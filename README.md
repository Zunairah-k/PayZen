# PayZen — Payment Proof Verifier

**Check the money, not the picture.** PayZen checks the payment screenshots you receive against **your own bank statement** and explains every verdict.

ForgeHacks Online 2026 · Track: **AI + Cybersecurity** · Team: Umaima · Zunairah · Alizah

**Live app:** https://payzenn.vercel.app/ · **API docs:** https://payzen-z43b.onrender.com/docs

> PayZen is **decision support, not a fraud detector.** It reports evidence and confidence, never calls a person or a single screenshot "fake", and works hardest to avoid its worst error: a **false Verified** (a payment marked as paid that never arrived).

---

## The problem

A payment screenshot is not proof of payment. It can be edited, come from a fake payment app, be reused by several people, or describe a payment that never arrived. The only reliable proof is the **receiver's own bank or UPI statement**, but checking hundreds of screenshots against a statement by hand is slow and error-prone. A wrong call either accepts a payment that never arrived or wrongly accuses someone who paid.

**Who it's for:** fest and club treasurers, housing societies, donation, tuition and trip collectors, and WhatsApp or Instagram sellers who collect through plain UPI and receive screenshots in bulk.

**How it answers the track prompt (recognize, prevent, verify, respond):**

| Verb | What PayZen does |
|---|---|
| Recognize | Flags contradicted amounts, wrong references, reused screenshots and missing payments |
| Verify | Checks every claim against the receiver's own statement, with evidence |
| Prevent | A secure email inbox that screens spoofing, prompt injection and phishing before anything is read; a unique payment link and QR prototype |
| Respond | Polite, non-accusatory replies in English, Hindi and Telugu; a follow-up list; re-check against a newer statement |

*Honesty note:* we found no evidence that AI itself is driving UPI screenshot fraud, so we frame this as fraud enabled by modern technology (photo editors, fake payment apps, reused screenshots). AI agents that read email are, however, a new target for prompt injection, which is why the email channel is screened.

---

## What you get

Each screenshot gets one of six verdicts, with plain-language reasons, the matched statement row and a confidence:

| Verdict | Meaning |
|---|---|
| **Verified** | Exact 12-digit reference **and** amount match a statement credit; nothing conflicts |
| **Likely match** | A plausible credit exists but reference or identity proof is incomplete; never auto-accepted |
| **Contradicted** | The reference is on the statement but details differ (the exact differences are shown) |
| **Not found** | No compatible credit in a period the statement covers |
| **Duplicate** | The claim shares a reference or identical image with another claim |
| **Can't verify yet** | The statement ends before the payment; upload a newer one and re-check |

Plus money totals (verified, likely, at risk, pending), CSV export and a follow-up list with a ready-to-send reply per payer.

---

## Try it in 60 seconds

1. Open https://payzenn.vercel.app/ and click **Try sample data**. It shows all six verdicts and uses no model call, so it always works.
2. To try the real pipeline, use the synthetic files in `data/synthetic/` (screenshots, statements) and `data/synthetic/demo/` (small files that trigger each prompt: password PDF, ambiguous dates, missing row, picture consent).
3. The free host sleeps when idle, so the first request can take about a minute.

---

## How it works

```mermaid
flowchart LR
  subgraph IN[Three ways in]
    U[Upload screenshots]
    W[WhatsApp chat export ZIP]
    E[Email to a secure inbox<br/>Agentboxd screening]
  end
  U --> X
  W --> X
  E -->|clean mail only| X[Screenshot reader<br/>Gemini vision to Claim]
  S[Bank or UPI statement<br/>CSV, XLSX, PDF, text, photo] --> I[Statement reader<br/>balance-chain self-check]
  X --> M[Matcher<br/>deterministic ladder<br/>one credit, one claim]
  I --> M
  M --> V[Verdict, reasons, evidence]
  V --> R[Replies EN / HI / TE<br/>follow-up list, CSV export]
  N[Newer statement] --> RC[Re-check] --> M
```

**Design principle: the model proposes, the arithmetic verifies.** AI helps *read*; every decision that matters is deterministic code, so every verdict is explainable and testable.

1. **Read the statement, in any format.** CSV, XLSX, pasted text, text PDF (multi-page, repeated headers, password) and, with the user's consent, photos and scanned PDFs. Two guessers propose which column is the date, narration, debit, credit and balance: rules, and an optional language model that sees **only column names and masked sample rows** and answers with column numbers. A parser applies the guess and the **balance-chain check** verifies it: every row's balance must equal the previous balance plus credit minus debit. If the chain holds across dozens of rows, the columns were read correctly. If not, PayZen retries, then asks the user one question. A file is never rejected for its format.
2. **Read each screenshot.** A Gemini vision model returns the text as printed; deterministic normalizers clean the amount, time and 12-digit reference, attach a confidence per field and an image fingerprint. Weak or ambiguous fields are left empty, never guessed.
3. **Match, deterministically.** See the ladder below.
4. **Explain.** Verdict, reasons, evidence, confidence, and a polite reply addressed to the payer.
5. **Re-check.** Claims marked *Can't verify yet* are re-run against a newer statement.

| Uses AI | Deliberately does not |
|---|---|
| Reading screenshots; reading photos and scans of statements (consent); suggesting statement columns (a helper; arithmetic decides); screening email (Agentboxd) | The balance check, matching, verdicts, duplicate and coverage logic, replies (templates) |

### Three ways in, one engine

- **Upload** screenshots and a statement on the website.
- **WhatsApp chat export:** upload the "export chat with media" ZIP and every picture is read like a normal upload. Only real images (checked by file signature), capped file counts and sizes, 25 pictures by default and 60 at most, nothing written to disk, and the chat text is never given to a model.
- **Secure email inbox:** payment proofs can be emailed to an [Agentboxd](https://agentboxd.com) inbox that scores every message for spoofing, prompt injection and phishing. Held mail is never opened. Clean mail is checked again by PayZen's own policy and its attachments then go through the same pipeline. **Email text is never given to a model as instructions.**

Every claim carries a **source tag** (Upload / WhatsApp / Email), so the same screenshot arriving through two doors is caught as a duplicate.

### The matching ladder

| Tier | Evidence | Verdict |
|---|---|---|
| 1 | Exact reference **and** equal amount, nothing conflicting | Verified (0.85–0.97) |
| 4 | Reference found, another field differs | Contradicted, with exact differences |
| 2 | No reference proof; equal amount, time within 30 min, similar payer name | Likely match |
| 3 | No reference proof; equal amount and time only | Likely match (low) |
| 5 | Nothing found and the claim is safely inside the statement's coverage | Not found |
| — | Coverage cannot support a conclusion | Can't verify yet |

- A reference match alone never verifies; the amount must match too. Tiers 2 and 3 can never produce Verified.
- Only statement **credits** count as payment evidence.
- **One credit supports one claim**, chosen by global optimal assignment (Hungarian algorithm), not first come first served.
- **Coverage-aware:** a claim after, or within one window of, the statement's end becomes *Can't verify yet*, never *Not found*.
- **Duplicates** come from real evidence: byte-identical files, the same reference, or a matching image fingerprint with corroboration. A fingerprint alone is only a note.
- Results are deterministic: same input, same output.

Full rules and confidence formulas: [`docs/TECHNICAL_REFERENCE.md`](docs/TECHNICAL_REFERENCE.md).

---

## Results

All data is **synthetic**, written by the team. Numbers are exactly as printed by the scripts.

| What was tested | Result | Output file |
|---|---|---|
| **Matching rules:** 100 labelled claims (55 genuine, 45 seeded fakes), 5 statement layouts, screenshot reading simulated | Accuracy 0.95–0.96; **0/45 fakes marked Verified**; 0/55 genuine marked Not found; 5/5 delayed payments resolved by re-check | `eval/results/results.md` |
| **Real screenshot reading + matching** (Gemini), 27 claims × 4 conditions: clean, recompressed, resized, photographed | Amount, reference and time right on **27/27** in every condition; verdict right 25/27; **0/11 fakes marked Verified**; 0/16 genuine marked Not found | `eval/results/screenshot_eval.md` |
| **Statement reader:** 17 layouts + 2 stress layouts (Indian grouping, Dr/Cr, signed and inverted amounts, newest-first, junk headers, wrapped narrations, merged-cell XLSX, no header, no balance column, multi-page and password PDFs) | 17/17 and 2/2 match ground truth on every date, amount, balance and reference; balance check passed on 16 (one layout has no balance column) | `docs/ingestion_test_report.md`, `docs/format_results.csv` |
| **Ablation:** column-mapping model off vs on | Identical: 17/17 both ways. The model is a safety net, not the source of accuracy | `docs/ablation_results.md` |
| **Photo of a statement:** 3 images × 4 conditions | Clean, recompressed, resized: 45/45 rows. Simulated phone photo: 15/45, with a dropped or date-shifted row | `docs/photo_degradation_results.md` |
| **Email intake:** 10 clean + 10 malicious emails | 20/20 processed; **10/10 malicious stopped** (all by Agentboxd); 0/10 clean blocked; 3/3 statements read | `docs/email_eval_results.md` |
| **One real payment:** a real GPay ₹1 payment (names covered) against a statement built to mirror the bank's format | Verified (97%); with the reference altered by one digit: Not found, with a "may be a misread" note | — |
| Automated tests | **642 passed** | `python -m pytest tests -q` |

---

## What works and what doesn't

**Works end to end:** the three ways in; all six verdicts with reasons; re-check; replies in three languages; follow-up list; CSV export; statement preview prompts (green tick, one question, PDF password, picture consent); a deployed app; the secure email channel holding an injection attempt in a live test.

**Limits, stated plainly:**

- **No real bank export has been tested.** Layouts are invented to imitate common quirks. We say "tested on 17 layouts", never "supports every bank".
- **Photos of statements are best effort.** A tilted, blurred photo can drop a row or shift the date column by one row, and the balance check cannot see wrong dates. Every picture-based statement therefore asks the user to check the dates. CSV, XLSX and text PDF are recommended.
- **Same reference reused by a different person is labelled Contradicted, not Duplicate** (0/4 in our test). It is never marked Verified, so the direction is safe, but the label is wrong. An identical reused image is caught as Duplicate (4/4).
- **The model made no accuracy difference** on our layouts; the rules already read all of them.
- **Email:** all blocking was done by Agentboxd, so PayZen's own quarantine policy is verified by offline tests only. Spoofed senders could not be tested. One sender, 20 emails.
- **Payment link and QR is a prototype.** It only helps future payments, and whether a bank copies the payment note into the statement is untested.
- **Screenshot degradation is simulated** by our own code; real phone photos are harder. Reading is slow on the free model tier (about 25 screenshots in 3 minutes).
- **Time saved has not been measured**, so we do not claim a number.
- Hindi and Telugu replies are machine-drafted; the rest of the interface is English.
- **Out of scope:** cash payments, forged statements (a user downloads their own) and collusion.

---

## Privacy and responsible use

- Everything is processed **in memory**; nothing is stored. A PDF password is used once and not kept.
- **Disclosure:** screenshots are sent to Google Gemini to be read, so the app tells users to use synthetic or blurred images. Statement mapping sends only column names and masked sample rows (digits to 9, letters to x). A **picture of a statement** is sent only after the user ticks a consent box.
- **Untrusted text is escaped** in the interface (email subject, sender, file names); email text is never used as instructions for a model.
- **Wording is never accusatory:** "could not be verified", "details differ", "please recheck", with the footer "Decision support. Confirm in your own bank app before acting on high-value payments."
- **Data:** synthetic only in the repo, tests, demo and video. The test data generator is for evaluation use only. API keys live in environment variables and are never committed.

---

## Setup and run

Requirements: Python 3.10+ and Node 18+.

```powershell
# backend (http://localhost:8000)
python -m venv backend\venv
backend\venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
cd backend
uvicorn app.main:app --reload

# frontend (http://localhost:5173)
cd frontend
npm install
npm run dev
```

Copy `.env.example` to `.env` and set the keys below. **Without any key** the statement reader still works (rules only) and "Try sample data" works; screenshot reading and the email channel need keys.

| Variable | Used for |
|---|---|
| `GEMINI_API_KEY` | Screenshot reading, statement photos, column-mapping helper (Google AI Studio free tier; model `gemini-3.1-flash-lite`, override with `GEMINI_MODEL`) |
| `AGENTBOXD_API_KEY` | Secure email inbox |
| `CORS_ORIGINS` (backend host) | The frontend URL, with no trailing slash |
| `VITE_API_URL` (frontend host) | The backend URL, with no trailing slash |

### Reproduce every number

| Result | Command |
|---|---|
| All tests | `python -m pytest tests -q` |
| Statement layouts, input checks | `python -m tests.ingestion.test_layouts` |
| Model off vs on | `python -m tests.ingestion.ablation` |
| Photo-of-statement conditions | `python -m tests.ingestion.degradation_eval` |
| Email test | `python -m tests.intake.email_eval baseline`, send the 20 emails, then `... score` |
| Matching rules on 100 claims | `python eval/generate_synthetic.py` then `python eval/run_eval.py` (needs `pip install -r eval/requirements.txt` and `python -m playwright install chromium`) |
| Real screenshot reading | `python eval/screenshot_eval.py` (needs `GEMINI_API_KEY`; about 12 minutes) |
| Check your own statement locally | `python -m tests.ingestion.real_check "path\to\statement.csv"` |

---

## Repository

```text
backend/app/
  main.py, models.py       API and the shared data contracts (Claim, StatementRow, StatementMeta, Verdict)
  ingestion/               statement reading: loader, pdf_loader, vision_loader, mapping, parser,
                           normalize, references, chain (balance check), coverage, pipeline, report
  intake/                  secure email inbox (Agentboxd) and WhatsApp ZIP intake
  services/                extractor, vision_gemini, matcher, rechecker, reply_generator, edit_hint
  payment_links.py         unique payment link and QR (prototype)
frontend/src/              React + Vite app: landing page, verify flow, results, reason drawer, follow-up list
eval/                      synthetic data generator, evaluation scripts, results/
data/synthetic/            100 labelled claims, screenshots, statements, demo files, degraded copies
tests/                     unit, ingestion, intake and integration tests
docs/                      test reports, results files, technical reference
```

---

## Credits, tools and honest AI use

- **Runs in the product:** Google Gemini (screenshot reading, statement photos, column-mapping helper) and Agentboxd (sponsor; email screening, with the hackathon Builder plan). Matching, verdicts and the balance check use no AI.
- **Built with** AI coding assistants; the team reviewed, ran and tested the code. Libraries: FastAPI, pandas, openpyxl, pdfplumber, Pillow, React, Vite, Playwright (synthetic screenshots), reportlab (test PDFs only). Hosting: Vercel (frontend) and Render (backend).
- **How this differs from what exists** (from a short search, not exhaustive): screenshot-to-spreadsheet extractors and accounting tools that match statements to invoices exist, and gateways avoid screenshots altogether. We did not find a tool that checks a batch of *untrusted* screenshots against the receiver's own statement with explained verdicts, a secure email door and a reply workflow. The contribution is that combination.
- Built during the ForgeHacks build window (October 3–10, 2026), using existing open-source libraries.

## Team

| Member | Built |
|---|---|
| **Umaima** | API, the whole web interface (landing page, verify flow, three-door intake, verdict explanation, follow-up list, EN/HI/TE payer messages), synthetic dataset and evaluation scripts, deployment |
| **Zunairah** | Statement reader for all formats (CSV, XLSX, text, text and password PDF, photo and scanned), balance-chain check, secure email intake, WhatsApp ZIP intake, payment link prototype, ingestion, photo and email evaluations |
| **Alizah** | Screenshot extraction and normalization, matching engine and verdicts, replies, re-check, edit hint, architecture, privacy and deployment documents |

## More detail

[`docs/TECHNICAL_REFERENCE.md`](docs/TECHNICAL_REFERENCE.md) (full matching rules, confidence rules, API notes) · [`API_INTEGRATION.md`](API_INTEGRATION.md) · [`ARCHITECTURE.md`](ARCHITECTURE.md) · [`PRIVACY_SECURITY.md`](PRIVACY_SECURITY.md) · [`DEPLOYMENT.md`](DEPLOYMENT.md)
