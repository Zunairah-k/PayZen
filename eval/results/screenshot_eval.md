# Screenshot evaluation, four conditions (synthetic data)

27 of 100 claims per condition (a sampled duplicate always brings its original). The real extractor read each screenshot; the real matcher judged the result against `statement_01_standard.csv`. 'Wrong' means a value was read but is not the true value (worse than 'nothing read'). Small sample, synthetic screenshots drawn by our own code, one vision model.

| Condition | Images | Nothing read | Amount right | Reference right | Time right | Wrong amount | Wrong reference | Verdict right | False-Verified (fake marked paid) | Genuine marked Not found |
|---|---|---|---|---|---|---|---|---|---|---|
| clean | 27 | 0 | 27/27 | 27/27 | 27/27 | 0 | 0 | 25/27 | 0/11 | 0/16 |
| recompressed | 27 | 0 | 27/27 | 27/27 | 27/27 | 0 | 0 | 25/27 | 0/11 | 0/16 |
| resized | 27 | 0 | 27/27 | 27/27 | 27/27 | 0 | 0 | 25/27 | 0/11 | 0/16 |
| photographed | 27 | 0 | 27/27 | 27/27 | 27/27 | 0 | 0 | 25/27 | 0/11 | 0/16 |

False-Verified is the most important number: a fake payment marked as paid.
