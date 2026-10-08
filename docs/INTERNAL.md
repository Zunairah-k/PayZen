## Latest Team Integration Contract

This is the shared hand-off contract for the final integration.

### Umaima — API / UI

Call the shared statement ingestion adapter with:

```python
to_shared(
    ingest_statement(
        file_bytes,
        filename,
        password=...,
        allow_vision=...
    )
)
```

If `result.ok` is `False`, display:

```python
result.report.user_message
```

Use `result.report.error_code` for the UI action:

| Error code | UI action |
|---|---|
| `pdf_password_required` | Ask for the PDF password |
| `pdf_password_incorrect` | Ask the user to retry the password |
| `vision_consent_required` | Show the vision-processing consent checkbox |
| `pdf_scanned` | Show scanned-document handling / consent |

If:

```python
result.report.needs_confirmation == True
```

show:

```python
result.report.mapping_summary
```

so the user can confirm the detected statement mapping.

### Alizah — Matcher

The matcher must consume the ingestion contract as follows:

- Coverage timestamps are ISO strings.
- `meta.coverage_end` is the **last covered moment**.
- Statement amounts are floats.
- Compare amounts using `round(x, 2)`, not raw floating-point equality.
- Only `reference_confidence == "high"` may produce automatic `Verified`.
- Medium, low, unknown, or uncertain references must never automatically produce `Verified`.

The matching ladder remains:

```text
High-confidence reference + equal amount → Verified
Amount + time + identity → Likely match
Amount + time only → Low-confidence Likely match
Reference/material field conflict → Contradicted
No candidate inside coverage → Not found
Outside/insufficient coverage → Can't verify yet
Shared evidence → Duplicate
```

This is an integration requirement, not a reason to redesign the matcher.

---

## Final Integration Checklist

### Backend

- [ ] Frozen Pydantic contracts remain compatible.
- [ ] Statement ingestion returns shared `StatementRow` / `StatementMeta`.
- [ ] Coverage values are handled as ISO strings.
- [ ] `coverage_end` is treated as the last covered moment.
- [ ] Amounts are compared after rounding to two decimals.
- [ ] Only high-confidence references can produce `Verified`.
- [ ] Tiers 2 and 3 can never produce `Verified`.
- [ ] Each statement credit can support at most one claim.
- [ ] Contradictions contain exact field differences.
- [ ] Coverage boundaries produce `Can't verify yet` where appropriate.
- [ ] Duplicate evidence is not treated as proof of fraud.
- [ ] Re-check uses the same matcher logic.

### Statement ingestion

- [ ] CSV works.
- [ ] XLSX works.
- [ ] Pasted text works.
- [ ] Text PDF works.
- [ ] Password-protected PDF handles required/incorrect passwords.
- [ ] Scanned PDF/photo path handles consent correctly.
- [ ] Mapping confirmation is shown when required.
- [ ] Coverage and balance-chain information are preserved.

### Frontend

- [ ] Upload flow works.
- [ ] Ingestion errors display `user_message`.
- [ ] Password prompts use the correct error code.
- [ ] Vision consent appears when required.
- [ ] Mapping confirmation appears when required.
- [ ] All six verdict statuses are displayed.
- [ ] Confidence and reasons are visible.
- [ ] Contradiction differences are visible.
- [ ] `follow_up_after` is visible for `Can't verify yet`.
- [ ] Suggested replies are copyable.
- [ ] Duplicate evidence is understandable.
- [ ] No UI calls a payment or person "fake" or "fraud".

### Security / privacy

- [ ] No real screenshots or statements are committed.
- [ ] No API keys or secrets are committed.
- [ ] `.env` is not exposed to the frontend.
- [ ] Uploads are not unnecessarily persisted.
- [ ] Sensitive financial values are not written to logs.
- [ ] External vision/model processing is disclosed and consented to where required.

### Testing

Run:

```powershell
python -m pytest tests/test_matcher.py -v
python -m pytest tests -v
```

Latest team-reported full-suite result:

```text
467 passed, 1 skipped
```

The skipped PDF password-flow test occurs when the optional `reportlab` dependency is unavailable.

Always rerun the complete suite after final integration because the test count may change.

---

## What Each Member Should NOT Change

### Umaima

Should not rewrite:
- the matcher
- matching tiers
- verdict meanings
- frozen data contracts without team agreement

### Zunairah

Should not:
- duplicate matching logic inside ingestion
- change verdict semantics
- change matcher scoring to compensate for ingestion behaviour

### Alizah

Should not:
- rewrite statement ingestion
- change frontend behaviour directly
- independently redesign the API contract

If a compatibility problem appears, make the smallest appropriate boundary fix and communicate the contract change.

---

## Current Project Priority

PayZen is now primarily in the **integration and final-polish stage**.

The goal is to connect the completed work reliably:

```text
Payment Screenshot
       ↓
Claim Extraction
       ↓
Statement Ingestion
       ↓
Shared Models
       ↓
Matcher
       ↓
Verdict
       ↓
Suggested Reply
       ↓
Frontend
       ↓
Re-check / Export
```

The most important final rule is:

> **Never produce a stronger verdict than the evidence supports.**

A false `Verified` is more serious than a cautious `Not found` or `Can't verify yet`.

---

## Ownership at a Glance

| Member | Primary ownership | Final integration responsibility |
|---|---|---|
| **Umaima** | API + UI | Connect ingestion, verification, replies and re-check into the user flow |
| **Zunairah** | Statement ingestion | Provide normalized rows/meta and clear ingestion status/error contracts |
| **Alizah** | Extraction + matcher + verdicts | Consume normalized statement data correctly and enforce conservative verification |

---

## Development Rule

For every change:

1. Check the frozen contracts first.
2. Make the smallest change necessary.
3. Add a focused regression test.
4. Run the relevant test file.
5. Run the full suite.
6. Update documentation after the behaviour is confirmed.
7. Tell the team about any contract change.

---