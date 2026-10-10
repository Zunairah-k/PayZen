# Statement ingestion: test report (auto-generated)

Generated 2026-10-08 by `python -m tests.ingestion.test_layouts` (language-model policy: `never`; model consulted successfully on 0 of 17 layouts).

## What is covered

- **Input types:** CSV (any delimiter or encoding), XLSX, pasted text, text PDF (multi-page, repeated headers, password-protected).
- **Layout mess:** junk header and footer blocks, opening-balance rows, wrapped narrations (including splits inside a 12-digit reference), Indian and European number formats, currency symbols, Dr/Cr suffixes, signed amounts, inverted sign convention, separate time column, newest-first order, no header row, no balance column.
- **Ground truth:** every parsed row is compared with the invented transaction it was rendered from: date (and time where present), debit, credit, balance and the 12-digit reference.
- **Self-check:** the balance chain must hold on every checked row (expected `unavailable` only for the layout with no balance column).

## Layout results

**17 of 17 layouts** matched ground truth on every date, amount, balance and reference.

| Layout | Type | Result | Rows parsed | Balance chain | Mapping used | Confidence | Asks user to confirm |
|---|---|---|---|---|---|---|---|
| 01_standard | CSV | ok | 80/80 | pass (79/79) | heuristic | 0.97 | no |
| 02_amount_drcr_suffix | CSV | ok | 80/80 | pass (79/79) | heuristic | 0.97 | no |
| 03_signed_amount | CSV | ok | 80/80 | pass (79/79) | heuristic | 0.97 | no |
| 04_mon_dates_separate_time | CSV | ok | 80/80 | pass (79/79) | heuristic | 0.97 | no |
| 05_indian_grouping_symbols | CSV | ok | 80/80 | pass (79/79) | heuristic | 0.97 | no |
| 06_junk_header_footer | CSV | ok | 80/80 | pass (80/80) | heuristic | 0.97 | no |
| 07_wrapped_narrations | CSV | ok | 80/80 | pass (79/79) | heuristic | 0.97 | no |
| 08_semicolon_cp1252_decimal_comma | CSV | ok | 80/80 | pass (79/79) | heuristic | 0.97 | no |
| 09_xlsx_merged_spacer | XLSX | ok | 80/80 | pass (79/79) | heuristic | 0.97 | no |
| 10_embedded_reference_patterns | CSV | ok | 80/80 | pass (79/79) | heuristic | 0.97 | no |
| 11_app_style_newest_first | CSV | ok | 80/80 | pass (79/79) | heuristic | 0.97 | no |
| X1_inverted_sign_convention | CSV | ok | 80/80 | pass (79/79) | heuristic+flip | 0.97 | no |
| X2_no_balance_column | CSV | ok | 80/80 | unavailable (0/0) | heuristic | 0.6 | yes |
| X3_no_header_row | CSV | ok | 80/80 | pass (79/79) | heuristic | 0.87 | no |
| X4_tab_separated | TXT | ok | 80/80 | pass (79/79) | heuristic | 0.97 | no |
| 12_text_pdf_page_breaks | PDF | ok | 80/80 | pass (79/79) | heuristic | 0.97 | no |
| 13_text_pdf_password | PDF | ok | 80/80 | pass (79/79) | heuristic | 0.97 | no |

## Input-handling checks

7 of 7 cases gave the expected clear outcome (a specific error code the interface can act on, never a crash).

| Case | Expected | Got | Result |
|---|---|---|---|
| Empty file | empty | empty | ok |
| Old .xls file | xls_unsupported | xls_unsupported | ok |
| Picture of a statement, no consent given | image_unsupported or vision_consent_required | vision_consent_required | ok |
| Text that is not a statement | no_transactions | no_transactions | ok |
| Encrypted PDF, no password | pdf_password_required | pdf_password_required | ok |
| Encrypted PDF, wrong password | pdf_password_incorrect | pdf_password_incorrect | ok |
| Encrypted PDF, right password | ok | ok | ok |

## Failures

None on this run.

## Known limits

- Layouts are invented to imitate common export quirks; they do not claim to match any real bank. Say "tested on N layouts".
- Scanned PDFs and photos of statements are handled by the vision path only when the user consents (see the Day 2 report).
- Old `.xls` files ask the user to re-save as `.xlsx` or `.csv`.
- A narration wrapped in the middle of a word gets a space inserted; references are unaffected, name hints can be.
- Rows are assumed to be in monotonic file order (oldest-first or newest-first).
