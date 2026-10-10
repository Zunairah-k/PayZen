# API and integration contract

The contract between statement ingestion, extraction, matching, replies, re-check and the API/UI layer. The data models in `backend/app/models.py` are frozen; changes need team agreement and a regression test.

## 1. Statement ingestion → API/UI

```python
to_shared(ingest_statement(file_bytes, filename, password=..., allow_vision=...))
```

Other entry points: `ingest_statement(bytes_or_path, filename, llm_policy="always"|"fallback"|"never")`, `ingest_text(text)`, and `to_shared(result, prefix="A-")` to keep row ids unique when two statements are combined (re-check). Users can override the column mapping or date order (`mapping_override`, month-first or day-first).

If `result.ok` is False, show `result.report.user_message` and act on `result.report.error_code`:

| Error code | UI action |
|---|---|
| `pdf_password_required` | Ask for the PDF password |
| `pdf_password_incorrect` | Ask the user to retry the password |
| `vision_consent_required` | Show the vision-processing consent checkbox |
| `pdf_scanned` | Show scanned-document handling and consent |

If `result.report.needs_confirmation` is True, show `result.report.mapping_summary` so the user can confirm the detected columns.

## 2. Claim (from the extractor)

`extract_claim(image_bytes, filename) -> Claim`; `extract_claim_detailed(...)` also returns partial date/time. Empty or non-bytes input raises `ValueError`. Missing fields stay `None` with confidence 0.0; the extractor never fabricates.

| Field | Value |
|---|---|
| `claim_id` | `claim_<12 hex>` |
| `source_file` | file name only |
| `image_hash` | `dhash256:<64 hex>`, or `sha256:<hex>` if the image cannot be decoded |
| `payer_name`, `payee_name` | normalized, or `None` |
| `payer_upi_id`, `payee_upi_id` | lower-case `local@handle`; masked IDs kept with confidence capped at 0.5 |
| `amount` | positive float (2 dp) or `None` |
| `timestamp` | `YYYY-MM-DDTHH:MM:SS` (naive), only when date and time were both read |
| `reference` | exactly 12 digits or `None` |
| `status_shown` | success / failed / pending, else `None` |
| `confidence` | per-field 0..1; 0.0 means not extracted |
| `extraction_notes` | up to 12 short notes |

## 3. Statement rows and metadata (what the matcher reads)

| `StatementRow` field | Use |
|---|---|
| `row_id` | reported in verdicts; unique within a statement |
| `credit` | only rows with `credit > 0` are payment evidence |
| `debit` | never matched; a reference on a debit-only row gives Contradicted (direction) |
| `datetime` | time comparison; exactly 00:00:00 is date-only and caps at Tier 3 |
| `extracted_reference`, `reference_confidence` | Tier 1 needs a **high**-confidence 12-digit reference; the matcher also scans narration |
| `narration`, `name_hint` | reference fallback and payer-name evidence |

| `StatementMeta` field | Use |
|---|---|
| `coverage_start`, `coverage_end` | ISO strings; `coverage_end` is the last covered moment (a date-only end includes the whole day) |
| `parse_confidence` | below 0.5, a missing payment is not concluded (Can't verify yet) |

A missing `meta` or missing coverage dates is allowed: reference and amount matches still work, but Not found is never concluded. Amounts are floats compared after `round(x, 2)`.

## 4. Matching

```python
verdicts = match_claims(claims, rows, meta)   # same order as claims; pure and deterministic
verdicts = attach_replies(verdicts)           # copies with suggested_reply filled
```

`MatchConfig` defaults: `time_window_minutes=30`, `reference_time_conflict_hours=24`, `name_similar_threshold=0.80`, `name_conflict_threshold=0.30`, `near_hash_bits=6`, `follow_up_delay_hours=24`, `min_parse_confidence=0.5`.

## 5. Verdict

| Field | Meaning |
|---|---|
| `claim_id`, `status` | claim and one of the six statuses |
| `tier` | 1 Verified; 2/3 Likely match; 4 Contradicted; 5 Not found; none for Duplicate and Can't verify yet |
| `matched_row_id` | evidence row (for Contradicted, the row sharing the reference) |
| `confidence` | rule-based evidence strength, not a measured probability |
| `reasons` | ordered, deterministic sentences naming the evidence |
| `field_differences` | Contradicted only, e.g. `{"amount": "claim=500.0, statement=300.0"}`; keys: amount, payer_name, timestamp, status_shown, direction |
| `follow_up_after` | ISO datetime, only for Can't verify yet |
| `suggested_reply` | filled by `attach_replies` / `recheck_claims` |

Confidence ranges: Tier 1 0.85–0.97 · Tier 2 0.60–0.89 · Tier 3 0.35–0.60 · Contradicted 0.60–0.95 · Duplicate 0.5–0.95 · Not found 0.55–0.75 · Can't verify yet 0.0.

Reasons can contain payer names, amounts and references: treat verdicts as sensitive data.

## 6. Replies, re-check, edit hint

- `generate_reply(verdict, tone="professional", language="en")`: tones professional, friendly, brief; language `en` only (the interface adds Hindi and Telugu payer messages in `frontend/src/replies.ts`); text built only from verdict fields; user values sanitised and capped at 80 characters.
- `recheck_claims(claims, newer_rows, newer_meta, previous_verdicts=...)`, `merge_rechecked(...)`, `recheck_changes(...)`: only Can't verify yet claims are re-run through the same matcher; credits already used by Verified or Likely claims cannot be reused. Make `row_id` unique per statement if two are combined.
- `compute_edit_hint(claim, peers=None, image_bytes=None)` returns `{"signal": none|low|medium, "reason", "confidence"}`, capped at 0.70; a note only, never a status.

## 7. HTTP routes

| Method and path | Purpose |
|---|---|
| `GET /health` | Liveness check |
| `POST /claims/upload` | Screenshots in, claims out |
| `POST /statement/upload` | One statement file in, rows and meta out |
| `POST /verify` | Claims, rows and meta in, verdicts out |
| re-check endpoint | Re-run *Can't verify yet* claims against a newer statement (name to confirm; see `tests/test_recheck_endpoint.py`) |
| `GET /intake/status`, `POST /intake/poll`, `GET /intake/messages`, `GET /intake/alerts` | Secure email inbox |
| `POST /intake/whatsapp-zip` | WhatsApp "export chat with media" ZIP |

Missing configuration returns 503 and Agentboxd connectivity errors return 502. *To verify:* compare this table with the live `/docs` page (https://payzen-z43b.onrender.com/docs) and fix any route name.

## 8. Integration rules

1. Check the frozen contracts first; make the smallest change; add a regression test; run the relevant file, then the full suite (`python -m pytest tests -q`).
2. Never duplicate matching logic in ingestion or UI; never change verdict meanings to compensate for another layer.
3. No UI text calls a payment or person "fake" or "fraud".
4. Tell the team about any contract change.