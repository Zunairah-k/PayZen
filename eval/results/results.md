# PayZen evaluation (synthetic data)

100 claims, 5 statement layouts + 1 later statement. Claims use oracle extraction. Numbers are exactly as produced by eval/run_eval.py. The data is synthetic.

## Statement ingestion

| statement | rows parsed/expected | credits exact | ref recall | ref precision | coverage | balance chain | parse conf | warnings |
|---|---|---|---|---|---|---|---|---|
| statement_06_later.csv | 5/5 | True | 1.0 | 1.0 | 2026-10-07T16:14:00 to 2026-10-07T20:33:00 | pass: Balance chain holds on all 4 checked rows. | 0.85 | 1 |
| statement_01_standard.csv | 68/68 | True | 1.0 | 1.0 | 2026-10-01T00:00:00 to 2026-10-06T23:59:59 | pass: Balance chain holds on all 67 checked rows. | 0.94 | 2 |
| statement_02_drcr.csv | 68/68 | True | 1.0 | 1.0 | 2026-10-01T00:00:00 to 2026-10-06T23:59:59 | pass: Balance chain holds on all 67 checked rows. | 0.94 | 2 |
| statement_03_signed.csv | 68/68 | True | 1.0 | 1.0 | 2026-10-01T08:29:39 to 2026-10-06T21:16:32 | pass: Balance chain holds on all 67 checked rows. | 0.97 | 0 |
| statement_04_datetime.csv | 68/68 | True | 1.0 | 1.0 | 2026-10-01T08:29:00 to 2026-10-06T21:16:00 | pass: Balance chain holds on all 67 checked rows. | 0.97 | 0 |
| statement_05_indian_junk.csv | 68/68 | True | 1.0 | 1.0 | 2026-10-01T00:00:00 to 2026-10-06T23:59:59 | pass: Balance chain holds on all 67 checked rows. | 0.94 | 2 |

## Verdict accuracy by statement layout

| layout | accuracy | false-Verified | false Not-found | fakes marked Likely |
|---|---|---|---|---|
| statement_01_standard.csv | 0.96 | 0/45 | 0/55 | 0 |
| statement_02_drcr.csv | 0.96 | 0/45 | 0/55 | 0 |
| statement_03_signed.csv | 0.95 | 0/45 | 0/55 | 0 |
| statement_04_datetime.csv | 0.95 | 0/45 | 0/55 | 0 |
| statement_05_indian_junk.csv | 0.96 | 0/45 | 0/55 | 0 |

## Baseline detail (statement_01_standard.csv)

### Confusion matrix (rows = expected, columns = predicted)

| expected \ predicted | Verified | Likely match | Contradicted | Not found | Duplicate | Can't verify yet |
|---|---|---|---|---|---|---|
| Verified | 33 | 0 | 0 | 0 | 0 | 0 |
| Likely match | 0 | 17 | 0 | 0 | 0 | 0 |
| Contradicted | 0 | 0 | 10 | 0 | 0 | 0 |
| Not found | 0 | 0 | 0 | 23 | 0 | 0 |
| Duplicate | 0 | 0 | 4 | 0 | 4 | 0 |
| Can't verify yet | 0 | 0 | 0 | 0 | 0 | 9 |

### Accuracy by category

| category | correct |
|---|---|
| genuine | 50/50 |
| genuine_delayed | 5/5 |
| edited_amount | 10/10 |
| invented_reference | 10/10 |
| duplicate_reference | 0/4 |
| duplicate_image | 4/4 |
| fake_app | 8/8 |
| wrong_payee | 5/5 |
| old_screenshot | 4/4 |

### With vs without a reference in the narration (genuine claims)

| case | correct |
|---|---|
| no reference in narration | 17/17 |
| reference in narration | 33/33 |

### False-Verified claim ids

none

### First 8 mismatches

| claim | category | expected | predicted | reasons |
|---|---|---|---|---|
| claim_076 | duplicate_reference | Duplicate | Contradicted | Reference 948467737826 appears on statement row S00009, so this row is the relevant evidence. / Payer information is incompatible: claim 'Vivaan Nair' vs statement 'Lakshmi Reddy'. |
| claim_077 | duplicate_reference | Duplicate | Contradicted | Reference 614586850142 appears on statement row S00057, so this row is the relevant evidence. / Payer information is incompatible: claim 'Ayesha Rao' vs statement 'Ananya Patel'. |
| claim_078 | duplicate_reference | Duplicate | Contradicted | Reference 517278895798 appears on statement row S00061, so this row is the relevant evidence. / Payer information is incompatible: claim 'Faizan Gupta' vs statement 'Riya Patel'. |
| claim_079 | duplicate_reference | Duplicate | Contradicted | Reference 940164005242 appears on statement row S00068, so this row is the relevant evidence. / Payer information is incompatible: claim 'Nikhil Gupta' vs statement 'Sneha Das'. |

## Re-check on delayed payments

| layout | delayed claims | correct before | correct after re-check |
|---|---|---|---|
| statement_01_standard.csv | 5 | 5 | 5 |
| statement_02_drcr.csv | 5 | 5 | 5 |
| statement_03_signed.csv | 5 | 5 | 5 |
| statement_04_datetime.csv | 5 | 5 | 5 |
| statement_05_indian_junk.csv | 5 | 5 | 5 |