# Technical notes: statement ingestion, secure email intake and evaluation

## 1. What actually runs, and what does not
| Part | Status | Notes |
|---|---|---|
| Statement reader: CSV, XLSX, pasted text | Runs | 15 invented layouts, every date, amount, balance and reference matches ground truth |
| Text PDF statements (several pages, repeated headers, password) | Runs | 2 invented PDFs; the password is used in memory only and never stored |
| Photo or scanned statement (vision model) | Runs, best effort | Only after the user consents (the image leaves our server). Clean, recompressed and resized images: 45/45 rows correct. Simulated phone photos: no wrong amounts or references, but a row was missed in 2 of 3 samples |
| Balance-chain self-check | Runs | Passes on every layout that has a balance column |
| Language-model column mapping | Runs, optional safety net | Changed no result on our layouts (see 6) |
| Secure email intake | Runs | 3 live emails, 5 offline tests, and a 20-email test (see 5) |
| Scanned PDFs through the vision path | Runs, best effort | Same consent rule as photos; not separately evaluated |
| Real bank statement formats | **Not tested** | All layouts are invented to imitate common export quirks |
| Replies sent from the inbox, automatic push of new email | **Not built** | Polling button only |

## 2. Setup
```powershell
git clone https://github.com/Zunairah-k/PayZen.git
cd PayZen
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
copy .env.example .env     # then add GEMINI_API_KEY and AGENTBOXD_API_KEY
```
Load the keys into the terminal for each session:
```powershell
Get-Content .env | Where-Object { $_ -match '^\s*[^#\s]\S*=' } | ForEach-Object { $k,$v = $_ -split '=',2; Set-Item "Env:$($k.Trim())" $v.Trim() }
```
Without keys the statement reader still works (deterministic mapper); only the model features and email intake need keys.

## 3. How to reproduce every result
| What | Command | Output |
|---|---|---|
| All automatic tests | `python -m pytest tests -q` | pass count |
| 17 layouts + input checks | `python -m tests.ingestion.test_layouts` | `docs/ingestion_test_report.md`, `docs/format_results.csv` |
| Model off vs on | `python -m tests.ingestion.ablation` | `docs/ablation_results.md/.csv` |
| Photo test, 4 conditions | `python -m tests.ingestion.degradation_eval` | `docs/photo_degradation_results.md/.csv` |
| Email test | `python -m tests.intake.email_eval baseline`, send 20 emails, then `... score` | `docs/email_eval_results.md/.csv` |
| Numbers in one place | `python -m tests.numbers_sheet` | printed |

## 4. Data
All data is synthetic. One fixed set of 80 invented transactions (seeded, with 24 identical fixed-fee payments and some payments without a reference) is rendered in 17 layouts: Indian and European number formats, Dr/Cr suffixes, signed and inverted amounts, separate time column, newest-first, junk headers and footers, wrapped narrations, merged-cell XLSX, tab-separated text, a no-header file, a file with no balance column, a multi-page PDF and a password-protected PDF. Photo tests use images drawn by our own code, then damaged (small JPEG, shrunk to 60%, tilted, blurred, darkened, grainy). Email tests use 20 invented emails. No real person's data was used.

## 5. Results
**Layouts:** 17/17 match ground truth; balance check passed on 16/17 (the 17th has no balance column). 7/7 input-handling checks give the expected clear outcome.
**Photo test** (3 images of 15 rows per condition):
| Condition | Rows fully correct | Wrong amounts | Wrong references | Balance check passed |
|---|---|---|---|---|
| clean | 45/45 | 0 | 0 | 3/3 |
| recompressed (JPEG 35) | 45/45 | 0 | 0 | 3/3 |
| resized (60%) | 45/45 | 0 | 0 | 3/3 |
| photographed (tilt, blur, dark, grain) | 15/45 | 0 | 0 | 3/3 |

(Rows are counted as correct only when all three of amount, balance and reference match and the row count is right; in the photographed condition 2 of 3 images returned 14 of 15 rows.)
**Email test:** | Measure | Result |
|---|---|
| emails sent: clean / malicious | 10 / 10 |
| emails processed | 20 of 20 |
| accepted: clean / malicious | 10 / 0 |
| blocked in total (held by Agentboxd / quarantined by our policy) | 10 (10 / 0) |
| errors | 0 |
| malicious emails stopped | 10 of 10 |
| clean emails wrongly blocked | 0 of 10 |
| statements read correctly from accepted clean emails | 3 of 3 |

**Model off vs on:** 17/17 layouts match ground truth in both modes; mean confidence 0.94 in both; the model answered on 17/17 layouts and agreed with the deterministic mapper on 16/17.

## 6. Failure examples and limitations
1. **A missed row in photos.** On simulated phone photos the vision model returned 14 of 15 rows in 2 of 3 samples. Every row it did read was correct, and the balance check passed because a missing first or last row cannot break the arithmetic. The app asked the user to confirm in those cases. Photo input is therefore best effort: we recommend CSV, XLSX or text PDF.
2. **The language model added nothing on our layouts.** The deterministic mapper already read all 17, so the model changed no result. We kept it as a safety net for unfamiliar headers and because the balance chain makes it safe, and we do not claim it improved accuracy.
3. **Our own policy was not exercised live.** In the live email run, Agentboxd held both malicious emails before our policy saw them. Our policy (scores, spoofed senders, incomplete checks) is covered by offline tests only.
4. Layouts, images and emails are invented by the people who wrote the code, so results show robustness to common quirks, not coverage of real banks. We say "tested on 17 layouts".
5. Small samples (3 images per condition, 20 emails); results are indicative, not statistical.
6. Ambiguous numeric dates default to day-first. Rows must be in file order, oldest-first or newest-first.
7. The Gemini free tier is rate-limited and may use requests to improve Google products. Statement mapping sends only column names and masked sample rows; images are sent only with consent; use synthetic images only.
8. Email attachments pass through Agentboxd (EU-hosted). Email records live in memory and reset on restart.

## 7. Models, libraries and sponsors
Gemini 3.1 Flash-Lite via Google AI Studio (column mapping, statement images); Agentboxd (agent email inbox, screening for spoofing, prompt injection and phishing, attachment scanning; Builder plan from the hackathon code). Python libraries: pdfplumber, openpyxl, charset-normalizer, httpx, Pillow, google-genai, FastAPI, pytest; reportlab is used only to generate test PDFs. Anthropic's API is supported as an optional alternative provider and is not used in the deployed app.

## 8. Privacy
Everything is processed in memory and nothing is stored on disk. API keys live only in environment variables. Real statements and screenshots should never be sent through the free model tier.