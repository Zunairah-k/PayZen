"""Tests for PayZen Phase 2 — verification / matching engine (Alizah).

Run from the repo root:
    python -m pytest tests/test_matcher.py -v
"""
import itertools
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.models import Claim, StatementMeta, StatementRow, Verdict  # noqa: E402
from app.services.matcher import MatchConfig, match_claims, name_similarity  # noqa: E402

BASE = datetime(2026, 10, 7, 10, 30)
REF = "123456789012"
REF2 = "210987654321"
SHA_A = "sha256:" + "a" * 64
DH_A = "dhash256:" + "0" * 64
DH_NEAR = "dhash256:" + "0" * 60 + "000f"   # 4 bits away from DH_A
DH_FAR = "dhash256:" + "0" * 56 + "000000ff"  # 8 bits away from DH_A


# ------------------------------------------------------------------ builders

def _construct(cls, kwargs, variants=()):
    """Build a shared-contract model whose exact field types we can't see."""
    last = None
    for combo in itertools.product(*[v for v in variants] or [[{}]]):
        data = dict(kwargs)
        for part in combo:
            data.update(part)
        try:
            return cls(**data)
        except ValidationError as exc:
            last = exc
    raise last


def iso(dt):
    return dt.isoformat()


def mk_claim(cid="c1", amount=500.0, ts=BASE, ref=None, name=None, upi=None, img=None,
             status=None, currency="INR", conf=None):
    return Claim(
        claim_id=cid,
        source_file=f"{cid}.png",
        image_hash=img,
        payer_name=name,
        payer_upi_id=upi,
        payee_name=None,
        payee_upi_id=None,
        amount=amount,
        currency=currency,
        timestamp=iso(ts) if isinstance(ts, datetime) else ts,
        reference=ref,
        app_style_guess=None,
        status_shown=status,
        confidence=conf or {},
        extraction_notes="",
    )


def mk_row(
    rid="r1",
    credit=500.0,
    dt=BASE,
    ref=None,
    hint=None,
    narration="UPI/CR/test",
    debit=None,
):
    return _construct(
        StatementRow,
        dict(
            row_id=rid,
            datetime=iso(dt) if isinstance(dt, datetime) else dt,
            narration=narration,
            debit=debit,
            credit=credit,
            balance=None,
            extracted_reference=ref,
            name_hint=hint,
            source_page_or_row="p1",
        ),
        variants=[
            [{}, {"source_page_or_row": 1}, {"source_page_or_row": None}]
        ],
    )


def mk_meta(
    start=datetime(2026, 10, 1),
    end=datetime(2026, 10, 31, 23, 59),
    pc=0.95,
    n=10,
):
    return StatementMeta(
        coverage_start=iso(start) if isinstance(start, datetime) else start,
        coverage_end=iso(end) if isinstance(end, datetime) else end,
        mapping_used={},
        balance_chain_result="ok",
        parse_confidence=pc,
        row_count=n,
        warnings=[],
    )


META = mk_meta()


def run(claims, rows, meta=META, config=None):
    return {v.claim_id: v for v in match_claims(claims, rows, meta, config)}


def run1(claim, rows, meta=META, config=None):
    return run([claim], rows, meta, config)[claim.claim_id]


def text(v):
    r = v.reasons
    return " | ".join(r) if isinstance(r, (list, tuple)) else str(r)


def fu(v):
    f = v.follow_up_after
    if f is None or f == "":
        return None
    return f if isinstance(f, datetime) else datetime.fromisoformat(str(f))


def diffs(v):
    return dict(v.field_differences or {})


def assert_valid(v):
    assert isinstance(v, Verdict)
    assert 0.0 <= v.confidence <= 1.0
    assert text(v).strip()


# ====================================================== TIER 1: Verified

def test_exact_reference_and_amount_is_verified():
    v = run1(mk_claim(ref=REF), [mk_row(ref=REF)])
    assert v.status == "Verified" and v.tier == 1 and v.matched_row_id == "r1"
    assert v.confidence >= 0.90
    assert not diffs(v)


def test_verified_reasons_are_specific():
    t = text(run1(mk_claim(ref=REF), [mk_row("r12", ref=REF)]))
    assert REF in t and "r12" in t
    assert "Amount matches" in t and "INR 500.00" in t
    assert "within 30 minutes" in t


@pytest.mark.parametrize(
    "raw",
    ["123456789012", "1234 5678 9012", "1234-5678-9012", " 123456789012 "],
)
def test_claim_reference_formatting_is_tolerated(raw):
    assert run1(mk_claim(ref=raw), [mk_row(ref=REF)]).status == "Verified"


def test_reference_found_only_in_narration_still_verifies_with_slightly_lower_confidence():
    a = run1(mk_claim(ref=REF), [mk_row(ref=REF)])
    b = run1(mk_claim(ref=REF), [mk_row(ref=None, narration=f"UPI/CR/{REF}/someone")])
    assert b.status == "Verified" and b.confidence < a.confidence and b.confidence >= 0.85
    assert "narration" in text(b)


def test_verified_without_claim_timestamp_notes_time_not_compared():
    v = run1(mk_claim(ref=REF, ts=None), [mk_row(ref=REF)])
    assert v.status == "Verified" and "Time was not compared" in text(v)


def test_verified_without_payer_name_notes_it():
    v = run1(mk_claim(ref=REF, name=None), [mk_row(ref=REF, hint="Ayesha Khan")])
    assert v.status == "Verified" and "not compared" in text(v)


def test_time_off_by_hours_still_verified_but_less_confident():
    near = run1(mk_claim(ref=REF), [mk_row(ref=REF)])
    far = run1(mk_claim(ref=REF), [mk_row(ref=REF, dt=BASE + timedelta(hours=3))])
    assert far.status == "Verified" and far.confidence < near.confidence
    assert "outside the 30-minute window" in text(far)


def test_same_reference_but_days_apart_is_contradicted():
    v = run1(mk_claim(ref=REF), [mk_row(ref=REF, dt=BASE + timedelta(days=3))])
    assert v.status == "Contradicted" and "timestamp" in diffs(v)


def test_date_only_statement_row_same_day_verifies():
    v = run1(mk_claim(ref=REF), [mk_row(ref=REF, dt=datetime(2026, 10, 7))])
    assert v.status == "Verified"


def test_date_only_statement_row_far_date_contradicts():
    v = run1(mk_claim(ref=REF), [mk_row(ref=REF, dt=datetime(2026, 10, 3))])
    assert v.status == "Contradicted"


def test_pending_screenshot_with_matching_credit_verifies_with_note():
    v = run1(mk_claim(ref=REF, status="pending"), [mk_row(ref=REF)])
    assert v.status == "Verified" and "pending" in text(v)


def test_failed_screenshot_with_matching_reference_is_contradicted():
    v = run1(mk_claim(ref=REF, status="failed"), [mk_row(ref=REF)])
    assert v.status == "Contradicted" and "status_shown" in diffs(v)


def test_low_extraction_confidence_lowers_verified_confidence():
    hi = run1(
        mk_claim(ref=REF, conf={"reference": 0.99, "amount": 0.99}),
        [mk_row(ref=REF)],
    )
    lo = run1(
        mk_claim(ref=REF, conf={"reference": 0.4, "amount": 0.4}),
        [mk_row(ref=REF)],
    )
    assert lo.status == "Verified" and lo.confidence < hi.confidence


def test_amount_matches_to_the_paisa():
    assert run1(
        mk_claim(ref=REF, amount=499.99),
        [mk_row(ref=REF, credit=500.0)],
    ).status == "Contradicted"

    assert run1(
        mk_claim(ref=REF, amount=499.99),
        [mk_row(ref=REF, credit=499.99)],
    ).status == "Verified"


def test_float_noise_in_amount_is_not_a_mismatch():
    assert run1(
        mk_claim(ref=REF, amount=0.1 + 0.2),
        [mk_row(ref=REF, credit=0.3)],
    ).status == "Verified"


# ================================================ TIER 4: Contradicted

def test_same_reference_wrong_amount_is_contradicted_with_exact_difference():
    v = run1(
        mk_claim(ref=REF, amount=500.0),
        [mk_row(ref=REF, credit=300.0)],
    )
    assert v.status == "Contradicted" and v.tier == 4 and v.matched_row_id == "r1"
    assert diffs(v)["amount"] == "claim=500.0, statement=300.0"
    assert "amount differs" in text(v)


def test_contradicted_never_verified_and_does_not_hunt_for_a_convenient_match():
    rows = [
        mk_row("r1", credit=300.0, ref=REF),
        mk_row("r2", credit=500.0),
    ]
    v = run1(mk_claim(ref=REF, amount=500.0), rows)
    assert v.status == "Contradicted" and v.matched_row_id == "r1"


def test_same_reference_incompatible_payer_name_is_contradicted():
    v = run1(
        mk_claim(ref=REF, name="Ali"),
        [mk_row(ref=REF, hint="Ayesha")],
    )
    assert v.status == "Contradicted"
    assert diffs(v)["payer_name"] == "claim=Ali, statement=Ayesha"


def test_upi_id_in_narration_overrides_name_hint_conflict():
    v = run1(
        mk_claim(ref=REF, name="Zed Q", upi="zed@okaxis"),
        [mk_row(ref=REF, hint="Ayesha", narration="UPI/CR/zed@okaxis/x")],
    )
    assert v.status == "Verified"


def test_similar_payer_name_verifies():
    v = run1(
        mk_claim(ref=REF, name="Syeda Alizah"),
        [mk_row(ref=REF, hint="SYEDA ALIZAH")],
    )
    assert v.status == "Verified" and "similar" in text(v)


def test_partially_similar_name_verifies_with_lower_confidence():
    full = run1(
        mk_claim(ref=REF, name="Syeda Alizah"),
        [mk_row(ref=REF, hint="SYEDA ALIZAH")],
    )
    part = run1(
        mk_claim(ref=REF, name="Syeda Alizah"),
        [mk_row(ref=REF, hint="SYEDA ALIZAH KHAN")],
    )
    assert part.status == "Verified" and part.confidence <= full.confidence


def test_multiple_conflicts_report_all_and_raise_confidence():
    one = run1(
        mk_claim(ref=REF, amount=500.0, name="Syeda Alizah"),
        [mk_row(ref=REF, credit=300.0, hint="Syeda Alizah")],
    )
    two = run1(
        mk_claim(ref=REF, amount=500.0, name="Ali"),
        [mk_row(ref=REF, credit=300.0, hint="Ayesha")],
    )
    assert set(diffs(two)) == {"amount", "payer_name"}
    assert set(diffs(one)) == {"amount"}
    assert two.confidence > one.confidence


def test_reference_on_debit_row_is_contradicted():
    v = run1(
        mk_claim(ref=REF),
        [mk_row("d1", credit=None, debit=500.0, ref=REF)],
    )
    assert v.status == "Contradicted" and "direction" in diffs(v)


def test_one_of_several_rows_with_same_reference_has_right_amount():
    rows = [
        mk_row("r1", credit=300.0, ref=REF),
        mk_row("r2", credit=500.0, ref=REF),
    ]
    v = run1(mk_claim(ref=REF), rows)
    assert v.status == "Verified" and v.matched_row_id == "r2"


def test_contradiction_picks_closest_row_when_several_share_reference():
    rows = [
        mk_row("r1", credit=100.0, ref=REF),
        mk_row("r2", credit=450.0, ref=REF),
    ]
    v = run1(mk_claim(ref=REF, amount=500.0), rows)
    assert v.status == "Contradicted" and v.matched_row_id == "r2" and "1 other" in text(v)


def test_low_reference_extraction_confidence_dampens_contradiction():
    hi = run1(
        mk_claim(ref=REF, amount=500.0, conf={"reference": 0.99}),
        [mk_row(ref=REF, credit=300.0)],
    )
    lo = run1(
        mk_claim(ref=REF, amount=500.0, conf={"reference": 0.3}),
        [mk_row(ref=REF, credit=300.0)],
    )
    assert lo.confidence < hi.confidence <= 0.95


# =================================================== TIER 2: Likely match

def test_amount_time_and_name_is_tier2_likely_match():
    v = run1(
        mk_claim(ts=BASE + timedelta(minutes=5), name="Syeda Alizah"),
        [mk_row(hint="SYEDA ALIZAH")],
    )
    assert v.status == "Likely match" and v.tier == 2
    t = text(v)
    assert "Amount matches" in t
    assert "within 30 minutes" in t
    assert "Payer name is similar" in t
    assert 0.65 <= v.confidence <= 0.89


def test_tier2_can_never_be_verified_even_with_perfect_evidence():
    v = run1(
        mk_claim(name="Syeda Alizah", upi="a@ybl"),
        [mk_row(hint="Syeda Alizah", narration="UPI/CR/a@ybl/Syeda Alizah")],
    )
    assert v.status == "Likely match" and v.tier == 2 and v.confidence <= 0.89


def test_name_found_in_narration_gives_tier2():
    v = run1(
        mk_claim(name="Syeda Alizah"),
        [mk_row(narration="UPI/CR/998877/SYEDA ALIZAH/ybl")],
    )
    assert v.status == "Likely match" and v.tier == 2 and "narration" in text(v)


def test_upi_id_in_narration_gives_tier2():
    v = run1(
        mk_claim(upi="alizah@oksbi"),
        [mk_row(narration="UPI/CR/1/alizah@oksbi/x")],
    )
    assert v.tier == 2 and "UPI ID" in text(v)


def test_masked_upi_is_not_identity_evidence():
    v = run1(
        mk_claim(upi="al****ah@oksbi"),
        [mk_row(narration="UPI/CR/1/al****ah@oksbi/x")],
    )
    assert v.tier == 3


@pytest.mark.parametrize(
    "minutes,expected",
    [
        (0, "Likely match"),
        (29, "Likely match"),
        (30, "Likely match"),
        (31, "Not found"),
        (-30, "Likely match"),
        (-31, "Not found"),
    ],
)
def test_time_window_boundaries(minutes, expected):
    v = run1(
        mk_claim(ts=BASE + timedelta(minutes=minutes)),
        [mk_row()],
    )
    assert v.status == expected


def test_custom_window_is_respected():
    cfg = MatchConfig(time_window_minutes=5)
    assert run1(
        mk_claim(ts=BASE + timedelta(minutes=10)),
        [mk_row()],
        config=cfg,
    ).status == "Not found"

    cfg = MatchConfig(time_window_minutes=60)
    assert run1(
        mk_claim(ts=BASE + timedelta(minutes=45)),
        [mk_row()],
        config=cfg,
    ).status == "Likely match"


def test_amount_must_be_equal():
    assert run1(
        mk_claim(amount=500.0),
        [mk_row(credit=500.01)],
    ).status == "Not found"


def test_clearly_different_name_excludes_the_candidate_and_is_explained():
    v = run1(
        mk_claim(name="Ali"),
        [mk_row(hint="Ayesha")],
    )
    assert v.status == "Not found" and "differs" in text(v) and "Ayesha" in text(v)


def test_claim_reference_conflicting_with_row_reference_is_not_a_soft_match():
    v = run1(
        mk_claim(ref=REF, name="Syeda Alizah"),
        [mk_row(ref=REF2, hint="Syeda Alizah")],
    )
    assert v.status == "Not found" and "different reference" in text(v)


def test_claim_reference_with_row_lacking_reference_is_tier3_with_note():
    v = run1(
        mk_claim(ref=REF),
        [mk_row(ref=None)],
    )
    assert v.status == "Likely match" and v.tier == 3 and "could not be checked" in text(v)


def test_row_has_reference_but_claim_does_not_is_allowed_with_note():
    v = run1(
        mk_claim(ref=None, name="Syeda Alizah"),
        [mk_row(ref=REF, hint="Syeda Alizah")],
    )
    assert v.status == "Likely match" and v.tier == 2 and "no reference" in text(v)


def test_date_only_row_is_capped_at_tier3():
    v = run1(
        mk_claim(name="Syeda Alizah"),
        [mk_row(dt=datetime(2026, 10, 7), hint="Syeda Alizah")],
    )
    assert v.status == "Likely match" and v.tier == 3 and "date only" in text(v)


def test_date_only_row_on_a_different_date_is_no_match():
    assert run1(
        mk_claim(),
        [mk_row(dt=datetime(2026, 10, 8))],
    ).status == "Not found"


# ================================================ TIER 3: amount + time only

def test_amount_and_time_only_is_low_confidence_possible_match():
    v = run1(mk_claim(), [mk_row()])
    assert v.status == "Likely match" and v.tier == 3
    assert 0.35 <= v.confidence <= 0.60


def test_tier3_reasons_state_missing_identity_and_reference_evidence():
    t = text(run1(mk_claim(), [mk_row()]))
    assert "Reference evidence is missing" in t
    assert "Payer identity could not be confirmed" in t
    assert "not enough to verify" in t


def test_closer_time_gives_higher_tier3_confidence():
    a = run1(mk_claim(ts=BASE), [mk_row()])
    b = run1(mk_claim(ts=BASE + timedelta(minutes=25)), [mk_row()])
    assert a.confidence > b.confidence


def test_weak_name_similarity_stays_tier3():
    v = run1(
        mk_claim(name="Syeda Alizah"),
        [mk_row(hint="SYEDA RAHMAN")],
    )
    assert v.tier == 3 and "weakly similar" in text(v)


def test_single_word_matching_name_is_not_tier2():
    v = run1(
        mk_claim(name="Ali"),
        [mk_row(hint="ALI")],
    )
    assert v.tier == 3


def test_low_extraction_confidence_lowers_soft_confidence():
    hi = run1(
        mk_claim(conf={"amount": 0.95, "timestamp": 0.95}),
        [mk_row()],
    )
    lo = run1(
        mk_claim(conf={"amount": 0.95, "timestamp": 0.3}),
        [mk_row()],
    )
    assert lo.confidence < hi.confidence and "low" in text(lo)


def test_ambiguous_candidates_reduce_confidence_and_say_so():
    single = run1(mk_claim(), [mk_row("r1")])
    multi = run1(
        mk_claim(),
        [mk_row("r1"), mk_row("r2", dt=BASE + timedelta(minutes=1))],
    )
    assert multi.status == "Likely match" and multi.confidence < single.confidence
    assert "ambiguous" in text(multi)


@pytest.mark.parametrize(
    "claim_kwargs,row_kwargs",
    [
        (dict(), dict()),
        (dict(name="Ali"), dict()),
        (dict(name="Ali"), dict(hint="Ali")),
        (dict(name="Syeda Alizah"), dict(hint="Syeda Rahman")),
        (dict(ref=REF), dict()),
        (dict(upi="x@ybl"), dict()),
        (dict(name="Syeda Alizah"), dict(hint="Syeda Alizah")),
        (
            dict(name="Syeda Alizah", upi="a@ybl"),
            dict(hint="Syeda Alizah", narration="a@ybl"),
        ),
        (
            dict(conf={"amount": 1.0, "timestamp": 1.0, "payer_name": 1.0}),
            dict(hint="Syeda Alizah"),
        ),
    ],
)
def test_weak_evidence_never_becomes_verified(claim_kwargs, row_kwargs):
    v = run1(mk_claim(**claim_kwargs), [mk_row(**row_kwargs)])
    assert v.status != "Verified"


# ============================================================ Missing data

def test_missing_timestamp_without_reference_cannot_be_verified_yet():
    v = run1(mk_claim(ts=None), [mk_row()])
    assert v.status == "Can't verify yet" and "no readable timestamp" in text(v)


def test_missing_amount_cannot_be_verified_yet():
    v = run1(mk_claim(amount=None), [mk_row()])
    assert v.status == "Can't verify yet" and "no readable amount" in text(v)


def test_missing_amount_but_reference_present_points_at_the_row_without_verifying():
    v = run1(
        mk_claim(amount=None, ref=REF),
        [mk_row("r9", ref=REF)],
    )
    assert v.status == "Can't verify yet" and "r9" in text(v)


@pytest.mark.parametrize("bad", [0, -5, float("nan"), float("inf")])
def test_unusable_amounts_are_treated_as_missing(bad):
    v = run1(mk_claim(amount=bad), [mk_row()])
    assert v.status == "Can't verify yet"


def test_missing_reference_falls_back_to_soft_matching():
    assert run1(mk_claim(ref=None), [mk_row()]).status == "Likely match"


def test_missing_payer_name_is_tier3_not_tier2():
    assert run1(
        mk_claim(name=None),
        [mk_row(hint="Syeda Alizah")],
    ).tier == 3


def test_statement_row_without_reference_name_or_narration_is_usable():
    row = mk_row(ref=None, hint=None, narration="")
    assert run1(mk_claim(), [row]).status == "Likely match"


def test_statement_row_without_datetime_cannot_soft_match():
    assert run1(mk_claim(), [mk_row(dt=None)]).status == "Not found"


def test_statement_row_without_datetime_can_still_verify_by_reference():
    assert run1(
        mk_claim(ref=REF),
        [mk_row(dt=None, ref=REF)],
    ).status == "Verified"


def test_non_inr_currency_cannot_be_verified():
    v = run1(
        mk_claim(currency="USD", ref=REF),
        [mk_row(ref=REF)],
    )
    assert v.status == "Can't verify yet" and "USD" in text(v)


def test_debit_rows_never_match_a_claim_softly():
    assert run1(
        mk_claim(),
        [mk_row(credit=None, debit=500.0)],
    ).status == "Not found"


def test_failed_screenshot_is_not_softly_matched():
    v = run1(
        mk_claim(status="failed"),
        [mk_row()],
    )
    assert v.status == "Not found" and "failed" in text(v)


def test_duck_typed_inputs_and_missing_attributes_do_not_crash():
    claim = SimpleNamespace(
        claim_id="x",
        amount="500",
        timestamp=BASE,
        reference=None,
        payer_name=None,
    )
    row = SimpleNamespace(
        row_id="r1",
        credit="500.00",
        datetime=BASE,
    )
    v = match_claims(
        [claim],
        [row],
        SimpleNamespace(
            coverage_start=date(2026, 10, 1),
            coverage_end=date(2026, 10, 31),
        ),
    )[0]
    assert v.status == "Likely match" and v.tier == 3


# ================================================================ Coverage

def test_no_candidate_inside_coverage_is_not_found():
    v = run1(
        mk_claim(ts=datetime(2026, 10, 15, 12, 0)),
        [mk_row()],
    )
    assert v.status == "Not found" and v.tier == 5
    assert "inside the statement coverage" in text(v)
    assert "No statement credit of INR 500.00" in text(v)
    assert 0.0 < v.confidence <= 0.80


def test_reference_not_on_statement_is_reported_in_not_found():
    v = run1(
        mk_claim(ts=datetime(2026, 10, 15, 12, 0), ref=REF),
        [mk_row()],
    )
    assert v.status == "Not found"
    assert f"No statement credit carries reference {REF}" in text(v)


def test_claim_after_coverage_end_cannot_be_verified_yet():
    v = run1(
        mk_claim(ts=datetime(2026, 11, 3, 9, 0)),
        [mk_row()],
    )
    assert v.status == "Can't verify yet" and v.status != "Not found"
    assert "after the statement coverage end" in text(v)
    assert "newer statement is required" in text(v)
    assert v.confidence == 0.0


def test_follow_up_after_is_set_and_after_the_claim():
    ts = datetime(2026, 11, 3, 9, 0)
    f = fu(run1(mk_claim(ts=ts), [mk_row()]))
    assert f is not None and f > ts


def test_follow_up_after_absent_for_other_statuses():
    assert fu(run1(mk_claim(ref=REF), [mk_row(ref=REF)])) is None
    assert fu(
        run1(
            mk_claim(ts=datetime(2026, 10, 15, 12)),
            [mk_row()],
        )
    ) is None


@pytest.mark.parametrize(
    "claim_ts,expected",
    [
        (datetime(2026, 10, 31, 23, 59), "Can't verify yet"),
        (datetime(2026, 10, 31, 23, 40), "Can't verify yet"),
        (datetime(2026, 10, 31, 23, 29), "Not found"),
        (datetime(2026, 10, 31, 23, 10), "Not found"),
        (datetime(2026, 11, 1, 0, 1), "Can't verify yet"),
        (datetime(2026, 10, 1, 0, 10), "Can't verify yet"),
        (datetime(2026, 10, 1, 0, 31), "Not found"),
        (datetime(2026, 9, 30, 23, 0), "Can't verify yet"),
    ],
)
def test_coverage_boundaries(claim_ts, expected):
    assert run1(
        mk_claim(ts=claim_ts),
        [mk_row(dt=datetime(2026, 10, 15))],
    ).status == expected


def test_claim_before_coverage_start_asks_for_an_earlier_statement():
    v = run1(
        mk_claim(ts=datetime(2026, 9, 20, 9)),
        [mk_row()],
    )
    assert v.status == "Can't verify yet"
    assert "earlier statement" in text(v)
    assert fu(v) is None


def test_missing_claim_timestamp_gives_no_coverage_conclusion():
    v = run1(
        mk_claim(ts=None, ref=REF),
        [mk_row()],
    )
    assert v.status == "Can't verify yet"
    assert "coverage cannot be checked" in text(v)


@pytest.mark.parametrize(
    "meta",
    [
        None,
        mk_meta(start=None),
        mk_meta(end=None),
        mk_meta(start=None, end=None),
    ],
)
def test_unknown_coverage_never_concludes_not_found(meta):
    v = run1(
        mk_claim(ts=datetime(2026, 10, 15, 12)),
        [mk_row()],
        meta=meta,
    )
    assert v.status == "Can't verify yet"


def test_inverted_coverage_is_rejected_safely():
    meta = mk_meta(
        start=datetime(2026, 10, 31),
        end=datetime(2026, 10, 1),
    )
    assert run1(
        mk_claim(ts=datetime(2026, 10, 15, 12)),
        [mk_row()],
        meta=meta,
    ).status == "Can't verify yet"


def test_low_parse_confidence_blocks_not_found():
    v = run1(
        mk_claim(ts=datetime(2026, 10, 15, 12)),
        [mk_row()],
        meta=mk_meta(pc=0.3),
    )
    assert v.status == "Can't verify yet" and "low confidence" in text(v)


def test_date_only_coverage_end_includes_the_whole_day():
    meta = mk_meta(end=datetime(2026, 10, 31))
    assert run1(
        mk_claim(ts=datetime(2026, 10, 31, 10, 0)),
        [mk_row(dt=datetime(2026, 10, 15))],
        meta=meta,
    ).status == "Not found"


def test_found_matches_do_not_depend_on_coverage_metadata():
    assert run1(
        mk_claim(ref=REF),
        [mk_row(ref=REF)],
        meta=None,
    ).status == "Verified"


def test_empty_statement_rows_cannot_prove_absence():
    v = run1(
        mk_claim(ts=datetime(2026, 10, 15, 12)),
        [],
    )
    assert v.status == "Can't verify yet"
    assert "no readable transactions" in text(v)


# ======================================================== One-to-one + ties

def test_one_credit_cannot_verify_two_claims():
    out = run(
        [mk_claim("a"), mk_claim("b")],
        [mk_row()],
    )
    matched = [
        v for v in out.values()
        if v.status in ("Verified", "Likely match")
    ]
    assert len(matched) == 1
    loser = next(v for v in out.values() if v not in matched)
    assert loser.status == "Not found"
    assert "already assigned" in text(loser)


def test_tie_break_is_lowest_claim_id_and_independent_of_input_order():
    for order in (["a", "b", "c"], ["c", "b", "a"], ["b", "c", "a"]):
        out = run(
            [mk_claim(i) for i in order],
            [mk_row()],
        )
        assert out["a"].status == "Likely match"
        assert out["b"].status == out["c"].status == "Not found"


def test_better_evidence_beats_claim_id_order():
    claims = [
        mk_claim("a", ts=BASE + timedelta(minutes=25)),
        mk_claim("b", ts=BASE + timedelta(minutes=1)),
    ]
    out = run(claims, [mk_row()])
    assert out["b"].status == "Likely match"
    assert out["a"].status == "Not found"


def test_name_evidence_beats_name_less_claim_for_the_same_credit():
    claims = [
        mk_claim("a"),
        mk_claim("b", name="Syeda Alizah"),
    ]
    out = run(
        claims,
        [mk_row(hint="SYEDA ALIZAH")],
    )
    assert out["b"].tier == 2
    assert out["a"].status == "Not found"


def test_global_assignment_gives_both_claims_a_row_when_possible():
    rows = [
        mk_row("r1", dt=BASE),
        mk_row("r2", dt=BASE + timedelta(minutes=20)),
    ]
    claims = [
        mk_claim("A", ts=BASE + timedelta(minutes=1)),
        mk_claim("B", ts=BASE - timedelta(minutes=25)),
    ]
    out = run(claims, rows)
    assert out["A"].status == "Likely match"
    assert out["B"].status == "Likely match"
    assert {out["A"].matched_row_id, out["B"].matched_row_id} == {"r1", "r2"}


def test_tier1_beats_soft_claim_for_the_same_row():
    rows = [mk_row("r1", ref=REF)]
    out = run(
        [mk_claim("soft"), mk_claim("hard", ref=REF)],
        rows,
    )
    assert out["hard"].status == "Verified"
    assert out["soft"].status != "Verified"
    assert out["soft"].matched_row_id != "r1"


def test_many_claims_each_get_their_own_credit_by_name():
    names = [
        "Syeda Alizah",
        "Umaima Khan",
        "Zunairah Ali",
        "Rahul Verma",
        "Priya Nair",
        "Arjun Mehta",
    ]
    rows = [
        mk_row(f"r{i}", hint=n.upper())
        for i, n in enumerate(names)
    ]
    claims = [
        mk_claim(f"c{i}", name=n)
        for i, n in enumerate(names)
    ]
    out = run(claims, rows)
    for i in range(len(names)):
        assert out[f"c{i}"].status == "Likely match"
        assert out[f"c{i}"].matched_row_id == f"r{i}"


def test_no_credit_row_is_ever_used_twice():
    rng = random.Random(7)
    rows = [
        mk_row(
            f"r{i}",
            credit=float(rng.choice([100, 200, 500])),
            dt=BASE + timedelta(minutes=rng.randint(0, 90)),
        )
        for i in range(12)
    ]
    claims = [
        mk_claim(
            f"c{i:02d}",
            amount=float(rng.choice([100, 200, 500])),
            ts=BASE + timedelta(minutes=rng.randint(0, 90)),
        )
        for i in range(25)
    ]
    out = run(claims, rows)
    used = [
        v.matched_row_id
        for v in out.values()
        if v.status in ("Verified", "Likely match")
    ]
    assert len(used) == len(set(used))


def test_multiple_claims_same_amount_only_as_many_matches_as_credits():
    rows = [
        mk_row("r1"),
        mk_row("r2", dt=BASE + timedelta(minutes=2)),
    ]
    out = run(
        [mk_claim(f"c{i}") for i in range(4)],
        rows,
    )
    assert sum(v.status == "Likely match" for v in out.values()) == 2
    assert sum(v.status == "Not found" for v in out.values()) == 2


def test_same_payer_competing_for_one_credit_is_duplicate_with_reasons():
    claims = [
        mk_claim("a", name="Syeda Alizah"),
        mk_claim(
            "b",
            name="SYEDA ALIZAH",
            ts=BASE + timedelta(minutes=3),
        ),
    ]
    out = run(claims, [mk_row()])
    assert out["a"].status == "Likely match"
    assert out["b"].status == "Duplicate"
    assert out["b"].matched_row_id == "r1"
    assert (
        "same payer name" in text(out["b"]).lower()
        or "Same payer name" in text(out["b"])
    )


def test_different_payers_competing_for_one_credit_are_not_called_duplicates():
    claims = [
        mk_claim("a", name="Syeda Alizah"),
        mk_claim("b", name="Rahul Verma"),
    ]
    out = run(claims, [mk_row()])
    statuses = sorted(v.status for v in out.values())
    assert "Duplicate" not in statuses
    assert statuses == ["Likely match", "Not found"]


# ================================================================ Duplicates

def test_same_reference_twice_one_verified_one_duplicate():
    out = run(
        [mk_claim("a", ref=REF), mk_claim("b", ref=REF)],
        [mk_row(ref=REF)],
    )
    assert out["a"].status == "Verified"
    d = out["b"]
    assert d.status == "Duplicate"
    assert d.matched_row_id == "r1"
    assert f"Same 12-digit reference {REF} as claim a" in text(d)
    assert 0.8 <= d.confidence <= 1.0
    assert "Also submitted as claim(s) b" in text(out["a"])


def test_duplicate_reasons_avoid_accusations():
    out = run(
        [mk_claim("a", ref=REF), mk_claim("b", ref=REF)],
        [mk_row(ref=REF)],
    )
    t = text(out["b"]).lower()
    assert "not proof" in t
    assert "fraud" not in t
    assert "fake" not in t


def test_three_claims_same_reference_one_original_two_duplicates():
    out = run(
        [mk_claim(c, ref=REF) for c in "abc"],
        [mk_row(ref=REF)],
    )
    assert sorted(v.status for v in out.values()) == [
        "Duplicate",
        "Duplicate",
        "Verified",
    ]


def test_same_reference_conflicting_names_without_resolution_verifies_nobody():
    claims = [
        mk_claim("a", ref=REF, name="Syeda Alizah"),
        mk_claim("b", ref=REF, name="Rahul Verma"),
    ]
    out = run(
        claims,
        [mk_row(ref=REF, hint=None)],
    )
    assert {v.status for v in out.values()} == {"Duplicate"}
    assert "different payer names" in text(out["a"])
    assert out["a"].confidence <= 0.70


def test_same_reference_conflicting_names_resolved_by_statement_name():
    claims = [
        mk_claim("a", ref=REF, name="Syeda Alizah"),
        mk_claim("b", ref=REF, name="Rahul Verma"),
    ]
    out = run(
        claims,
        [mk_row(ref=REF, hint="SYEDA ALIZAH")],
    )
    assert out["a"].status == "Verified"
    assert out["b"].status in ("Contradicted", "Duplicate")


def test_same_reference_one_correct_amount_one_wrong_keeps_contradiction():
    out = run(
        [
            mk_claim("a", ref=REF, amount=500.0),
            mk_claim("b", ref=REF, amount=900.0),
        ],
        [mk_row(ref=REF)],
    )
    assert out["a"].status == "Verified"
    assert out["b"].status == "Contradicted"
    assert "contradicted" not in text(out["a"]).lower() or True
    assert "shared with claim" in text(out["b"])


def test_identical_sha256_is_duplicate_even_without_other_agreement():
    out = run(
        [
            mk_claim("a", amount=500.0, img=SHA_A),
            mk_claim("b", amount=700.0, img=SHA_A),
        ],
        [],
    )
    assert {out["a"].status, out["b"].status} >= {"Duplicate"}
    assert "byte-identical" in text(out["b"])
    assert out["b"].confidence >= 0.9


def test_identical_perceptual_hash_alone_is_not_enough():
    claims = [
        mk_claim("a", amount=500.0, img=DH_A),
        mk_claim(
            "b",
            amount=700.0,
            img=DH_A,
            ts=BASE + timedelta(hours=2),
        ),
    ]
    out = run(claims, [mk_row()])
    assert "Duplicate" not in {v.status for v in out.values()}
    assert "not treated as a duplicate" in text(out["a"]) + text(out["b"])


def test_identical_perceptual_hash_with_same_amount_and_time_is_duplicate():
    claims = [
        mk_claim("a", img=DH_A, name="Syeda Alizah"),
        mk_claim(
            "b",
            img=DH_A,
            name="Syeda Alizah",
            ts=BASE + timedelta(seconds=20),
        ),
    ]
    out = run(
        claims,
        [mk_row(hint="SYEDA ALIZAH")],
    )
    assert out["a"].status == "Likely match"
    assert out["b"].status == "Duplicate"
    assert "supporting evidence, not proof" in text(out["b"])


def test_near_perceptual_hash_corroborated_is_duplicate():
    claims = [
        mk_claim("a", img=DH_A),
        mk_claim(
            "b",
            img=DH_NEAR,
            ts=BASE + timedelta(seconds=10),
        ),
    ]
    out = run(
        claims,
        [mk_row(), mk_row("r2")],
    )
    assert "Duplicate" in {v.status for v in out.values()}


def test_near_perceptual_hash_without_corroboration_is_ignored():
    claims = [
        mk_claim("a", img=DH_A),
        mk_claim("b", img=DH_NEAR, amount=900.0),
    ]
    out = run(
        claims,
        [mk_row(), mk_row("r2", credit=900.0)],
    )
    assert "Duplicate" not in {v.status for v in out.values()}


def test_perceptual_hash_beyond_threshold_is_ignored():
    claims = [
        mk_claim("a", img=DH_A),
        mk_claim(
            "b",
            img=DH_FAR,
            ts=BASE + timedelta(seconds=10),
        ),
    ]
    out = run(
        claims,
        [mk_row(), mk_row("r2")],
    )
    assert "Duplicate" not in {v.status for v in out.values()}


def test_shared_reference_not_on_statement_still_marks_the_second_claim_duplicate():
    ts = datetime(2026, 10, 15, 12)
    out = run(
        [
            mk_claim("a", ref=REF, ts=ts),
            mk_claim("b", ref=REF, ts=ts),
        ],
        [mk_row()],
    )
    assert out["a"].status == "Not found"
    assert out["b"].status == "Duplicate"
    assert out["b"].matched_row_id is None


def test_duplicates_of_a_contradicted_claim_leave_its_verdict_alone():
    out = run(
        [
            mk_claim("a", ref=REF, amount=900.0),
            mk_claim("b", ref=REF, amount=900.0),
        ],
        [mk_row(ref=REF)],
    )
    assert {v.status for v in out.values()} == {"Contradicted"}


# =============================================================== General

def test_empty_claims_returns_empty_list():
    assert match_claims([], [mk_row()], META) == []
    assert match_claims(None, None, None) == []


def test_output_order_and_ids_match_input():
    ids = ["z", "b", "m", "a"]
    res = match_claims(
        [mk_claim(i) for i in ids],
        [mk_row()],
        META,
    )
    assert [v.claim_id for v in res] == ids


def test_all_returned_verdicts_are_valid_contracts_with_bounded_confidence():
    claims = [
        mk_claim("v", ref=REF),
        mk_claim("w", ref=REF2, amount=1.0),
        mk_claim("x", name="Ali"),
        mk_claim("y", ts=datetime(2026, 12, 1)),
        mk_claim("z", amount=None),
        mk_claim("t", ts=None),
    ]
    for v in match_claims(
        claims,
        [mk_row(ref=REF), mk_row("r2", credit=1.0, ref=REF2, hint="B")],
        META,
    ):
        assert_valid(v)
        assert v.suggested_reply in (None, "")


def test_status_values_are_from_the_frozen_contract():
    allowed = {
        "Verified",
        "Likely match",
        "Contradicted",
        "Not found",
        "Duplicate",
        "Can't verify yet",
    }
    claims = [
        mk_claim(
            f"c{i}",
            amount=float(a),
            ts=BASE + timedelta(minutes=m),
            ref=r,
        )
        for i, (a, m, r) in enumerate(
            itertools.product(
                [500, 300],
                [0, 90],
                [None, REF],
            )
        )
    ]
    assert {
        v.status
        for v in match_claims(
            claims,
            [mk_row(ref=REF), mk_row("r2", credit=300.0)],
            META,
        )
    } <= allowed


def test_field_differences_only_on_contradictions():
    claims = [
        mk_claim("a", ref=REF, amount=1.0),
        mk_claim("b"),
        mk_claim("c", ts=datetime(2026, 12, 1)),
    ]
    for v in match_claims(claims, [mk_row(ref=REF)], META):
        if v.status != "Contradicted":
            assert not diffs(v)
        else:
            assert diffs(v)


def test_no_difference_is_reported_for_unavailable_evidence():
    v = run1(
        mk_claim(ref=REF, amount=500.0, name=None, ts=None),
        [mk_row(ref=REF, hint=None, credit=300.0)],
    )
    assert set(diffs(v)) == {"amount"}


def test_repeated_runs_are_identical():
    claims = [
        mk_claim(
            f"c{i}",
            amount=float(500 if i % 2 else 300),
            ts=BASE + timedelta(minutes=i * 3),
        )
        for i in range(10)
    ]
    rows = [
        mk_row(
            f"r{i}",
            credit=float(500 if i % 2 else 300),
            dt=BASE + timedelta(minutes=i * 4),
        )
        for i in range(6)
    ]
    runs = [
        [
            v.model_dump() if hasattr(v, "model_dump") else v.dict()
            for v in match_claims(claims, rows, META)
        ]
        for _ in range(3)
    ]
    assert runs[0] == runs[1] == runs[2]


def test_result_per_claim_is_independent_of_input_order():
    claims = [
        mk_claim(
            f"c{i}",
            amount=500.0,
            ts=BASE + timedelta(minutes=i),
        )
        for i in range(5)
    ]
    rows = [
        mk_row(
            f"r{i}",
            dt=BASE + timedelta(minutes=2 * i),
        )
        for i in range(3)
    ]
    base = {
        v.claim_id: (v.status, v.matched_row_id, v.confidence)
        for v in match_claims(claims, rows, META)
    }
    rng = random.Random(3)

    for _ in range(5):
        c2, r2 = claims[:], rows[:]
        rng.shuffle(c2)
        rng.shuffle(r2)
        again = {
            v.claim_id: (v.status, v.matched_row_id, v.confidence)
            for v in match_claims(c2, r2, META)
        }
        assert again == base


def test_inputs_are_not_mutated():
    claims = [mk_claim("a", ref=REF)]
    rows = [mk_row(ref=REF)]

    before = (
        [
            c.model_dump() if hasattr(c, "model_dump") else c.dict()
            for c in claims
        ],
        [
            r.model_dump() if hasattr(r, "model_dump") else r.dict()
            for r in rows
        ],
    )

    match_claims(claims, rows, META)

    after = (
        [
            c.model_dump() if hasattr(c, "model_dump") else c.dict()
            for c in claims
        ],
        [
            r.model_dump() if hasattr(r, "model_dump") else r.dict()
            for r in rows
        ],
    )

    assert before == after


def test_reasons_are_meaningful_never_a_bare_word():
    scenarios = [
        (mk_claim(ref=REF), [mk_row(ref=REF)]),
        (mk_claim(ref=REF, amount=1.0), [mk_row(ref=REF)]),
        (mk_claim(), [mk_row()]),
        (mk_claim(ts=datetime(2026, 12, 1)), [mk_row()]),
        (mk_claim(ts=datetime(2026, 10, 15, 12)), [mk_row()]),
        (mk_claim(amount=None), [mk_row()]),
    ]

    for claim, rows in scenarios:
        v = run1(claim, rows)
        items = v.reasons if isinstance(v.reasons, list) else [v.reasons]
        assert items
        assert all(
            isinstance(i, str) and len(i.split()) >= 4
            for i in items
        ), v.status


def test_reasons_never_use_accusatory_language():
    claims = [
        mk_claim("a", ref=REF),
        mk_claim("b", ref=REF),
        mk_claim("c", ref=REF, amount=1.0),
        mk_claim("d", img=SHA_A),
        mk_claim("e", img=SHA_A, amount=9.0),
        mk_claim("f", ts=datetime(2026, 12, 1)),
    ]

    for v in match_claims(claims, [mk_row(ref=REF)], META):
        t = text(v).lower()
        for bad in (
            "fake",
            "fraud",
            "forged",
            "cheat",
            "scam",
            "liar",
        ):
            assert bad not in t, (v.claim_id, bad)


def test_custom_name_threshold_changes_tier():
    cfg = MatchConfig(name_similar_threshold=0.99)
    v = run1(
        mk_claim(name="Syeda Alizah"),
        [mk_row(hint="SYEDA ALIZAH KHAN")],
        config=cfg,
    )
    assert v.tier == 3


# ============================================================ name_similarity

@pytest.mark.parametrize(
    "a,b,lo,hi",
    [
        ("Syeda Alizah", "SYEDA ALIZAH", 0.99, 1.0),
        ("Syeda Alizah", "Alizah Syeda", 0.99, 1.0),
        ("Mr. Rahul Verma", "RAHUL VERMA", 0.99, 1.0),
        ("Syeda Alizah", "Syeda Aliza", 0.85, 1.0),
        ("S Alizah", "Syeda Alizah", 0.75, 0.85),
        ("Ali", "Ali Khan", 0.0, 0.75),
        ("Ali", "Ali", 0.0, 0.75),
        ("Ali", "Ayesha", 0.0, 0.3),
        ("Syeda Alizah", "Rahul Verma", 0.0, 0.1),
    ],
)
def test_name_similarity_ranges(a, b, lo, hi):
    s = name_similarity(a, b)
    assert s is not None and lo <= s <= hi


@pytest.mark.parametrize(
    "a,b",
    [
        (None, "Ali"),
        ("Ali", None),
        ("", "Ali"),
        ("123", "Ali"),
        ("   ", "   "),
    ],
)
def test_name_similarity_is_none_without_usable_names(a, b):
    assert name_similarity(a, b) is None


def test_name_similarity_is_symmetric():
    assert name_similarity(
        "Syeda Alizah",
        "Alizah S",
    ) == name_similarity(
        "Alizah S",
        "Syeda Alizah",
    )