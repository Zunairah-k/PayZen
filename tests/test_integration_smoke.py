"""Small integration smoke test for Alizah-owned services (Day 3).

Offline: no internet, no API keys, no vision API, no frontend, no real data.
It checks that the services import and compose; it does NOT repeat the large
Phase 1/2/3 suites.

Run from the repo root:
    python -m pytest tests/test_integration_smoke.py -v
"""

import itertools
import sys
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

STATUSES = {
    "Verified",
    "Likely match",
    "Contradicted",
    "Not found",
    "Duplicate",
    "Can't verify yet",
}

VERDICT_FIELDS = [
    "claim_id",
    "status",
    "tier",
    "matched_row_id",
    "confidence",
    "reasons",
    "field_differences",
    "follow_up_after",
    "suggested_reply",
]

CONTRACTS = {
    "Claim": [
        "claim_id",
        "source_file",
        "image_hash",
        "payer_name",
        "payer_upi_id",
        "payee_name",
        "payee_upi_id",
        "amount",
        "currency",
        "timestamp",
        "reference",
        "app_style_guess",
        "status_shown",
        "confidence",
        "extraction_notes",
    ],
    "StatementRow": [
        "row_id",
        "datetime",
        "narration",
        "debit",
        "credit",
        "balance",
        "extracted_reference",
        "name_hint",
        "source_page_or_row",
    ],
    "StatementMeta": [
        "coverage_start",
        "coverage_end",
        "mapping_used",
        "balance_chain_result",
        "parse_confidence",
        "row_count",
        "warnings",
    ],
    "Verdict": VERDICT_FIELDS,
}


# ------------------------------------------------------------------ imports


def test_all_alizah_services_and_models_import():
    from app import models  # noqa: F401
    from app.services import (
        edit_hint,
        extractor,
        matcher,
        rechecker,
        reply_generator,
    )  # noqa: F401

    for name in (
        "extract_claim",
        "extract_claim_detailed",
        "MockVisionProvider",
        "set_default_provider",
    ):
        assert hasattr(extractor, name)

    assert hasattr(matcher, "match_claims")
    assert hasattr(matcher, "MatchConfig")

    assert hasattr(reply_generator, "generate_reply")
    assert hasattr(reply_generator, "attach_replies")

    assert hasattr(rechecker, "recheck_claims")
    assert hasattr(edit_hint, "compute_edit_hint")


def _field_names(cls):
    f = getattr(cls, "model_fields", None) or getattr(cls, "__fields__", {})
    return list(f)


@pytest.mark.parametrize("name", sorted(CONTRACTS))
def test_frozen_contract_fields_are_still_present(name):
    from app import models

    present = _field_names(getattr(models, name))
    missing = [f for f in CONTRACTS[name] if f not in present]

    assert not missing, f"{name} is missing frozen fields: {missing}"


# ------------------------------------------------------------------ builders


def _construct(cls, kwargs, variants=()):
    last = None

    for combo in itertools.product(*variants) if variants else [()]:
        data = dict(kwargs)

        for part in combo:
            data.update(part)

        try:
            return cls(**data)
        except ValidationError as exc:
            last = exc

    raise last


def _row(
    row_id="r1",
    credit=500.0,
    ref="123456789012",
    dt=datetime(2026, 10, 7, 10, 30),
):
    from app.models import StatementRow

    # StatementRow.datetime is a string in the frozen contract.
    normalized_dt = dt.isoformat() if isinstance(dt, datetime) else dt

    return _construct(
        StatementRow,
        dict(
            row_id=row_id,
            datetime=normalized_dt,
            narration="UPI/CR/synthetic",
            debit=None,
            credit=credit,
            balance=None,
            extracted_reference=ref,
            name_hint=None,
            source_page_or_row="p1",
        ),
        variants=[
            [
                {},
                {"source_page_or_row": 1},
                {"source_page_or_row": None},
            ]
        ],
    )


def _meta(
    start=datetime(2026, 10, 1),
    end=datetime(2026, 10, 31, 23, 59),
):
    from app.models import StatementMeta

    # StatementMeta coverage dates are strings in the frozen contract.
    normalized_start = (
        start.isoformat() if isinstance(start, datetime) else start
    )
    normalized_end = end.isoformat() if isinstance(end, datetime) else end

    # mapping_used must remain a dictionary.
    # balance_chain_result is represented as a string in the model contract.
    return _construct(
        StatementMeta,
        dict(
            coverage_start=normalized_start,
            coverage_end=normalized_end,
            mapping_used={},
            balance_chain_result="ok",
            parse_confidence=0.95,
            row_count=1,
            warnings=[],
        ),
        variants=[
            [
                {},
                {"source_page_or_row": 1},
            ]
        ],
    )


def _mock_claim():
    """Claim produced by the REAL extractor pipeline using the labelled MOCK provider (offline)."""
    from app.services.extractor import MockVisionProvider, extract_claim_detailed

    provider = MockVisionProvider(
        {
            "amount": {
                "value": "₹500",
                "confidence": 0.95,
            },
            "reference": {
                "value": "1234 5678 9012",
                "confidence": 0.95,
            },
            "timestamp": {
                "value": "07 Oct 2026, 10:31 AM",
                "confidence": 0.9,
            },
            "payer_name": {
                "value": "SYNTHETIC PAYER",
                "confidence": 0.9,
            },
        }
    )

    return extract_claim_detailed(
        b"synthetic-bytes-not-a-real-screenshot",
        "synthetic.png",
        provider,
    ).claim


# ------------------------------------------------------------------ composition


def test_extractor_works_offline_and_default_provider_invents_nothing():
    from app.services.extractor import extract_claim

    c = extract_claim(
        b"synthetic-bytes",
        "x.png",
    )

    assert c.amount is None
    assert c.reference is None
    assert c.payer_name is None


def test_mock_extraction_flows_into_matcher_and_is_verified():
    from app.services.matcher import match_claims

    claim = _mock_claim()

    assert claim.reference == "123456789012"
    assert claim.amount == 500.0

    verdicts = match_claims(
        [claim],
        [_row()],
        _meta(),
    )

    assert len(verdicts) == 1

    v = verdicts[0]

    assert v.claim_id == claim.claim_id
    assert v.status == "Verified"
    assert v.tier == 1
    assert 0.0 <= v.confidence <= 1.0
    assert v.reasons


def test_verdict_exposes_every_documented_field_and_a_known_status():
    from app.services.matcher import match_claims

    v = match_claims(
        [_mock_claim()],
        [_row()],
        _meta(),
    )[0]

    for f in VERDICT_FIELDS:
        assert hasattr(v, f), f

    assert v.status in STATUSES


def test_reply_generator_populates_suggested_reply_without_changing_the_verdict():
    from app.services.matcher import match_claims
    from app.services.reply_generator import attach_replies, generate_reply

    v = match_claims(
        [_mock_claim()],
        [_row()],
        _meta(),
    )[0]

    out = attach_replies([v])[0]

    assert out.suggested_reply == generate_reply(v)
    assert out.suggested_reply.startswith(
        "The payment appears to be verified"
    )

    assert (
        out.status,
        out.tier,
        out.confidence,
        out.matched_row_id,
    ) == (
        v.status,
        v.tier,
        v.confidence,
        v.matched_row_id,
    )


def test_coverage_gap_then_recheck_flow_composes():
    from app.services.matcher import match_claims
    from app.services.rechecker import merge_rechecked, recheck_claims

    claim = _mock_claim()

    old_meta = _meta(
        end=datetime(2026, 10, 5)
    )

    unrelated = _row(
        "old1",
        credit=999.0,
        ref="210987654321",
        dt=datetime(2026, 10, 2, 9, 0),
    )

    first = match_claims(
        [claim],
        [unrelated],
        old_meta,
    )

    assert first[0].status == "Can't verify yet"
    assert first[0].follow_up_after is not None

    new = recheck_claims(
        [claim],
        [_row("n1")],
        _meta(),
        previous_verdicts=first,
    )

    assert new[0].status == "Verified"
    assert new[0].suggested_reply

    assert merge_rechecked(
        first,
        new,
    )[0].status == "Verified"


def test_edit_hint_is_a_separate_weak_signal():
    from app.services.edit_hint import compute_edit_hint

    h = compute_edit_hint(_mock_claim())

    assert set(h) == {
        "signal",
        "reason",
        "confidence",
    }

    assert h["signal"] in (
        "none",
        "low",
        "medium",
    )

    assert 0.0 <= h["confidence"] <= 1.0


def test_empty_inputs_are_safe_end_to_end():
    from app.services.matcher import match_claims
    from app.services.reply_generator import attach_replies

    assert attach_replies(
        match_claims([], [], None)
    ) == []

    assert match_claims(
        [_mock_claim()],
        [],
        None,
    )[0].status == "Can't verify yet"


def test_pipeline_needs_no_environment_variables_or_network(monkeypatch):
    for key in list(__import__("os").environ):
        if (
            "KEY" in key.upper()
            or "TOKEN" in key.upper()
            or "SECRET" in key.upper()
        ):
            monkeypatch.delenv(key, raising=False)

    from app.services.matcher import match_claims

    assert match_claims(
        [_mock_claim()],
        [_row()],
        _meta(),
    )[0].status == "Verified"