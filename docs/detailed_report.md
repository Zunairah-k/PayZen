# Day 1 Detailed Report: Statement Ingestion

**Owner:** Zunairah  |  **Project:** Payment Proof Verifier (ForgeHacks Online 2026, AI + Cybersecurity)
**Code:** `backend/app/ingestion/`  |  **Tests:** `tests/ingestion/`

---

## 1. In simple terms

**The problem.** Our tool checks payment screenshots against the receiver's own bank statement. But every bank exports statements differently: different column names, date styles, number formats, junk lines at the top, totals at the bottom, and sometimes newest-first ordering. If the tool can't read the statement correctly, nothing after it works.

**What I built.** A "statement reader" that takes almost any CSV or Excel statement, or pasted text, and turns it into a clean list of transactions: date, description, money in, money out, balance, and the 12-digit payment reference. It never refuses a file because of its format.

**How it stays honest.** It guesses which column is which, then proves the guess with arithmetic. In a real statement, every row's balance equals the previous balance plus money in minus money out. If that holds across dozens of rows, the columns were read correctly. If it doesn't, the reader says where it broke and tries a fix. The guess is a proposal and the math decides. This is the project's core principle ("the model proposes, the math verifies"), applied to the first stage.

**What I tested.** 15 deliberately messy statement layouts built from the same 80 invented transactions. All 15 were read back with every date, amount, balance and reference matching the ground truth.

**What it can't do yet.** PDF, scanned and photo statements (planned for Day 2). Results so far are on invented layouts, so they show robustness to common mess, not coverage of any real bank.

---

## 2. Pipeline

```
file or pasted text
  -> loader.py      decode, detect delimiter, read rows, find the real header row
  -> mapping.py     propose which column is date / narration / debit / credit / balance
                    (deterministic proposer + optional language-model proposer)
  -> parser.py      apply each mapping to every row (normalize.py cleans each cell)
  -> chain.py       verify with the balance-chain arithmetic, in both row directions
  -> pipeline.py    keep the mapping the arithmetic confirms; retry or repair if none does
  -> references.py  extract the 12-digit UPI reference and payer-name hint
  -> coverage.py    compute the period the statement covers
  -> report.py      parse report + confidence score for the preview screen
output: IngestResult(ok, rows[StatementRow], meta[StatementMeta], report[ParseReport])
```

---

## 3. What each module does

| File | Responsibility |
|---|---|
| `loader.py` | Reads CSV, XLSX and pasted text. Decodes bytes (BOM, UTF-8/16/32, charset detection, cp1252 and latin-1 fallback). Picks the delimiter (`, ; tab \|`, or a `sep=` line) by which one gives consistent column counts. Keeps each row's original line number. Drops blank spacer columns. Finds the true header row among junk lines by header vocabulary plus whether transaction-looking rows follow. If there is no header, it invents column names from the contents. Limits: 20 MB, 100,000 rows. PDF, image and old `.xls` files return a clear, actionable message instead of a crash. |
| `normalize.py` | Cell cleaning, all deterministic. Money becomes `Decimal` to 2 places. Handles `Rs.`, rupee sign, Indian grouping (1,50,000.00), European format (1.234,56), brackets and trailing minus as negatives, and Dr/Cr markers. Dates: DD/MM/YY, ISO, `06-Oct-2026`, compact; a separate time column; day-first vs month-first decided from the whole column's evidence. `mask_cell` hides content before anything reaches a language model (digits become 9, letters x/X). |
| `mapping.py` | Two proposers feed one verifier. **Heuristic:** header words plus what cells contain. **Language model:** sees only column names plus up to 6 masked sample rows and answers with column indices. Replies are validated strictly (integers inside the column range only), so text hidden in a statement can't steer anything but an index. Temperature 0, replies cached, default `Gemini gemini-3.1-flash-lite` on the free tier (override with GEMINI_MODEL; Anthropic is supported as an alternative provider).. It never raises: any failure falls back to the deterministic mapper. |
| `parser.py` | Applies a mapping to every row. Classes: transaction, continuation (a wrapped narration stitched onto the previous row; a split inside a 12-digit number is rejoined without a space), opening-balance row (used as the chain's starting point), skipped (junk, totals, footers, repeated page headers), and lost (data-looking rows it could not read, counted and reported). Resolves debit vs credit from two columns, a signed amount, a Dr/Cr suffix, or a separate type column. |
| `references.py` | Extracts the 12-digit reference with a confidence label. **High:** labelled (`UTR:`, `RRN`, `Ref No`) or right after UPI/IMPS/NEFT/RTGS. **Medium:** a single bare 12-digit number. **Low:** several different bare numbers. A reference taken from a dedicated reference column is treated as high. Also extracts a payer-name hint (a hint only, never used alone for a Verified verdict). |
| `coverage.py` | Computes the statement's first and last moment. A date-only statement covers its last day until 23:59:59. `position_in_coverage` classifies a claim time as before / after / near_end (inside the 24-hour settle buffer) / inside / unknown, so the matcher never says "Not found" for a payment the statement could not contain yet. |
| `chain.py` | The verifier. Checks `balance[i] = balance[i-1] + credit - debit` with a 0.01 tolerance. Tries both file directions and keeps the one the arithmetic supports, so newest-first exports work. A break reports the row, expected vs actual, and a hint (debit/credit swapped, missing row, sign handling). Evidence is "strong" at 10 or more checks. |
| `report.py` | The parse report: what was understood, skipped and lost, mapping used, chain result, warnings, and a plain-language message. Confidence is a transparent rule, not a trained probability: base by chain outcome (pass 0.97, partial 0.70, unavailable 0.60, fail 0.30) times the share of rows parsed, minus small penalties for assumed or conflicting date order, a synthesized header, or an incomplete mapping. |
| `pipeline.py` | Orchestration. Candidates: deterministic mapping, then the model's mapping, then a model retry given the chain failure as feedback, plus a debit/credit-flipped twin of any mapping whose chain fails (repairs inverted sign conventions). Candidates are ranked by chain status, pass rate, parse rate and mapping completeness, and the best wins. If nothing verifies, it returns the best attempt with `needs_confirmation=True` for the one-tap preview (`mapping_override`). It never raises to the caller. |
| `models.py` | `StatementRow` and `StatementMeta` for the ingestion output (Decimal and datetime), with `to_dict()` for the API. |

---

## 4. Design decisions and why

1. **The model proposes, the math verifies.** A wrong column guess fails the balance arithmetic, which is very hard to satisfy by accident.
2. **Never reject a file for its format.** Failures become a preview plus a one-tap confirmation, not an error. This follows the lesson from a previous hackathon, where judges penalised a tool that demanded exact input formatting.
3. **Privacy by construction.** Only column names and masked sample rows can reach a language model. No names, amounts, references or account numbers. Nothing is written to disk.
4. **Two independent proposers.** The deterministic mapper works offline and costs nothing, and the model covers layouts the rules don't anticipate. Because both go through the same verifier, the model can't make results worse.
5. **Exact money.** `Decimal` everywhere, never float, so balance arithmetic is exact.
6. **Coverage-aware by design.** Ingestion reports the covered period and a settle buffer so later stages can say "Can't verify yet" instead of wrongly accusing an honest payer.
7. **Honest uncertainty.** Weak evidence (fewer than 10 balance checks), assumed date order, no balance column and lost rows all become visible warnings and a lower confidence, not silent success.

---

## 5. Test method and results

**Method.** `tests/ingestion/layouts.py` builds one fixed set of 80 invented transactions (seeded, reproducible, with a block of 24 identical fixed-fee amounts and some NEFT rows without references), then renders it in 15 different layouts. `tests/ingestion/test_layouts.py` parses each layout and compares every row with the ground truth: date (and time where the layout has one), debit, credit, balance, 12-digit reference, plus the expected balance-chain status. The test fails if any single row differs.

**Layouts (11 core + 4 extra stress):**

| # | Layout | What it tests |
|---|---|---|
| 01 | Standard columns, DD/MM/YY | Baseline, dedicated reference column |
| 02 | One amount column with Dr/Cr suffix | Direction from marker |
| 03 | One signed amount column | Direction from sign |
| 04 | DD-Mon-YYYY plus separate time column | Date and time merging |
| 05 | Indian grouping and currency symbols, UTF-8 BOM | Number cleaning |
| 06 | Junk header block, opening-balance row, footer totals | Header detection, footer removal, opening anchor |
| 07 | Narrations wrapped across two rows (every 5th split inside the reference) | Row stitching |
| 08 | Semicolons, cp1252, decimal comma | Delimiter, encoding, European numbers |
| 09 | XLSX with merged cells and a spacer column | Spreadsheet quirks |
| 10 | Six different reference patterns in narrations | Reference extraction |
| 11 | App-style export, newest first, renamed columns, DEBIT/CREDIT type | Ordering, renamed columns |
| X1 | Signed amount with inverted sign convention | Arithmetic repair (flip) |
| X2 | No balance column | Graceful degradation |
| X3 | No header row | Synthesized header |
| X4 | Tab-separated pasted text | Pasted-text path |

**Results (offline, deterministic mapper only; policy `never`):**

| Layout | Rows parsed | Balance chain | Mapping used |
|---|---|---|---|
| 01 to 05, 07 to 11, X3, X4 (each) | 80/80 | pass (79/79) | heuristic |
| 06_junk_header_footer | 80/80 | pass (80/80, the opening-balance row adds one check) | heuristic |
| X1_inverted_sign_convention | 80/80 | pass (79/79) | heuristic + flip |
| X2_no_balance_column | 80/80 | unavailable (0/0) | heuristic |

**15 of 15 layouts matched ground truth on every date, amount, balance and reference.** The only layout without a passing chain is X2, by design, since it has no balance to check. There the system flags the numbers as not self-verified.

**Language-model path (Gemini free tier, `gemini-3.1-flash-lite`):** the model was consulted live on the first three layouts and its column mapping agreed with the deterministic mapper on all three. The full 15-layout run with the model enabled (`INGEST_TEST_POLICY=always`) also matched ground truth on all 15. Because the balance chain decides, the model can only confirm or add a candidate mapping; it can't make a result worse. Only column names and masked sample rows are sent to the model (no names, amounts, references or account numbers).

**How to reproduce:**
```
python -m tests.ingestion.test_layouts      # table + auto-generated docs/day1_ingestion_report.md
python -m pytest tests/ingestion -q         # same checks under pytest
```

---

## 6. Refinements made during Day 1

- **Date-order warning:** ISO and month-name dates no longer trigger a misleading "ambiguous date" warning or a confidence penalty, because those formats carry their own order. Only all-numeric dates such as 06/10/2026 with no disambiguating evidence are marked "assumed day-first".
- **Reference-column confidence:** a reference read from a dedicated reference column is now high confidence. Otherwise the matcher would have downgraded good Verified matches.

---

## 7. Limitations (state these in the README)

- **Synthetic data only.** The layouts are invented to imitate common export quirks and were written by the same team that wrote the parser. 15/15 shows robustness to those quirks. It does not prove coverage of any real bank. Say "tested on 15 layouts", never "supports all banks".
- No PDF, scanned or photo statements yet (a clear message is returned; Day 2).
- Old `.xls` files must be re-saved as `.xlsx` or `.csv`.
- A narration wrapped in the middle of a word gets a space inserted. References are unaffected; name hints can be.
- Rows are assumed to be in monotonic file order (oldest-first or newest-first). A statement with shuffled rows will fail the chain and ask for confirmation.
- Ambiguous all-numeric dates default to day-first (an Indian-statement assumption) and are flagged.
- The 12-digit reference is the UPI/IMPS length. Longer alphanumeric NEFT UTRs are deliberately not returned as references.

---

## 8. Hand-off to the team

- **Entry points:** `ingest_statement(bytes_or_path, filename, llm_policy="always"|"fallback"|"never")` and `ingest_text(text)`, both returning `IngestResult(ok, rows, meta, report)`.
- **Preview screen (Umaima):** show `report.user_message`, `report.mapping_summary`, `report.chain` and `report.warnings`. When `report.needs_confirmation` is true, let the user pick columns and call again with `mapping_override` (`Mapping.from_dict`). The file is never refused.
- **Matcher (Alizah):** use `meta.coverage_start` and `meta.coverage_end` with `position_in_coverage()` for coverage-aware verdicts. Use `row.extracted_reference` together with `row.reference_confidence`; require "high" for a Verified verdict.
- **Day 2 integration note:** the shared API models in `backend/app/models.py` use float and str. The ingestion models use Decimal and datetime. A small converter is needed at the API boundary (`row.to_dict()` already gives strings for Decimal and ISO strings for datetimes).

---

## 9. Day 2 plan (my part)

1. Text PDF tables with page breaks, repeated headers and a password prompt (password used locally, never stored).
2. Pasted-text polish and photo-of-statement via the vision path.
3. Grow the chaos formats from 15 to the plan's 12-core set plus extras, and build the harness that reports parse success and chain result per format.
4. Ablation for Day 3: results with the model off (`never`) vs on (`always`).
5. Integrator duties: merge at 1:00 pm and 6:00 pm, run the smoke test.

---

## 10. README-ready paragraph

> **Any-format statement ingestion.** Users upload their own bank statement as CSV, XLSX or pasted text, in whatever layout their bank uses; no reformatting is required. The loader decodes the file, finds the real header row among junk lines and drops footers and totals. A deterministic mapper and an optional language model each *propose* which column is the date, narration, debit, credit and balance (the model sees only column names and masked sample rows, never real names, amounts or references). A deterministic parser applies each proposal, and a **balance-chain check** (every row's balance must equal the previous balance plus credit minus debit, in either file direction) *verifies* it. The mapping the arithmetic confirms wins; if none does, the user confirms the mapping in one tap and the file is never rejected. On our 15 synthetic layouts the pipeline recovered every date, amount, balance and 12-digit reference correctly. The layouts are invented, so we report this as robustness to common export quirks, not as support for any specific bank.