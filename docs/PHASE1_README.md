# PayZen — Phase 1: Screenshot Extraction + Normalization (Alizah)

Screenshot bytes -> `Claim`. Nothing else. No matching, no verdicts.

## 1. What was implemented
- `extract_claim(image_bytes, filename) -> Claim` (same signature as the scaffold).
- Pluggable vision-provider interface (`VisionProvider`), a "nothing configured" default, and a clearly-labelled `MockVisionProvider`.
- Deterministic normalizers: reference, amount, currency, timestamp, names, UPI IDs, status, app guess.
- Per-field confidence in `Claim.confidence`.
- Perceptual image hash (dHash) with honest sha256 fallback.
- Short `extraction_notes` explaining limitations.

## 2. Files
```
backend/app/services/extractor.py   <- REPLACES the stub
tests/test_extractor.py             <- new
PHASE1_README.md
requirements-alizah-phase1.txt
```
`models.py`, `ingestor.py`, `matcher.py`, `main.py` are NOT touched.

## 3. How extraction works
1. Reject empty / non-bytes input (`ValueError`).
2. Compute the image hash.
3. Ask the provider for RAW fields (text as seen: `"₹ 1,500.00"`, `"1234 5678 9012"`) plus its own 0..1 confidence per field.
4. Normalize each field. Anything that can't be established becomes `None` with confidence `0.0`.
5. Build `Claim`. A provider crash is contained: you get an all-`None` claim with a note, not an exception.

`extract_claim_detailed()` also returns `partial_date` / `partial_time` (see limits) and provider info.

## 4. Normalization rules (conservative on purpose)
| Field | Accepts | Rejects (-> `None`) |
|---|---|---|
| reference | `123456789012`, `1234 5678 9012`, `1234-5678-9012`, `UPI Ref: 123456789012` | not exactly 12 digits, 2+ different candidates, letters inside digits (no O->0 / l->1 repair), `111111111111`, ints that lost leading zeros |
| amount | `₹300`, `Rs. 300`, `INR 300`, `300/-`, `300.00`, `₹1,00,000`, bare number | `Paid 300 to 98765...` (unmarked number in text), 2+ different amounts, `0`, negatives, bad comma grouping |
| currency | only when evidenced by a marker or provider; conflict -> `None` | never assumed |
| timestamp | many Indian-app formats, 12/24h, day-first numeric dates | invalid times, years outside 2000-2100, several times in one string |
| names | whitespace/zero-width cleanup; ALL-CAPS or all-lower -> Title Case; mixed case kept | no letters |
| UPI ID | lower-cased, spaces removed, `local@handle` shape; masked IDs (`ab****12@oksbi`) kept but flagged | bad shape |
| status | `success` / `failed` / `pending` | unrecognised |
| app guess | PhonePe, Google Pay, Paytm, BHIM, Amazon Pay, CRED | unrecognised |

Timestamps: `Claim.timestamp` is only set for a FULL date+time, as `YYYY-MM-DDTHH:MM:SS`, no timezone invented (an explicit `+05:30`/`IST` is ignored with a note). Date-only or time-only leaves `Claim.timestamp = None`, adds a note, and exposes the partial value via `extract_claim_detailed()`.

## 5. Confidence
- Range 0..1, always present for: reference, amount, currency, timestamp, payer_name, payer_upi_id, payee_name, payee_upi_id, status_shown, app_style_guess.
- Not extracted / rejected -> exactly `0.0`.
- Otherwise = provider confidence (clamped to 0..1; NaN/garbage -> 0.0; none reported -> 0.5) x small penalty (reformatted reference x0.95, amount pulled out of messy text x0.9). Masked UPI IDs are capped at 0.5.
- These numbers are the provider's self-reported certainty, NOT a measured accuracy.

## 6. Image hash
`dhash256:<64 hex>` — grayscale 17x16 resize, 256 difference bits. Survives resizing/recompression. `hamming_distance(a, b)` is included as a helper.
If Pillow is missing or the bytes aren't an image: `sha256:<hex>` (exact bytes only; this is NOT perceptual) and a note says so.
Caution for Phase 2: screenshots from the same app share a template, so a dHash is a weak signal. Treat a small distance as a hint, never as proof.

## 7. Mock vs real provider
- Default provider = `NoProviderConfigured`: extracts nothing (honest empty claim). The old fake "Test Payer / 300 / 123456789012" is gone.
- `MockVisionProvider(fields)` returns fixtures you give it and writes "MOCK provider used" in the notes. With no fixture it reads `{"mock_fields": {...}}` JSON from the uploaded bytes so you can demo by uploading a `.json` file.
- A real provider = subclass `VisionProvider`, implement `extract_fields()` returning `RawExtraction`, then call `set_default_provider(MyProvider())`. No API key or env var is needed for Phase 1.

## 8. Dependencies
Pillow (optional at runtime), pytest (tests). pydantic is already in your repo. Real API/key required: NO.

## 9. Integrating
`extract_claim` keeps its signature, so existing callers keep working — but with no provider they now get an all-`None` claim. To demo the pipeline before a real model exists, call `set_default_provider(MockVisionProvider({...}))` once at startup.
`Claim` is built to fit your `models.py` without editing it (list or str `extraction_notes`, datetime or str `timestamp`, optional-with-default fields). I could not see `models.py`; if construction raises a ValidationError, send me the model.

## 10. Commands (run from the repo root)
PowerShell:
```
git checkout -b alizah/phase1-extraction
Expand-Archive "$HOME\Downloads\alizah_phase1_extraction.zip" -DestinationPath "$HOME\Downloads\" -Force
$src = "$HOME\Downloads\alizah_phase1_extraction"
Copy-Item "$src\backend\app\services\extractor.py" ".\backend\app\services\extractor.py" -Force
New-Item -ItemType Directory -Force .\tests | Out-Null
Copy-Item "$src\tests\test_extractor.py" ".\tests\" -Force
Copy-Item "$src\PHASE1_README.md", "$src\requirements-alizah-phase1.txt" "." -Force
pip install -r requirements-alizah-phase1.txt
python -m pytest tests/test_extractor.py -v
```
macOS/Linux/Git Bash:
```
git checkout -b alizah/phase1-extraction
unzip -o ~/Downloads/alizah_phase1_extraction.zip -d ~/Downloads
cp ~/Downloads/alizah_phase1_extraction/backend/app/services/extractor.py backend/app/services/
mkdir -p tests && cp ~/Downloads/alizah_phase1_extraction/tests/test_extractor.py tests/
cp ~/Downloads/alizah_phase1_extraction/{PHASE1_README.md,requirements-alizah-phase1.txt} .
pip install -r requirements-alizah-phase1.txt
python -m pytest tests/test_extractor.py -v
```
If `tests/` or `app/services` needs `__init__.py` in your repo, pytest still works: the test adds `backend/` to `sys.path` itself.

## 11. Known limitations
- No real OCR/vision yet; quality depends entirely on the future provider.
- Only 12-digit references. Other formats (e.g. PhonePe `T...` IDs) are rejected, not guessed.
- Numeric dates are read day-first; `03/04/2026` is 3 April.
- No timezone handling; times are as shown on the screenshot.
- dHash is weak between same-app screenshots (see 6).
- Confidence is provider self-report plus fixed penalties, not calibrated.
- Name casing: ALL-CAPS names become Title Case ("MCDONALD" -> "Mcdonald").
- Only INR markers are recognised in amount text.

## 12. Intentionally NOT implemented
Matching, fuzzy name matching, one-to-one assignment, duplicate detection (only the hash helper exists), coverage logic, verdicts, replies, re-check, edit detection, statement ingestion, frontend, API wiring, any real vision API.
