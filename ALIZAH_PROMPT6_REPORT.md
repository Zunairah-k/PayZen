# Alizah — Prompt 6 report: Agentboxd screenshot handler

## 0. Read this first (what I could and could not inspect)
Only Zunairah's **integration guide** was available to me in this task. The files `backend/app/intake/*`, `main.py`, `models.py` and the existing `tests/intake/*` were **not provided**, so I did **not** inspect them. Everything I know about the intake service comes from the guide:
- registration: `get_service().register_screenshot_handler(fn)`, "once at startup (or lazily on the first poll)";
- handler signature: `fn(image_bytes, filename, meta)` returning "a small JSON-friendly summary";
- stored outcome: `{ok: true, result: <your summary>}`; on failure `{ok: false, error_code: "handler_error"}`; before registration `{ok: null, note, bytes}`.

I therefore wrote the handler defensively against that contract only and did not guess any other intake API. Anything below marked **VERIFY** needs a 1-minute check against the real code.

## 1. Files changed and why
| File | Status | Why |
|---|---|---|
| `backend/app/services/intake_handler.py` | **new** | The handler, idempotent registration, and a small bounded in-memory list of e-mailed claims |
| `tests/test_screenshot_handler.py` | **new** | 33 offline tests (32 run + 1 environment-dependent) |
| `ALIZAH_PROMPT6_REPORT.md` | **new** | This report |
| `OPTIONAL_matcher_reference_gate/` | **optional, NOT applied** | Proposed fix for the matcher mismatch in section 8 (3 patches + 1 test file) |

No existing file is modified by the main change. `extractor.py`, `matcher.py`, `models.py`, `main.py`, `backend/app/intake/`, `backend/app/ingestion/` and the frontend are untouched.

## 2. How registration works
`register_screenshot_handler(service=None)`:
- uses the service you pass, or resolves it lazily via `<package root>.intake.router.get_service()` (the package root is derived from this module's own package, so it works under both `app.` and `backend.app.` layouts and never creates a second copy of the modules);
- registers `read_screenshot` **at most once per service object** (a second call returns `False` and does not call the service again);
- makes no network call, does not run the extractor, and never raises (a missing intake package or a failing registration returns `False` and logs only the exception type);
- has no import-time side effects, so there is no circular-import risk (`intake` is imported lazily, only when called).
`ensure_registered()` is the lazy variant for a first poll.

## 3. How the existing extractor is reused
`read_screenshot` calls `extract_claim_detailed(image_bytes, filename)` from `extractor.py` — the same function the manual-upload path uses — with whatever provider is set via `set_default_provider`. There is no second extraction implementation. With no provider configured the extractor returns an honest empty claim and the summary says `extracted: false`.

## 4. Return format
The handler **never raises** and returns a JSON-serializable dict, which the intake service stores as `{"ok": true, "result": <this dict>}` (per the guide). Success:
```json
{"extracted": true, "claims": 1, "claim_id": "claim_ab12…", "source_file": "proof.png", "image_hash": "dhash256:…",
 "payer_name": "…", "payer_upi_id": null, "payee_name": null, "payee_upi_id": null, "amount": 500.0, "currency": "INR",
 "timestamp": "2026-10-07T10:31:00", "reference": "123456789012", "app_style_guess": null, "status_shown": null,
 "confidence": {"reference": 0.95, "amount": 0.95, "…": 0.0}, "notes": ["…"], "provider": "none-configured|mock|…",
 "mock_provider": false, "verification": "not_verified",
 "verification_note": "A claim was extracted from the screenshot. It has NOT been verified; …"}
```
`claims` is kept for compatibility with the guide's placeholder (`{"claims": 1}`); it is `0` when nothing was extracted. Optional `partial_date` / `partial_time` appear when only one half of a timestamp was read.
Failure (contained, fixed text, no exception message): `{"extracted": false, "claims": 0, "error_code": "empty_image|invalid_input|image_too_large|extraction_failed", "message": "<generic>", "verification": "not_verified", …}`.
**Design choice (VERIFY):** failures are returned *inside* a normal `result` (so the intake record shows `ok: true` with `result.extracted: false`). If you would rather have the service mark them `ok: false, handler_error`, change `_error(...)` returns to `raise` — but only if the service catches handler exceptions (I could not confirm that).

## 5. Security behaviour preserved
- Zunairah's policy (held/quarantined mail, no attachment download) is not touched. The handler only receives bytes the service chose to pass; it cannot fetch anything and imports no network or intake-policy code (tested via the module's imports).
- Filename, `meta` and everything else from the e-mail are untrusted: the filename is sanitized (control/bidi characters stripped, length-capped, path removed by the extractor); `meta` is read only for a `message_id` storage key and tolerated in any shape; no e-mail text is ever interpreted as instructions.
- Extraction is **never reported as verification** (`verification: "not_verified"`).
- Logging: only the exception **type** is logged — no bytes, names, amounts, references or exception text (tested with a fake exception containing a secret).
- Attachment size guard: > 10 MB is refused before decoding. No keys, `.env` files or new dependencies.
- **Not verified by me:** that quarantined/held mail is never passed to the handler. That is enforced by the service and covered by Zunairah's tests — run `python -m pytest tests/intake -q`.

## 6. Tests and results
`tests/test_screenshot_handler.py` (offline: fake intake service, mock provider, network disabled in tests): registration once / per-service / lazy / missing package / failing registration / no network; exact bytes + filename reach the extractor; JSON-serializable summary; extraction never reported as verification; empty/oversize/invalid input; extractor crash contained and not logged; one failure doesn't affect the next; hostile filename and any `meta` shape; bounded claim store; the stored claim is verified only by the real matcher with a statement; import hygiene.

**Results from MY environment** (scratch repo with *stand-in* models and **no** `backend/app/intake/` package): handler tests **32 passed, 1 skipped** (the skipped test checks the real service exposes `register_screenshot_handler` and only runs where the intake package imports). Together with my earlier suites the scratch run was **481 passed, 1 skipped**. This is **not** a result for your repository; run the commands in section 10.

## 7. Integration still required (Umaima / main.py)
Add once, after `app.include_router(intake_router)`:
```python
from .intake.router import get_service
from .services.intake_handler import register_screenshot_handler
register_screenshot_handler(get_service())     # idempotent; safe to call again
```
Passing the service explicitly (imported the same way as the router) avoids picking up a second copy of `get_service` if the intake module imports itself as `backend.app…`. A FastAPI startup/lifespan hook is equally fine. Optionally, to verify e-mailed screenshots against a statement result: `get_email_claims(message_id)` → `match_claims(claims, rows, meta)` (rows/meta from `to_shared(get_service().get_statement_result(...))`). That wiring is not done here.

## 8. Matcher contract mismatch discovered (reported, NOT silently changed)
Required: *"Only `reference_confidence == "high"` may automatically produce Verified; medium/low/unknown/uncertain must never."*
Found in the current matcher: **not enforced.** An exact reference + equal amount verifies regardless of the extractor's reference confidence; low confidence only lowers the verdict's `confidence` (floor 0.85). Also, `Claim.confidence` is a dict of floats (key `reference`), so "high" has to be defined numerically.
Other listed rules are already satisfied: ISO-string coverage times; `coverage_end` as last covered moment (date-only end = whole day; after/near end → *Can't verify yet*); amounts compared to the paisa (equivalent to `round(x, 2)`); weak amount/time/name evidence → cautious *Likely match*.

**Proposed fix (optional folder, not applied):** high = `confidence["reference"] >= 0.85` (or the string "high"); medium ≥ 0.50; otherwise low; missing/invalid = unknown. A Tier-1 match whose reference is not *high* is reported as **Likely match (tier 1 kept as the evidence rung), confidence 0.60–0.80**, with the reason "only a high-confidence reference can verify automatically", and it still consumes the credit. Contradicted, Duplicate and Tiers 2/3 are unchanged. Thresholds are in `MatchConfig` (`reference_high_confidence`, `reference_medium_confidence`).
Impact you must check: any test/demo claim **without** a reference confidence becomes *Likely match*. My own tests needed a one-line builder change (`confidence={"reference": 0.95}`) and one rewritten test. Teammates' fixtures/synthetic demo claims may need the same.
Sandbox regression for the patch: clean baseline 481 passed / 1 skipped → after applying the 3 patches + the new gate tests (30) **512 passed / 1 skipped**. Not run on your repo.

## 9. Known limitations
- Intake service code and tests were not inspected (section 0); return-format handling beyond the guide is unverified.
- `get_email_claims` is in-memory and bounded (200), resets on restart (like intake records) and holds payer details — clear it after use.
- Only image attachments the service classifies as "screenshot" reach the handler; no PDF screenshots.
- Output depends on the configured vision provider; none is configured by default, so e-mailed screenshots return `extracted: false` until one is set.
- Two package roots (`app.` vs `backend.app.`) hold separate module copies; always register the same service object the router uses.
- Replies are not generated here.

## 10. Local integration guide
**Extract** `alizah_prompt6_agentboxd_handler.zip`; copy:
| From ZIP | To repo |
|---|---|
| `backend/app/services/intake_handler.py` | `backend/app/services/intake_handler.py` (new) |
| `tests/test_screenshot_handler.py` | `tests/test_screenshot_handler.py` (new) |
| `ALIZAH_PROMPT6_REPORT.md` | repo root |
Back up: nothing is replaced. (Only if you apply the optional patch: `backend/app/services/matcher.py`, `tests/test_matcher.py`, `tests/test_phase3.py` — git is enough.)

```powershell
git checkout -b alizah/prompt6-agentboxd-handler
Expand-Archive "$HOME\Downloads\alizah_prompt6_agentboxd_handler.zip" -DestinationPath "$HOME\Downloads\" -Force
$src = "$HOME\Downloads\alizah_prompt6_agentboxd_handler"
Copy-Item "$src\backend\app\services\intake_handler.py" ".\backend\app\services\" -Force
Copy-Item "$src\tests\test_screenshot_handler.py" ".\tests\" -Force
Copy-Item "$src\ALIZAH_PROMPT6_REPORT.md" "." -Force
python -m pytest tests/test_screenshot_handler.py -v
python -m pytest tests/intake -q
python -m pytest tests/test_matcher.py -v
python -m pytest tests -q
```
Then add the 3 `main.py` lines from section 7 (manual) and run the app: `register_screenshot_handler(get_service())` should return `True` the first time.

**Optional matcher gate** (only after reading section 8):
```powershell
$o = "$src\OPTIONAL_matcher_reference_gate"
git apply --check "$o\01_matcher_reference_gate.patch" "$o\02_test_matcher_builder.patch" "$o\03_test_phase3_builder.patch"
git apply "$o\01_matcher_reference_gate.patch" "$o\02_test_matcher_builder.patch" "$o\03_test_phase3_builder.patch"
Copy-Item "$o\test_matcher_reference_gate.py" ".\tests\" -Force
python -m pytest tests -q          # inspect any NEW failures from other fixtures
```
If `git apply --check` fails, your files differ from mine — stop and send me the files. Roll back: `git checkout -- backend/app/services/matcher.py tests/test_matcher.py tests/test_phase3.py` and delete `tests/test_matcher_reference_gate.py`.
