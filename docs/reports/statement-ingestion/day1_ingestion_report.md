# Day 1 report: statement ingestion

Generated 2026-10-08 by `python -m tests.ingestion.test_layouts` (language-model policy: `never`; model consulted on 0 of 17 layouts).

## What was built (`backend/app/ingestion`)

- `loader.py`: CSV, XLSX and pasted text; encoding and delimiter detection, true header row among junk lines, spacer columns dropped.
- `mapping.py`: deterministic column mapper plus a language-model mapper that sees only column names and masked sample rows; replies validated as column indices only.
- `normalize.py`, `parser.py`, `references.py`: Indian number grouping, currency symbols, Dr/Cr, many date formats, wrapped narrations stitched, footers and totals dropped, 12-digit reference and name hint extraction.
- `coverage.py`: the period a statement covers, so late payments become "Can't verify yet" instead of "Not found".
- `chain.py`, `report.py`, `pipeline.py`: balance-chain self-verification in both directions, debit/credit flip repair, parse report with confidence; the model proposes, the arithmetic decides.

## Results on synthetic layouts

17 of 17 layouts parsed with every date, amount, balance and reference matching ground truth.

| Layout | Result | Rows parsed | Balance chain | Mapping used |
|---|---|---|---|---|
| 01_standard | ok | 80/80 | pass (79/79) | heuristic |
| 02_amount_drcr_suffix | ok | 80/80 | pass (79/79) | heuristic |
| 03_signed_amount | ok | 80/80 | pass (79/79) | heuristic |
| 04_mon_dates_separate_time | ok | 80/80 | pass (79/79) | heuristic |
| 05_indian_grouping_symbols | ok | 80/80 | pass (79/79) | heuristic |
| 06_junk_header_footer | ok | 80/80 | pass (80/80) | heuristic |
| 07_wrapped_narrations | ok | 80/80 | pass (79/79) | heuristic |
| 08_semicolon_cp1252_decimal_comma | ok | 80/80 | pass (79/79) | heuristic |
| 09_xlsx_merged_spacer | ok | 80/80 | pass (79/79) | heuristic |
| 10_embedded_reference_patterns | ok | 80/80 | pass (79/79) | heuristic |
| 11_app_style_newest_first | ok | 80/80 | pass (79/79) | heuristic |
| X1_inverted_sign_convention | ok | 80/80 | pass (79/79) | heuristic+flip |
| X2_no_balance_column | ok | 80/80 | unavailable (0/0) | heuristic |
| X3_no_header_row | ok | 80/80 | pass (79/79) | heuristic |
| X4_tab_separated | ok | 80/80 | pass (79/79) | heuristic |
| 12_text_pdf_page_breaks | ok | 80/80 | pass (79/79) | heuristic |
| 13_text_pdf_password | ok | 80/80 | pass (79/79) | heuristic |

## Failures

None on this run.

## Known limits

- PDF, scanned and photo statements are not handled yet (clear message returned; Day 2).
- Old `.xls` files ask the user to re-save as `.xlsx` or `.csv`.
- A narration wrapped in the middle of a word gets a space inserted; references are unaffected, name hints can be.
- The layouts are invented to imitate common export quirks; they do not claim to match any real bank.
