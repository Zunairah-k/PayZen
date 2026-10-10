# PayZen — Phase 2: Matching / Verification Engine (Alizah)

`match_claims(claims, statement_rows, statement_meta=None, config=None) -> List[Verdict]`

One Verdict per claim, same order as the input. Pure, deterministic, stdlib only. Phase 1 (`extractor.py`), `models.py`, the ingestion pipeline and the frontend are NOT touched.

## 1. What was implemented
Matching ladder, transparent candidate scoring, global one-to-one assignment, duplicate detection, coverage-aware verdicts, contradiction handling, calibrated confidence, evidence-based reasons. `suggested_reply` is left unset (Phase 3).

## 2. Matching ladder
Only rows with a positive `credit` are payment evidence. Debit rows never soft-match.
| Tier | Rule | Status | Confidence |
|---|---|---|---|
| 1 | Claim reference == row reference (field, or a 12-digit token in the narration) AND amount equal AND no conflicting field | Verified | 0.85–0.97 |
| 4 | Reference is on a statement row but a field conflicts (amount, payer name, time >24h, screenshot says "failed", or row is a debit) | Contradicted | 0.60–0.95 |
| 2 | No reference hit; equal amount + time within window + payer identity (name similarity >= 0.80, or payer UPI ID in the narration) | Likely match | 0.60–0.89 |
| 3 | No reference hit; equal amount + time within window, identity missing/weak | Likely match (low) | 0.35–0.60 |
| 5 | No candidate, claim safely inside coverage | Not found | ~0.55–0.75 |
| – | Coverage can't support a conclusion | Can't verify yet | 0.0 |
Tiers 2/3 can never produce Verified. A reference match is never searched around: if the reference is on the statement but conflicts, the claim is Contradicted. A soft candidate whose row carries a *different* reference is rejected.

## 3. Candidate scoring (used to rank competing claim/row pairs)
`points (0–100) = 30*time_proximity + 40*name_similarity + 20*(payer UPI ID in narration) + 10*extraction_confidence`. Missing evidence scores 0. Assignment weight = tier bonus (T1 > T2 > T3) + points, so tier always dominates.
Name similarity: order-insensitive token match (exact 1.0, initial 0.6, typo <= 0.9), scaled by sqrt(token-count ratio); one-word names are capped at 0.75, so "Ali" vs "Ali Khan" is never "similar". Statement name hints can support OR contradict (similarity < 0.30 excludes a candidate / contradicts a reference match); narration text can only support.

## 4. Time window
Default `time_window_minutes=30` (screenshot clock vs bank posting time; UPI credits post within minutes). Same-reference matches tolerate up to 24h before being Contradicted (`reference_time_conflict_hours`). Statement rows with date only (00:00:00) can't be time-compared: they cap at Tier 3 (same date required). All thresholds live in `MatchConfig`. Missing timestamps are never invented.

## 5. One-to-one assignment
Candidate edges are grouped into connected components; each is solved as a maximum-weight bipartite assignment (Hungarian algorithm), so the *global* best pairing wins, not first-come-first-served. A better pairing for one claim can free a row for another. **Tie-breaking** (exact weight ties): lower `claim_id` (then input position) wins, then lower `row_id`. Input order does not change results. Losing claims get "Not found" (credit already assigned) or "Duplicate" (see below), never Verified.

## 6. Duplicate detection
Claims are linked only by: same reference; byte-identical file (`sha256:` hash); or identical/near (<= 6 of 256 bits) `dhash256:` hash **plus** corroboration (same reference, or same amount within 60 s). Perceptual hash alone is never enough (same-app screenshots look alike) and an uncorroborated match only adds a note. In each linked group one claim keeps its verdict (assigned/Verified first, then claim_id order); the others become Duplicate with reasons. Same reference + conflicting payer names that the statement name can't resolve: nobody is Verified, all are Duplicate. A claim that loses a credit to a claim with the same payer name, amount and time is Duplicate; with different payers it is just "Not found". Contradicted claims keep their verdict.

## 7. Coverage
No candidate → inside coverage by more than one window from both ends = Not found. After `coverage_end`, within one window of it, before `coverage_start`, or near it = Can't verify yet (`follow_up_after` = claim time + 24h for the end side; reason asks for a newer/earlier statement). Missing claim timestamp, missing/inverted coverage, empty statement, or `parse_confidence < 0.5` = Can't verify yet. A date-only `coverage_end` includes that whole day. Matches found by reference never depend on coverage.

## 8. Contradictions
`field_differences` holds exact claim-vs-statement text, only for fields where both sides have a value: `amount: "claim=500.0, statement=300.0"`, `payer_name`, `timestamp`, `status_shown`, `direction`.

## 9. Confidence
Tier 1: 0.97, minus 0.07 if time is outside the window, 0.04 for partial name match, 0.02 narration-only reference, 0.03 if screenshot says pending, small penalty for low extraction confidence; floor 0.85. Tier 2: 0.65 + up to 0.15 (name) + 0.04 (time) + 0.05 (UPI), cap 0.89. Tier 3: 0.40 + up to 0.14 (time) + 0.04 (weak name), cap 0.60. Ambiguity (several near-equal rows) −0.08; low extraction confidence −0.10. These are rule-based scores, not measured probabilities.

## 10. Tests
`tests/test_matcher.py`: 156 test cases (behaviour-level; only the public API and `MatchConfig`). Covers every item on your list: ladder, wrong amount, missing timestamp/reference/name/statement reference, debit rows, tie-breaking, global assignment, duplicates (reference, sha256, dHash, conflicting names), coverage boundaries, empty inputs, duck-typed/malformed inputs, confidence range, field_differences, reasons, no accusatory words, determinism and input-order independence.

## 11. Integration
Copy `matcher.py` over the stub. Call it from the API layer with the lists you already have:
`verdicts = match_claims(claims, statement_rows, statement_meta)`.
The old stub's function name is unknown to me — adapt the call site in `main.py` (or add a one-line wrapper). Nothing else needs to change.

## 12. Example
```python
from app.services.matcher import match_claims, MatchConfig
verdicts = match_claims(claims, rows, meta, MatchConfig(time_window_minutes=45))
for v in verdicts:
    print(v.claim_id, v.status, v.tier, v.matched_row_id, v.confidence, v.reasons)
```

## 13. Limitations
- Built without seeing your real `models.py` / ingestion output. Verdicts are constructed defensively (works with `tier` optional or int, str/datetime `follow_up_after`), but if `Verdict(...)` raises a ValidationError, send me the model.
- Timezones are dropped (wall-clock compared). Day-first assumptions are Phase 1's.
- `payee_*` fields are not compared (statement rows have no payee info).
- Name matching is token-based; transliteration variants (e.g. Hindi/Urdu spellings) won't match.
- Coverage is taken only from `StatementMeta`; it is not inferred from rows.
- Hungarian solve is O(n^3) per component; fine for hundreds of same-amount claims.

## 14. Left for Phase 3
Reply generation (`suggested_reply`), re-check flow when a newer statement arrives, low-weight screenshot-edit hint, API/UI wiring of `follow_up_after`, evaluation on the team's ground-truth fixtures.
