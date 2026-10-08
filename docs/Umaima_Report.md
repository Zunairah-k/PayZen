# PayZen - Day 1 Report (Wednesday, 7 October 2026)

**Project:** PayZen, a payment-proof verifier (ForgeHacks Online 2026, AI + Cybersecurity track)
**Author of this report:** Umaima
**Team:** Umaima, Zunairah (team lead), Alizah
**Repository:** https://github.com/Zunairah-k/PayZen (everyone commits directly to `main`)

---

## 1. Summary

Day 1 goal from the plan: *a thin slice working end to end*, meaning one statement plus a few screenshots should flow through the system and produce a verdict table in the UI, even if parts are stubbed.

**Result:** achieved. The pipeline (upload, API, verdicts, UI) works end to end using stub logic. Real screenshot extraction (Alizah) has been pushed. Real statement ingestion (Zunairah) is still in progress, so the matcher still runs on stub data. All my Day 1 deliverables are complete and pushed: backend scaffold, frontend, synthetic data generator, real redacted screenshots, and a competitor re-search.

| Planned for Day 1 (my part) | Status |
| --- | --- |
| Repo scaffold: backend API skeleton and frontend shell following frozen contracts | Done |
| Synthetic statement layouts 1 to 5 plus 20 genuine mock screenshots plus ground truth | Done |
| UI: two upload areas, results table with status chips, detail drawer | Done |
| Wire UI to backend and fix contract mismatches | Done (stub level) |
| Collect real redacted screenshots from own small transfers | Done (stored locally, git-ignored) |
| Competitor re-search (30 min) | Done (Section 8) |
| End-of-day thin-slice demo and list of top issues | Prepared (Section 10) |

---

## 2. Environment and setup

**Working location:** `C:\dev\PayZen`.

**Decision and reason:** I originally cloned the repo inside OneDrive in a folder with non-English characters in the path. I moved to `C:\dev` because OneDrive tries to sync thousands of dependency files (`venv`, `node_modules`), and non-ASCII paths can break tools such as Playwright and some Python and Node packages.

**Tools and versions**

| Tool | Version | Note |
| --- | --- | --- |
| Python | 3.14.5 | Worked for FastAPI, Pydantic and Uvicorn. Fallback: 3.13 if a package fails. |
| Node | 20.19.4 | Fine for Vite and React. |
| Git | 2.48.1 | |
| Editor | VS Code | Python interpreter set manually to `backend\venv\Scripts\python.exe` |

**Setup problems and fixes**

1. **PowerShell script policy blocked venv activation.** Fixed by allowing local scripts for the current user (`RemoteSigned`).
2. **VS Code did not list the backend virtual environment** because it was nested in `backend`. Fixed by choosing "Enter interpreter path" and pointing to the venv's `python.exe`.
3. **`requirements.txt` encoding.** Generated with `Out-File -Encoding ascii` instead of `>`, because PowerShell's `>` can write a file pip cannot read.
4. **Pip cache warnings** ("Cache entry deserialization failed") were harmless.
5. **Source Control badge showed 535 changes.** Cause: a `.venv` folder at the repo root that `.gitignore` did not cover (it only listed `venv/`). Fix: add `.venv/` to `.gitignore` and avoid blanket `git add .` until the badge is small.

---

## 3. Backend scaffold (FastAPI)

**Structure**

```
backend/
  requirements.txt
  app/
    __init__.py
    main.py            API endpoints
    models.py          frozen data contracts
    services/
      extractor.py     screenshot -> Claim            (Alizah)
      ingestor.py      statement file -> rows + meta  (Zunairah)
      matcher.py       claims + rows -> verdicts      (Alizah)
```

**Data contracts (Pydantic models).** These were frozen on the first night so three people could build in parallel.

- **Claim:** claim_id, source_file, image_hash, payer_name, payer_upi_id, payee_name, payee_upi_id, amount, currency, timestamp, reference, app_style_guess, status_shown, confidence (per field), extraction_notes.
- **StatementRow:** row_id, datetime, narration, debit, credit, balance, extracted_reference, name_hint, source_page_or_row.
- **StatementMeta:** coverage_start, coverage_end, mapping_used, balance_chain_result, parse_confidence, row_count, warnings.
- **Verdict:** claim_id, status, tier, matched_row_id, confidence, reasons, field_differences, follow_up_after, suggested_reply.
- **Status values:** Verified, Likely match, Contradicted, Not found, Duplicate, Can't verify yet.
- **VerifyRequest:** claims, rows and meta bundled for the verify endpoint.

Most fields are optional on purpose, because extraction can miss values.

**Endpoints**

| Method and path | Purpose |
| --- | --- |
| `GET /health` | Liveness check |
| `POST /claims/upload` | Accepts many screenshots, returns Claims |
| `POST /statement/upload` | Accepts one statement file, returns rows and meta |
| `POST /verify` | Accepts claims, rows and meta, returns Verdicts |

CORS allows the Vite dev server (`http://localhost:5173`).

**Stub strategy.** Each service file returns fake but valid data so the whole system runs on day one. Teammates replace the function bodies without touching the API or UI. The stub matcher marks a claim "Verified" when its reference equals a statement row's reference, otherwise "Not found".

**Verification done.** I tested all endpoints in the automatic Swagger page (`/docs`). `/verify` returned HTTP 200 with a valid verdict.

---

## 4. Frontend (React + Vite + TypeScript)

**Files built**

- `types.ts`: TypeScript mirrors of the backend contracts.
- `statusColors.ts`: one colour per verdict (green, teal, amber, red, purple, grey).
- `api.ts`: client functions for the three endpoints.
- Components: `UploadPanel` (two drag-and-drop zones), `SummaryBar` (money cards for verified, likely, at risk and pending, plus verdict count chips), `ResultsTable` (row per claim with status chip and confidence), `ReasonDrawer` (side panel with reasons and a screenshot-versus-statement comparison table that highlights differences).
- `App.tsx` and `App.css`: page layout and the run flow (upload claims, upload statement, verify, display).

**Design rules applied**

- The interface never uses the word "fake" for a single claim; it says Not found, Contradicted, Duplicate.
- A disclaimer appears in the detail drawer: "Decision support. Confirm in your own bank app before acting on high-value payments."
- Visual redesign (3D, animations, glassmorphism inspired by the Sentra landing-page reference) is deliberately deferred to Day 3 morning, after core features work.

**Test result with stubs.** I uploaded a synthetic screenshot (Sana Nair, Rs. 500) and `statement_04_datetime.csv`. The UI displayed a verdict table, money cards, and chips. The row showed "Test Payer, Rs. 300, Verified, 95%".

**What this proves and what it does not.**

- It proves the connection works: upload, API, contracts, UI.
- It does not prove any analysis. The stubs ignore the uploaded files and return hardcoded values, which is why the output did not match the screenshot.
- Correct expected result for that screenshot: **Likely match**. I checked the CSV, and line 42 has a credit of 500.00 for Sana Nair on 04-Oct at 20:42, but the statement narration contains no reference number, so the system must match on amount, time and name.

---

## 5. Synthetic data generator

**Purpose:** create realistic but entirely fake data so the team can build and test without real payment information, and so we have ground truth for evaluation later.

**Location:** script at `eval/generate_synthetic.py`; output in `data/synthetic/`. The script uses a fixed random seed, so output is reproducible. It runs in its own virtual environment (`eval/venv`) with Playwright and Chromium to render screenshots.

**What it creates**

1. **Master list of 68 transactions:** 60 credits from fake payers and 8 vendor debits. A large share of the credits are an identical Rs. 300 fee, which deliberately creates the "many equal amounts" collision case. Balances are computed so the balance chain stays arithmetically consistent.
2. **Five statement layouts** built from the same transactions:
   1. Standard columns (withdrawal and deposit), DD/MM/YY, date only.
   2. Single amount column with a Dr/Cr suffix, date only.
   3. Single signed amount column, full ISO timestamps.
   4. Separate date and time columns, DD-Mon-YYYY (this is the layout I tested with).
   5. Junk header block, Indian number grouping, "Rs." prefix, footer totals, date only.
3. **20 genuine payment screenshots** rendered from 4 generic visual styles (light, dark, blue header card, receipt style), with varied status wording, date formats, label names (UPI Ref No., UTR, Transaction ID, Reference No.), and a mix of PNG and JPEG compression. No real brand logos are used.
4. **A decoy ID on each screenshot** (Order ID, Txn Ref, or Payment ID), so the extractor must choose the real 12-digit reference.
5. **`ground_truth.csv`** with the expected verdict and reason for every screenshot.
6. **`master_payments.json`** with every underlying transaction, and a README stating all data is fake.

**Key design decisions**

- About 25 percent of credit narrations contain **no reference number**. Those claims should become "Likely match", forcing the fallback matching ladder to be exercised.
- Layouts 1, 2 and 5 contain only a date with no time, so matching on those must work from date plus amount plus name, not exact time.
- Reference numbers are unique 12-digit strings; narration patterns differ by layout.
- Only genuine claims exist so far. Seeded fakes, delayed payments and the larger 100-claim set are scheduled for Day 2.

---

## 6. Real redacted screenshots

I sent small amounts between teammates and saved screenshots of the payment screens. Names, numbers and UPI IDs are blurred or cropped. They are stored in `data/real-redacted/`, which is git-ignored so they never reach the public repository. Purpose: test Alizah's extractor on real layouts that our generator cannot imitate perfectly.

---

## 7. Git and collaboration

- The team works directly on `main` (no feature branches).
- Commits so far include my initial README commit, my scaffold commit, and two commits from Alizah ("Implement screenshot extraction and normalization foundation" and a follow-up).
- When I pulled, Git asked for a merge commit message because my local commits and Alizah's diverged. I learned two ways to handle it: accept the auto-generated merge commit, or undo the merge and use `git pull --rebase`, which keeps a clean linear history and keeps each person's own commit message visible.
- **Team habit adopted:** pull before starting, and pull then push when finished. Optionally set `pull.rebase true` globally.
- **Safety rule:** never commit keys or real data. `.gitignore` covers `venv/`, `.venv/`, `__pycache__/`, `node_modules/`, `.env`, `data/real-redacted/`.

---

## 8. Competitor re-search (7 October 2026)

**Goal:** check whether tools already do what PayZen does, so the originality claim stays honest. Method: web searches; results are from vendor sites and blogs, so treat them as indicative, not exhaustive.

### Category A: single-screenshot "fake payment screenshot" checkers

Examples: ScamShield AI, ScamScan, ScamDekho, ScamCheck, screenshotchecker.com, toolsda.com.

- **What they do:** read one screenshot with OCR or image forensics, check things like whether the UTR is exactly 12 digits, font and blur inconsistencies, known fake templates, and UPI handle reputation. Most are free and need no sign-up.
- **What they do not do:** match claims against *your* bank statement, handle batches, detect duplicates across payers, handle statement coverage and delays, or help you respond.
- **Their own limits:** one checker states that it does not verify a transaction with a bank; another states that you cannot reliably tell from the image and the only definitive answer is to check your own account. This supports PayZen's premise: proof comes from the receiver's own records.

### Category B: extraction-only tools

Example: imagetotable.ai turns UPI screenshots into a spreadsheet and treats the 12-digit UPI reference as the key to match against a statement.

- **Does:** batch extraction.
- **Does not:** do the matching or return fraud verdicts; the user does a lookup manually.

### Category C: accounting, society and ERP reconciliation

Examples: TallyPrime, myBillBook AI Recon, MyGate society accounting, Society Connekt, Bharat My Society, MIRA Smart Accountant, Sell.Do, AI Accountant.

- **Do:** reconcile bank statements to invoices or dues; several rely on gateways, virtual accounts or unique identifiers; MIRA advertises reading bank statements in any CSV or XLSX format with AI column identification.
- **Do not:** treat payer-supplied screenshots as untrusted claims or produce fraud-oriented verdicts such as Contradicted, Duplicate and Not found.
- **Implication for us:** any-format statement parsing is not unique by itself. Our differentiator must be the combination (see below).

### Category D: prevention by design (no screenshots needed)

Examples: Razorpay Smart Collect (virtual UPI IDs and bank accounts per customer), Paywize (dynamic QR codes and instant webhooks), SBI Collect (used by IIT Kanpur's event registration).

- **Do:** tie every payment to a unique identifier so reconciliation is automatic.
- **Limit for our users:** groups that collect through ordinary UPI QR codes or personal and club accounts, without a gateway, still receive screenshots.

### Evidence that the screenshot-and-UTR workflow is real

Public college event pages (for example Shyam Lal College's conference registration and Karunya's Electra '19 symposium) ask participants to send a transaction screenshot or UTR through a form and confirm registration only after payment is received, which implies manual checking.

### Positioning conclusion

| Claim | Safe to make? |
| --- | --- |
| "We detect fake screenshots" | No. This space is crowded and free. Do not pitch it this way. |
| "We read screenshots and statements with AI" | Not unique. |
| "We accept any statement format" | Not unique alone (similar capability exists in accounting tools). |
| "Batch verification of untrusted payment claims against the receiver's own statement, with evidence-based verdicts (Verified, Likely, Contradicted, Not found, Duplicate, Can't verify yet), one-to-one assignment, coverage-aware handling of delays, and ready-to-send replies, for people who collect via plain UPI" | **Yes, as the combination.** From my searches I did not find a tool doing all of this. State it as "we did not find", not "nobody does it". |

**Suggested wording for the README and Devpost description:** "Single-screenshot checkers analyse one image; accounting tools reconcile invoices; gateways avoid screenshots entirely. PayZen serves people who still collect through plain UPI and receive screenshots in bulk: it verifies each claim against the receiver's own statement and explains every verdict."

**Prepared answer for "why not just use a payment gateway?":** gateways solve this when you can use one; PayZen is for groups that cannot or do not, and its optional unique-link feature moves them toward prevention.

---

## 9. Problems faced and lessons

1. **Stub output looked like a real (wrong) result.** Lesson: label stub responses clearly (for example a visible "stub data" banner) so nobody mistakes placeholder output for analysis.
2. **Git merge editor opened unexpectedly.** Lesson: understand merge versus rebase; pull often.
3. **Large Source Control count from `.venv`.** Lesson: check `.gitignore` before the first commit.
4. **Path and environment issues on Windows** (OneDrive, non-ASCII path, execution policy, interpreter selection). Lesson: start in a short ASCII path outside cloud-synced folders.
5. **The statement narration may lack a reference.** Lesson: the matching ladder is not optional; it is needed for roughly a quarter of cases in our own data.

---

## 10. Open items and top issues for Day 2

1. **Statement ingestion is still stubbed** (Zunairah in progress); the matcher cannot give real verdicts until it is integrated.
2. **Extractor integration:** confirm Alizah's output matches the Claim contract on all 20 synthetic and the real redacted screenshots; add API keys through a local `.env` (never committed).
3. **Matcher** must implement the ladder (exact reference, then amount plus time plus name), one-to-one assignment, duplicate detection, and coverage-aware verdicts.
4. **Stub banner** in the UI until real logic lands.
5. **Dataset extension:** seeded fakes, delayed payments, and about 100 labelled claims.

---

## 11. Day 2 plan (my part)

- Reason cards with highlighted differences; inline editing of low-confidence fields.
- Money totals, CSV export, sample-data button.
- Extend the generator to about 100 claims with seeded fakes (edited amount, invented reference, reused screenshot, fake-app style, wrong payee, old screenshot) and delayed-payment cases.
- Evaluation script comparing predictions with ground truth per category.
- Stretch: unique payment link and QR generator.
- Start the Devpost description draft.

---

## Appendix: repository layout at end of Day 1

```
PayZen/
  README.md
  .gitignore
  backend/
    requirements.txt
    app/ (main.py, models.py, services/...)
  frontend/
    src/ (App.tsx, api.ts, types.ts, statusColors.ts, components/...)
  eval/
    generate_synthetic.py
  data/
    synthetic/ (screenshots/, statements/, ground_truth.csv, master_payments.json, README.md)
    real-redacted/   (git-ignored, local only)
  docs/
```

*Screenshots to add when documenting: the Swagger `/docs` page with a 200 response, the UI after "Verify payments", a few synthetic screenshots, the GitHub commits page.*
