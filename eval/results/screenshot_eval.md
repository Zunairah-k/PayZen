# Screenshot evaluation, four conditions (synthetic data)

27 of 100 claims per condition (a sampled duplicate always brings its original). The real extractor read each screenshot; the real matcher judged the result against `statement_01_standard.csv`. 'Wrong' means a value was read but is not the true value (worse than 'nothing read'). Small sample, synthetic screenshots drawn by our own code, one vision model.

| Condition | Images | Nothing read | Amount right | Reference right | Time right | Wrong amount | Wrong reference | Verdict right | False-Verified (fake marked paid) | Genuine marked Not found |
|---|---|---|---|---|---|---|---|---|---|---|
| clean | 27 | 0 | 27/27 | 27/27 | 27/27 | 0 | 0 | 25/27 | 0/11 | 0/16 |
| recompressed | 27 | 1 | 26/27 | 26/27 | 26/27 | 0 | 0 | 24/27 | 0/11 | 0/16 |
| resized | 27 | 3 | 24/27 | 24/27 | 24/27 | 0 | 0 | 22/27 | 1/11 | 0/16 |
| photographed | 27 | 6 | 21/27 | 21/27 | 21/27 | 0 | 0 | 20/27 | 0/11 | 0/16 |

False-Verified is the most important number: a fake payment marked as paid.

- resized: false-Verified claim ids: claim_081

Verdicts that did not match ground truth:

- clean: claim_069 expected Not found, got Likely match
- clean: claim_077 expected Duplicate, got Contradicted
- recompressed: claim_001 expected Likely match, got Can't verify yet
- recompressed: claim_069 expected Not found, got Likely match
- recompressed: claim_077 expected Duplicate, got Contradicted
- resized: claim_005 expected Likely match, got Can't verify yet
- resized: claim_039 expected Verified, got Can't verify yet
- resized: claim_069 expected Not found, got Likely match
- resized: claim_077 expected Duplicate, got Contradicted
- resized: claim_081 expected Duplicate, got Verified
- photographed: claim_025 expected Verified, got Can't verify yet
- photographed: claim_069 expected Not found, got Likely match
- photographed: claim_077 expected Duplicate, got Contradicted
- photographed: claim_081 expected Duplicate, got Can't verify yet
- photographed: claim_085 expected Not found, got Can't verify yet
- photographed: claim_089 expected Not found, got Can't verify yet
- photographed: claim_093 expected Not found, got Can't verify yet