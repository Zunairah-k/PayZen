# Alizah — Phase 3 engineering report (PayZen)

1. **Scope:** reply generation, re-check workflow, image-edit hint — Alizah-owned backend only.
2. **New files:** `reply_generator.py`, `rechecker.py`, `edit_hint.py`, `tests/test_phase3.py` (+ two docs). Zero existing files modified.
3. **Contracts:** `models.py` frozen and untouched; `match_claims(claims, rows, meta)` signature unchanged.
4. **Replies:** deterministic, evidence-only text for all six statuses; tones professional/friendly/brief; English now, per-language catalog ready for Hindi/Telugu.
5. **Next steps in replies:** "Can't verify yet" asks for a statement covering the `follow_up_after` time, or an earlier/newer one, or the missing amount/time.
6. **Safety:** no accusatory vocabulary (tested for every status × tone); echoed user text sanitised and length-capped.
7. **Integration of replies:** `attach_replies` returns copies with `suggested_reply` set; matcher stays evidence-only.
8. **Re-check:** `recheck_claims` re-runs unresolved claims through the existing matcher against a newer statement; no rules duplicated or weakened.
9. **Re-check guard:** credits already used by Verified/Likely claims (by reference) are not reusable by re-checked claims.
10. **Edit hint:** weak low/medium/none signal from near-identical image fingerprints with differing payment fields, or editor names in image metadata; capped at 0.70; cannot affect verdicts.
11. **Dependencies:** none new (stdlib; Pillow optional and already used by Phase 1).
12. **Tests:** 120 new cases (replies, re-check, edit hint, matcher-output integration, regression). Authored and run in a sandbox with stand-in models: Phase 1 + 2 + 3 = 436 passed there; **must be re-run on the real repo**.
13. **Known limits:** reply routing keys off Phase 2 reason text; rows without references can't be tracked across statements; hint is heuristic.
14. **Remaining:** API/UI wiring, re-upload flow, fixture-based end-to-end evaluation, deployment.
