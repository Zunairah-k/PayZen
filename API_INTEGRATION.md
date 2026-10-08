# PayZen — API / Integration Contract

Scope: the contract between the Alizah-owned services (extraction, matching, replies, re-check, edit hint) and whatever API layer calls them.

> **What this document is based on.** The function signatures and behaviour below are taken from the Alizah-owned service code (`extractor.py`, `matcher.py`, `reply_generator.py`, `rechecker.py`, `edit_hint.py`) and the field lists of the frozen contracts. The author of this document did **not** see `main.py`, the statement ingestor's public functions, the frontend, or the real `models.py`. Anything about those is marked **TO BE CONFIRMED DURING FINAL INTEGRATION**. No HTTP routes are documented as existing; the request/response JSON in section D is a *proposal*, not current behaviour.

## A. Claim input (produced by the extractor)

```
extract_claim(image_bytes: bytes, filename: str) -> Claim
extract_claim_detailed(image_bytes, filename, provider=None) -> ExtractionDetails   # Claim + partial_date / partial_time
```
Raises `ValueError` for empty / non-bytes input. With **no vision provider configured the extractor returns a Claim whose payment fields are all `None`** (it never fabricates). Plug a provider with `set_default_provider(...)`; `MockVisionProvider` is test/demo only and labels itself in `extraction_notes`.

| Claim field | What the extractor produces |
|---|---|
| `claim_id` | `claim_<12 hex>` (random per extraction) |
| `source_file` | file name only (path stripped) |
| `image_hash` | `dhash256:<64 hex>` (perceptual), or `sha256:<hex>` if the bytes are not a decodable image |
| `payer_name`, `payee_name` | whitespace/casing normalized, or `None` |
| `payer_upi_id`, `payee_upi_id` | lower-case `local@handle`, or `None`; masked IDs (`ab****12@bank`) kept with confidence capped at 0.5 |
| `amount` | positive float (2 dp) or `None` |
| `currency` | `"INR"` only when evidenced, else `None` |
| `timestamp` | `YYYY-MM-DDTHH:MM:SS`, naive, only when date **and** time were read; else `None` (partial date/time is available from `extract_claim_detailed`) |
| `reference` | exactly 12 digits or `None` |
| `app_style_guess` | PhonePe / Google Pay / Paytm / BHIM / Amazon Pay / CRED, else `None` |
| `status_shown` | `success` / `failed` / `pending`, else `None` |
| `confidence` | dict, each value 0..1, `0.0` = not extracted. Keys: reference, amount, currency, timestamp, payer_name, payer_upi_id, payee_name, payee_upi_id, status_shown, app_style_guess |
| `extraction_notes` | up to 12 short notes (<=160 chars) |

## B. Statement input (`StatementRow`, produced by the statement ingestor)

Ingestor function names and signatures: **TO BE CONFIRMED DURING FINAL INTEGRATION** (not inspected). What the matcher reads from each row:

| Field | Use |
|---|---|
| `row_id` | reported in `Verdict.matched_row_id` and reasons; should be unique within one statement |
| `credit` | only rows with `credit > 0` count as payment evidence |
| `debit` | never matched as a payment. Only used when a claim's reference sits on a debit-only row → `Contradicted` (`direction`) |
| `datetime` | time comparison. A time of exactly `00:00:00` is treated as date-only (such rows cap at Tier 3) |
| `extracted_reference` | exact 12-digit reference for Tier 1. The matcher also looks for 12-digit tokens in `narration` |
| `narration` | reference fallback; payer UPI ID / name evidence |
| `name_hint` | payer-name evidence; a clearly different name can contradict a reference match |
| `balance`, `source_page_or_row` | not read |

Amounts are compared to the paisa (no float tolerance beyond rounding to 2 dp).

## C. `StatementMeta` input

| Field | Use by the matcher |
|---|---|
| `coverage_start`, `coverage_end` | coverage logic. A date-only `coverage_end` (midnight) includes the whole day |
| `parse_confidence` | below 0.5 → a missing payment is **not** concluded (`Can't verify yet`) |
| `mapping_used`, `balance_chain_result`, `row_count`, `warnings` | not read |

`meta=None` or missing coverage dates is allowed: matches by reference/amount still work, but "Not found" is never concluded.

## D. Verification request

Python-level contract (exact):

```python
from app.services.matcher import match_claims, MatchConfig
from app.services.reply_generator import attach_replies

verdicts = match_claims(claims, rows, meta)              # List[Verdict], same order as claims
verdicts = attach_replies(verdicts)                      # copies with suggested_reply filled
```
- `match_claims(claims, statement_rows, statement_meta=None, config=None)`; the three-argument call is the public API.
- Pure and deterministic; one Verdict per claim; empty claims → `[]`.
- `MatchConfig` defaults: `time_window_minutes=30`, `reference_time_conflict_hours=24`, `name_similar_threshold=0.80`, `name_conflict_threshold=0.30`, `near_hash_bits=6`, `follow_up_delay_hours=24`, `min_parse_confidence=0.5`.

**Proposed** HTTP shape (NOT existing; route names TO BE CONFIRMED): upload one or more screenshots + one statement file → API runs extractor per image, ingestor once, then `match_claims` → `attach_replies` → returns `{"verdicts": [...]}` using exactly the Verdict fields in section E (extra top-level fields such as per-claim `edit_hint` are an API-layer decision, since Verdict is frozen).

## E. Verdict response

| Field | Meaning |
|---|---|
| `claim_id` | id of the claim this verdict is for |
| `status` | one of the six statuses below |
| `tier` | `1` Verified · `2`/`3` Likely match · `4` Contradicted · `5` Not found · `None` for Duplicate and Can't verify yet (the matcher falls back to `0` only if `models.py` requires an int) |
| `matched_row_id` | statement row used as evidence. For Contradicted: the row sharing the reference. For Duplicate: the contested row (evidence pointer, **not** an assignment). `None` if no row |
| `confidence` | 0..1, rule-based evidence strength (not a measured probability); see below |
| `reasons` | ordered list of short deterministic sentences naming the evidence |
| `field_differences` | claim-vs-statement text, only for Contradicted, e.g. `{"amount": "claim=500.0, statement=300.0"}`. Keys used: `amount`, `payer_name`, `timestamp`, `status_shown`, `direction` |
| `follow_up_after` | ISO datetime; set only for "Can't verify yet" when the claim is after / near `coverage_end` (claim time + 24 h) |
| `suggested_reply` | empty from the matcher; filled by `attach_replies` / `recheck_claims` |

### Statuses (decision-support wording; no verdict says a person did something wrong)
| Status | Meaning |
|---|---|
| **Verified** | Exact 12-digit reference and amount match a statement credit, and no field conflicts. Confidence 0.85–0.97. |
| **Likely match** | No reference proof. Tier 2: amount + time + payer identity evidence (0.60–0.89). Tier 3: amount + time only (0.35–0.60); identity/reference could not be confirmed. Never promoted to Verified. |
| **Contradicted** | The reference exists on the statement but a detail differs (amount, payer name, time far apart, screenshot shows a failed payment, or the row is a debit). Differences are listed in `field_differences`. A mismatch of evidence, not a judgement of intent. |
| **Not found** | No compatible credit, and the claim is safely inside statement coverage; or its only compatible credit was already used by another claim. |
| **Duplicate** | The claim shares evidence with another submitted claim (same reference, byte-identical file, a corroborated image fingerprint, or same payer/amount/time competing for one credit). One claim per group keeps its verdict. Duplicate evidence is not proof of misconduct. |
| **Can't verify yet** | The statement cannot support a conclusion: claim after/near `coverage_end` or before `coverage_start`, missing amount/timestamp, unknown coverage, unreadable/low-confidence statement, or non-INR currency. Confidence is 0.0 — absence is not evidence. |

### Evidence, coverage, replies
- **Reasons** are the evidence trail (e.g. "Exact 12-digit reference … matches statement row r12", "Amount matches: claim INR 500.00 vs statement credit INR 500.00"). They may contain payer names and amounts — treat them as sensitive (see PRIVACY_SECURITY.md).
- **Coverage / follow-up:** claim after `coverage_end` (or within one window of either edge) → `Can't verify yet`, never `Not found`; `follow_up_after` tells the UI when a statement covering the claim is needed. A match found by reference does not depend on coverage.
- **Reply:** `generate_reply(verdict, tone="professional", language="en")` — English only; tones `professional | friendly | brief`; text is built only from Verdict fields; user-supplied values are sanitized and length-capped.
- **Confidence:** Tier 1 ≈ 0.85–0.97; Tier 2 ≈ 0.60–0.89; Tier 3 ≈ 0.35–0.60; Contradicted 0.60–0.95; Duplicate 0.5–0.95 by evidence; Not found ≈ 0.55–0.75; Can't verify yet 0.0.

### Re-check flow
```python
from app.services.rechecker import recheck_claims, merge_rechecked, recheck_changes
new = recheck_claims(claims, newer_rows, newer_meta, previous_verdicts=verdicts)   # replies attached by default
merged = merge_rechecked(verdicts, new)        # swap by claim_id, order preserved
changes = recheck_changes(verdicts, new)       # [{claim_id, before, after, changed}]
```
Only claims previously "Can't verify yet" (or without a previous verdict) are re-run, through the same `match_claims`. Row ids from different statements may collide, so make `row_id` unique per statement if two are ever combined (**TO BE CONFIRMED** with the ingestor).

### Edit hint (separate from Verdict)
`compute_edit_hint(claim, peers=None, image_bytes=None) -> {"signal": "none|low|medium", "reason": str, "confidence": 0..1}` — a weak supporting note, never a status. It is not a Verdict field; whether/how the API returns it is an API-layer decision (**TO BE CONFIRMED**).

### Not in the contract
There is no `edit_hint`, `language` or `edit` field on Verdict; no HTTP route is defined by these services; no field named "fraud"/"fake" exists anywhere.
