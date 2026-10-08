# Ablation: language model off versus on

Generated 2026-10-08 by `python -m tests.ingestion.ablation`.

**What is compared.** OFF: columns are identified from header words and cell contents, and the balance check picks the mapping that adds up. ON: the model is also asked (it sees only column names and masked sample rows) and the balance check still decides which mapping is kept.

## Summary (copy these two lines)

```
MODEL OFF: 17/17 layouts match ground truth | balance check passed on 16/17 (1 has no balance column) | asks the user to confirm on 1 | mean confidence 0.94
MODEL ON : 17/17 layouts match ground truth | balance check passed on 16/17 (1 has no balance column) | asks the user to confirm on 1 | mean confidence 0.94 | model answered on 17/17, agreed with the deterministic mapper on 16/17, its mapping was the one kept on 2
```

## Standard layouts

| Layout | Type | OFF result | OFF mapping | ON result | ON mapping | Model agreed |
|---|---|---|---|---|---|---|
| 01_standard | CSV | ok | heuristic | ok | heuristic | yes |
| 02_amount_drcr_suffix | CSV | ok | heuristic | ok | heuristic | yes |
| 03_signed_amount | CSV | ok | heuristic | ok | heuristic | yes |
| 04_mon_dates_separate_time | CSV | ok | heuristic | ok | heuristic | yes |
| 05_indian_grouping_symbols | CSV | ok | heuristic | ok | heuristic | yes |
| 06_junk_header_footer | CSV | ok | heuristic | ok | heuristic | yes |
| 07_wrapped_narrations | CSV | ok | heuristic | ok | heuristic | yes |
| 08_semicolon_cp1252_decimal_comma | CSV | ok | heuristic | ok | heuristic | yes |
| 09_xlsx_merged_spacer | XLSX | ok | heuristic | ok | llm | yes |
| 10_embedded_reference_patterns | CSV | ok | heuristic | ok | heuristic | yes |
| 11_app_style_newest_first | CSV | ok | heuristic | ok | llm | yes |
| X1_inverted_sign_convention | CSV | ok | heuristic+flip | ok | heuristic+flip | yes |
| X2_no_balance_column | CSV | ok | heuristic | ok | heuristic | yes |
| X3_no_header_row | CSV | ok | heuristic | ok | heuristic | no |
| X4_tab_separated | TXT | ok | heuristic | ok | heuristic | yes |
| 12_text_pdf_page_breaks | PDF | ok | heuristic | ok | heuristic | yes |
| 13_text_pdf_password | PDF | ok | heuristic | ok | heuristic | yes |

## Stress set: unfamiliar headers (not part of the standard layouts)

```
MODEL OFF: 2/2 layouts match ground truth | balance check passed on 2/2 (0 has no balance column) | asks the user to confirm on 0 | mean confidence 0.97
MODEL ON : 2/2 layouts match ground truth | balance check passed on 2/2 (0 has no balance column) | asks the user to confirm on 0 | mean confidence 0.97 | model answered on 2/2, agreed with the deterministic mapper on 1/2, its mapping was the one kept on 0
```

| Layout | Type | OFF result | OFF mapping | ON result | ON mapping | Model agreed |
|---|---|---|---|---|---|---|
| S1_transliterated_headers | CSV | ok | heuristic | ok | heuristic | yes |
| S2_unfamiliar_headers_credit_first | CSV | ok | heuristic+flip | ok | heuristic+flip | no |

## How to read this

Accuracy is the same with the model off and on. That is the honest finding: header words, cell contents and the arithmetic check already identify these layouts, so the model is a safety net for layouts we have not seen, not the source of the accuracy we report.

Layouts are invented to imitate common export quirks. Say "tested on N layouts"; do not claim every bank.
