# Photo-of-statement test under four conditions

Generated 2026-10-08 by `python -m tests.ingestion.degradation_eval`.

Each condition uses 3 synthetic statement images of 15 rows (images are drawn by our own test code, then damaged). The vision model reads each image; the balance check verifies it. A row counts as correct only when its amounts, balance and 12-digit reference all match the truth, and rows are counted as 0 when the number of rows read is wrong. Small sample, synthetic data, one vision model.

| Condition | What was done | Statements read | Right number of rows | Rows fully correct | Wrong amounts | Wrong references | Balance check passed | Asked user to confirm |
|---|---|---|---|---|---|---|---|---|
| clean | original image, no damage | 3/3 | 3/3 | 45/45 | 0 | 0 | 3/3 | 0/3 |
| recompressed | saved as a small JPEG (quality 35) | 3/3 | 3/3 | 45/45 | 0 | 0 | 3/3 | 0/3 |
| resized | shrunk to 60% of its size | 3/3 | 3/3 | 45/45 | 0 | 0 | 3/3 | 0/3 |
| photographed | tilted 2 degrees, blurred, darker, grainy, JPEG quality 55 | 3/3 | 1/3 | 15/45 | 0 | 0 | 3/3 | 2/3 |

## Failure examples

- **photographed**: read 14 of 15 rows
- **photographed**: read 14 of 15 rows

## Reading these results

- This tests the *photo* path only. Spreadsheet, CSV and text-PDF statements do not use the vision model.
- Real phone photos (glare, folds, a hand in the frame) are harder than these simulated ones.
