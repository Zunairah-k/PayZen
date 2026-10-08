# PayZen — Phase 3: Replies, Re-check, Edit Hint (Alizah)

Everything here sits ON TOP of the Phase 1 extractor and Phase 2 matcher. `match_claims(claims, rows, meta)`, `models.py`, ingestion and the frontend are untouched. New code is standard library only (Pillow is used optionally, as already required by Phase 1).

## What Phase 3 implements
1. `reply_generator.py` — `generate_reply(verdict, tone="professional", language="en")`, `attach_replies(verdicts, ...)`
2. `rechecker.py` — `recheck_claims(claims, rows, meta, previous_verdicts=None, ...)`, `merge_rechecked`, `recheck_changes`
3. `edit_hint.py` — `compute_edit_hint(claim, peers=None, image_bytes=None)`, `edit_hints_for_claims`

## Files (all NEW; nothing existing is modified)
| File | Copy to |
|---|---|
| `backend/app/services/reply_generator.py` | same path in the repo |
| `backend/app/services/rechecker.py` | same path |
| `backend/app/services/edit_hint.py` | same path |
| `tests/test_phase3.py` | `tests/` |
| `PHASE3_README.md`, `ALIZAH_PHASE3_REPORT.md` | repo root (or `docs/`) |

## Reply generator
- Reads only Verdict fields (status, tier, matched_row_id, confidence, reasons, field_differences, follow_up_after). Nothing invented; no clock, locale or randomness.
- One headline sentence per status (the wording you specified), then evidence: matched row + "Evidence strength: high/medium/low" (>=0.85 / >=0.60 / else), tier-specific caution for Tier 3, exact submitted-vs-statement values for Contradicted, a next step (recheck UPI/bank app, share transaction details, ...).
- "Can't verify yet": if `follow_up_after` is set → "Please provide a statement that covers at least 08 Nov 2026 10:31." Otherwise the next step is chosen from the Phase 2 reason text (earlier statement, missing amount, missing time, non-INR, low parse confidence, empty statement, unknown coverage), default "Please provide a newer statement." **These keys depend on Phase 2 wording; the tests run against real matcher output so a wording change will fail loudly.**
- Tones: `professional` (default), `friendly` (+ thank-you line), `brief` (headline only). Unknown tone/language → `ValueError` (no silent fallback to the wrong language).
- Multilingual-ready: all fragments live in `_CATALOGS["en"]`; add `"hi"`/`"te"` catalogs with the same keys.
- `attach_replies` returns COPIES with `suggested_reply` set; other fields identical; existing replies kept unless `overwrite=True`. The matcher still leaves `suggested_reply` empty — call `attach_replies` in the API layer.

## Re-check
- Reuses `match_claims` — no matching logic duplicated, so no rule is weakened.
- With `previous_verdicts`, only claims that were "Can't verify yet" (or have no previous verdict) are re-run (`recheck_statuses` can add "Not found"); output follows `claims` order. Without it, every given claim is re-run.
- Rows whose 12-digit reference belongs to an already Verified/Likely claim are removed from the pool, and a re-checked claim sharing that reference gets an explanatory reason — so an overlapping statement can't verify a second claim with the same credit.
- Replies are attached by default (`with_replies=False` to skip). `merge_rechecked(previous, new)` swaps results in by claim_id; `recheck_changes` gives before/after for the UI.

## Image-edit hint
Returns `{"signal": "none"|"low"|"medium", "reason": str, "confidence": 0..1}`. A pure function: it cannot create or change a Verdict.
- Peer signal (Phase 1 dHash, <= 6 bits apart): near-identical image + same reference but different amount/payer/time → medium (0.55); differing amount or reference only → low (0.25). Same fields everywhere = duplicate evidence (matcher's job), not an edit hint.
- Metadata signal (optional, Pillow): Software tag naming a known editor → medium (0.50).
- Two agreeing signals add 0.05; confidence is capped at 0.70. No evidence → `none` / 0.0, never invented.
- Not forensics: same-app screenshots look alike and metadata is easily stripped; the reason text says so. Do not show it as a verdict.

## Security / design decisions
Text echoed into replies (names, field values) is stripped of control/bidi characters, whitespace-collapsed and capped at 80 chars, so user-controlled screenshot text cannot inject newlines or instructions. Accusatory words are never generated (tested across all statuses and tones). The hint never feeds the verdict. Deterministic output everywhere.

## Run the tests
```
python -m pytest tests/test_phase3.py -v      # 120 cases
python -m pytest tests -v                     # whole repo
```

## Limitations
- Built without your real `models.py`; copies use `model_copy`/`copy(update=)` (pydantic v2/v1) and do not re-validate.
- Rows without a reference can't be tracked across statements in a re-check.
- Duplicate checks in a re-check only cover the re-checked claims (+ the reference rule above).
- Reply keys rely on Phase 2 reason wording; English only; reply strings are not yet wired into the API/UI.
- Edit hint is a heuristic, easily false-positive for same-app screenshots.

## Remaining for final integration
Call `attach_replies` (or `recheck_claims`) from `main.py`; add an endpoint/button for re-uploading a newer statement; show `follow_up_after` and the edit hint (as a note, not a status) in the UI; run the team ground-truth fixtures end to end; deployment.
