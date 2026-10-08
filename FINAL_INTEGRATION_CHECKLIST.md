# PayZen — Final Integration Checklist

Legend: ✅ **Implemented in repo** (service level) · 🔗 **Waiting for team integration** · 🚀 **Final deployment task**. "Implemented" means the code exists and has its own tests; it does not mean it is wired into the API or verified in the deployed app.

| # | Item | Owner | State |
|---|---|---|---|
| 1 | [ ] extractor connected to API (`extract_claim` per uploaded screenshot; vision provider chosen — default is "none configured") | Alizah + API owner | ✅ service · 🔗 wiring |
| 2 | [ ] statement ingestion connected to API (rows + meta passed on) | Zunairah + API owner | ✅ service · 🔗 wiring |
| 3 | [ ] matcher/verdict connected (`match_claims(claims, rows, meta)`) | Alizah + API owner | ✅ service · 🔗 wiring |
| 4 | [ ] replies attached (`attach_replies` before responding) | Alizah + API owner | ✅ service · 🔗 wiring |
| 5 | [ ] re-check connected (re-upload of a newer statement → `recheck_claims`, `merge_rechecked`) | Alizah + Umaima | ✅ service · 🔗 wiring + UI flow |
| 6 | [ ] frontend displays all six statuses | Umaima | 🔗 verify |
| 7 | [ ] reason cards display reasons/evidence | Umaima | 🔗 verify |
| 8 | [ ] confidence displayed | Umaima | 🔗 verify |
| 9 | [ ] field differences displayed (Contradicted) | Umaima | 🔗 verify |
| 10 | [ ] "Can't verify yet" displays follow-up (`follow_up_after` and reply text) | Umaima | 🔗 verify |
| 11 | [ ] uploads handled safely (type/size validation, no persistence, no sensitive logging) | API owner | 🔗 |
| 12 | [ ] frontend/backend environment variables configured (names TO BE CONFIRMED) | Team | 🚀 |
| 13 | [ ] local end-to-end smoke test (synthetic screenshot + synthetic statement → verdicts in UI) | Team | 🔗 (service-level smoke test: `tests/test_integration_smoke.py`) |
| 14 | [ ] deployed backend test (health/route reachable, CORS ok) | Team | 🚀 |
| 15 | [ ] deployed frontend test (talks to deployed backend over HTTPS) | Team | 🚀 |
| 16 | [ ] final regression (`python -m pytest tests -v`) | Team | 🔗 |
| 17 | [ ] README/demo flow verified (synthetic data only) | Team | 🔗 |

Also decide: how the weak edit hint is returned/shown (note only), and the real vision provider and its secret (name TO BE CONFIRMED).
