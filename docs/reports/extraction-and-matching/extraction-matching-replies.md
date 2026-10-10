# Extraction, matching and replies (Alizah)

How a screenshot becomes a verdict and a reply. This one document replaces the three phase READMEs. Code: `backend/app/services/` (`extractor.py`, `vision_gemini.py`, `matcher.py`, `reply_generator.py`, `rechecker.py`, `edit_hint.py`, `intake_handler.py`). Tests: `tests/test_extractor.py`, `test_matcher.py`, `test_phase3.py`, `test_screenshot_handler.py`, `test_vision_gemini.py`, `test_integration_smoke.py`.

```text
Screenshot bytes -> extractor -> Claim -> matcher (+ statement rows and meta) -> Verdict -> reply
                                                        newer statement -> re-check -> Verdict
```

---

## Part 1. Screenshot extraction and normalization

`extract_claim(image_bytes, filename) -> Claim`. Nothing else: no matching, no verdicts.

**How it works**
1. Reject empty or non-bytes input (`ValueError`).
2. Compute the image hash.
3. Ask the vision provider for the raw text as printed (for example "₹ 1,500.00", "1234 5678 9012") plus its own 0..1 confidence per field. The deployed provider is Gemini (`vision_gemini.py`), registered once at startup.
4. Normalize each field. Anything that cannot be established becomes `None` with confidence 0.0.
5. Build the `Claim`. A provider crash is contained: you get an all-empty claim with a note, not an exception.

`extract_claim_detailed()` also returns the partial date or time when only one was read.

**Normalization rules (conservative on purpose)**

| Field | Accepts | Rejects (becomes None) |
|---|---|---|
| reference | `123456789012`, `1234 5678 9012`, `1234-5678-9012`, `UPI Ref: 123456789012` | not exactly 12 digits, two different candidates, letters inside digits (no O to 0 repair), `111111111111` |
| amount | `₹300`, `Rs. 300`, `INR 300`, `300/-`, `₹1,00,000`, a bare number | an unmarked number inside text, two different amounts, 0, negatives, bad comma grouping |
| currency | only when a marker or the provider evidences it | never assumed |
| timestamp | many Indian-app formats, 12 or 24 hour, day-first numeric dates | invalid times, years outside 2000 to 2100, several times in one string |
| names | whitespace and zero-width cleanup; ALL-CAPS becomes Title Case | no letters |
| UPI ID | lower-cased `local@handle`; masked IDs kept but flagged | bad shape |
| status, app guess | success / failed / pending; PhonePe, Google Pay, Paytm, BHIM, Amazon Pay, CRED | unrecognised |

`Claim.timestamp` is set only for a full date and time (`YYYY-MM-DDTHH:MM:SS`, no timezone invented).

**Confidence.** Always present for every field; exactly 0.0 when not extracted. Otherwise the provider's self-reported certainty (clamped to 0..1; none reported becomes 0.5) times a small penalty (reformatted reference x0.95, amount pulled from messy text x0.9). Masked UPI IDs are capped at 0.5. These are not measured accuracies.

**Image hash.** `dhash256:<64 hex>` (grayscale 17x16 resize, 256 difference bits) survives resizing and recompression. If Pillow is missing or the bytes are not an image: `sha256:<hex>` (exact bytes only). Screenshots from the same app share a template, so a small distance is a hint, never proof.

**Limits.** Only 12-digit references (other formats are rejected, not guessed); numeric dates are read day-first; no timezone handling; confidence is not calibrated; only INR markers are recognised.

---

## Part 2. Matching and verification

`match_claims(claims, statement_rows, statement_meta=None, config=None) -> List[Verdict]`: one verdict per claim, same order as the input. Pure, deterministic, standard library only.

**Matching ladder.** Only rows with a positive credit are payment evidence. Debit rows never soft-match.

| Tier | Rule | Status | Confidence |
|---|---|---|---|
| 1 | High-confidence reference equal (field, or a 12-digit token in the narration), amount equal, no conflicting field | Verified | 0.85 to 0.97 |
| 4 | Reference is on a row but a field conflicts (amount, payer name, time over 24 h, screenshot says failed, row is a debit) | Contradicted | 0.60 to 0.95 |
| 2 | No reference hit; equal amount, time within the window, payer identity (name similarity 0.80 or more, or payer UPI ID in the narration) | Likely match | 0.60 to 0.89 |
| 3 | No reference hit; equal amount and time, identity weak or missing | Likely match (low) | 0.35 to 0.60 |
| 5 | No candidate, claim safely inside coverage | Not found | about 0.55 to 0.75 |
| none | Coverage cannot support a conclusion | Can't verify yet | 0.0 |

Tiers 2 and 3 can never produce Verified. A reference match is never searched around: if the reference is on the statement but conflicts, the claim is Contradicted.

**Candidate scoring** (ranks competing claim and row pairs): points out of 100 = 30 x time proximity + 40 x name similarity + 20 x (payer UPI ID in narration) + 10 x extraction confidence. Name similarity is an order-insensitive token match (exact 1.0, initial 0.6, typo up to 0.9); one-word names are capped at 0.75, so "Ali" versus "Ali Khan" is never similar. A statement name hint can support or contradict a match; narration text can only support.

**Time window.** Default 30 minutes. A same-reference match tolerates up to 24 hours before it is Contradicted. A date-only row (00:00:00) cannot be time-compared, so it caps at Tier 3. All thresholds live in `MatchConfig`. Missing timestamps are never invented.

**One credit, one claim.** Candidate edges are grouped into connected components and each is solved as a maximum-weight bipartite assignment (Hungarian algorithm), so the globally best pairing wins and input order does not change results. Exact ties go to the lower `claim_id`, then the lower `row_id`. Losing claims become Not found or Duplicate, never Verified.

**Duplicates.** Claims are linked only by the same reference, a byte-identical file, or an identical or near (6 of 256 bits or fewer) fingerprint plus corroboration (same reference, or same amount within 60 seconds). A fingerprint alone adds only a note. In each group one claim keeps its verdict and the others become Duplicate. Contradicted claims keep their verdict.

**Coverage.** More than one window inside both ends: Not found. After the end, within one window of it, or before the start: Can't verify yet (`follow_up_after` is the claim time plus 24 hours on the end side). Missing claim time, missing or inverted coverage, an empty statement, or parse confidence under 0.5 also gives Can't verify yet. A date-only `coverage_end` includes that whole day. A match by reference never depends on coverage.

**Contradictions.** `field_differences` holds exact claim-versus-statement text, only where both sides have a value (amount, payer name, timestamp, status shown, direction).

**Confidence formula.** Tier 1: 0.97, minus 0.07 if time is outside the window, 0.04 for a partial name match, 0.02 for a narration-only reference, 0.03 if the screenshot says pending, and a small penalty for low extraction confidence; floor 0.85. Tier 2: 0.65 plus up to 0.15 (name), 0.04 (time) and 0.05 (UPI), cap 0.89. Tier 3: 0.40 plus up to 0.14 (time) and 0.04 (weak name), cap 0.60. Ambiguity (several near-equal rows) subtracts 0.08; low extraction confidence subtracts 0.10. These are rule-based scores, not probabilities.

**Limits.** Timezones are dropped; payee fields are not compared; name matching is token-based, so transliteration variants will not match; coverage comes only from `StatementMeta`.

---

## Part 3. Replies, re-check and edit hint

**Reply generator.** `generate_reply(verdict, tone="professional", language="en")` and `attach_replies(verdicts)`. It reads only verdict fields and invents nothing.
- One headline sentence per status, then the evidence (matched row, "Evidence strength: high, medium or low"), a caution for Tier 3, exact submitted-versus-statement values for Contradicted, and a next step.
- For Can't verify yet: if `follow_up_after` is set, it asks for a statement covering that time; otherwise the next step is chosen from the reason (earlier statement, missing amount, missing time, non-INR, low parse confidence, empty statement).
- Tones: professional (default), friendly (adds a thank-you line), brief (headline only). An unknown tone or language raises `ValueError`.
- English only here. The Hindi and Telugu payer messages are written in the interface (`frontend/src/replies.ts`).
- `attach_replies` returns copies with `suggested_reply` set.

**Re-check.** `recheck_claims`, `merge_rechecked`, `recheck_changes`. It reuses `match_claims`, so no rule is duplicated or weakened. Only claims that were Can't verify yet (or had no previous verdict) are re-run. Rows whose reference belongs to an already Verified or Likely claim are removed from the pool, so an overlapping statement cannot verify a second claim with the same credit.

**Edit hint.** `compute_edit_hint(claim, peers=None, image_bytes=None)` returns `{"signal": none|low|medium, "reason", "confidence"}`.
- Near-identical image plus the same reference but different amount, payer or time: medium (0.55). Differing amount or reference only: low (0.25).
- A known editor named in the image metadata: medium (0.50).
- Two agreeing signals add 0.05; confidence is capped at 0.70; no evidence gives none and 0.0.
- It is a weak note, never a status, and has no path into a verdict. It is not forensics: same-app screenshots look alike and metadata is easily stripped.

**Safety.** Text echoed into replies (names, field values) has control and bidirectional characters removed, whitespace collapsed, and is capped at 80 characters. Accusatory words are never generated (tested for every status and tone). Output is deterministic everywhere.

**Tests.** `test_extractor.py`, `test_matcher.py` (156 cases covering the ladder, wrong amount, missing fields, debit rows, tie-breaking, global assignment, duplicates, coverage boundaries, determinism, input-order independence), `test_phase3.py` (120 cases), `test_screenshot_handler.py`, `test_integration_smoke.py` (13 cases). Run `python -m pytest tests -q` for the current total.