"""Phase 3 tests: reply generator, re-check workflow, image-edit hint (Alizah).

Run from the repo root:
    python -m pytest tests/test_phase3.py -v
"""

import io
import itertools
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.models import Claim, StatementMeta, StatementRow, Verdict  # noqa: E402
from app.services.edit_hint import compute_edit_hint, edit_hints_for_claims  # noqa: E402
from app.services.matcher import match_claims  # noqa: E402
from app.services.rechecker import merge_rechecked, recheck_changes, recheck_claims  # noqa: E402
from app.services.reply_generator import attach_replies, generate_reply  # noqa: E402


BASE = datetime(2026, 10, 7, 10, 30)
REF = "123456789012"

DH_A = "dhash256:" + "0" * 64
DH_NEAR = "dhash256:" + "0" * 60 + "000f"
DH_FAR = "dhash256:" + "0" * 56 + "000000ff"

FORBIDDEN = (
    "scam",
    "fraudster",
    "fraudulent",
    "liar",
    "fake person",
    "fraud",
    "fake",
    "cheat",
    "forged",
)

STATUSES = [
    "Verified",
    "Likely match",
    "Contradicted",
    "Not found",
    "Duplicate",
    "Can't verify yet",
]


# ------------------------------------------------------------------ helpers


def iso(value):
    """Convert datetime values to the string format used by project models."""
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _construct(cls, kwargs, variants=()):
    """Construct a Pydantic model while allowing harmless compatibility variants."""
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


def mk_claim(
    cid="c1",
    amount=500.0,
    ts=BASE,
    ref=None,
    name=None,
    img=None,
    status=None,
    currency="INR",
):
    return Claim(
        claim_id=cid,
        source_file=f"{cid}.png",
        image_hash=img,
        payer_name=name,
        payer_upi_id=None,
        payee_name=None,
        payee_upi_id=None,
        amount=amount,
        currency=currency,
        timestamp=iso(ts),
        reference=ref,
        app_style_guess=None,
        status_shown=status,
        confidence={},
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
            datetime=iso(dt),
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
):
    return _construct(
        StatementMeta,
        dict(
            coverage_start=iso(start),
            coverage_end=iso(end),
            mapping_used={},
            balance_chain_result="ok",
            parse_confidence=pc,
            row_count=5,
            warnings=[],
        ),
        variants=[
            [{}, {"balance_chain_result": True}, {"balance_chain_result": None}]
        ],
    )


OLD_META = mk_meta()

NEW_META = mk_meta(
    start=datetime(2026, 11, 1),
    end=datetime(2026, 11, 30, 23, 59),
)

LATE = datetime(2026, 11, 7, 10, 30)


def V(
    status,
    tier=None,
    row=None,
    conf=0.9,
    reasons=(),
    diffs=None,
    follow=None,
):
    """Hand-made verdict for reply-generator tests."""
    return SimpleNamespace(
        claim_id="x",
        status=status,
        tier=tier,
        matched_row_id=row,
        confidence=conf,
        reasons=list(reasons),
        field_differences=diffs or {},
        follow_up_after=follow,
        suggested_reply=None,
    )


def one(claim, rows, meta=OLD_META):
    return match_claims([claim], rows, meta)[0]


def text(v):
    r = v.reasons
    return " | ".join(r) if isinstance(r, (list, tuple)) else str(r)


# ======================================================
# REPLY GENERATOR
# ======================================================


@pytest.mark.parametrize(
    "status,start",
    [
        ("Verified", "The payment appears to be verified."),
        (
            "Likely match",
            "The payment is likely to match a statement transaction",
        ),
        (
            "Contradicted",
            "We found a transaction with the same reference, but some payment details differ",
        ),
        (
            "Not found",
            "We could not find a matching transaction within the available statement coverage.",
        ),
        (
            "Duplicate",
            "This payment appears to duplicate another submitted payment claim.",
        ),
        (
            "Can't verify yet",
            "This payment cannot be verified from the current statement coverage.",
        ),
    ],
)
def test_each_status_has_the_expected_headline(status, start):
    assert generate_reply(V(status)).startswith(start)


def test_verified_mentions_reference_and_amount_and_row():
    r = generate_reply(V("Verified", 1, "r12", 0.97))
    assert "reference and amount match" in r
    assert "r12" in r
    assert "high" in r


def test_likely_match_tier3_says_identity_and_reference_unconfirmed():
    r = generate_reply(V("Likely match", 3, "r1", 0.45))
    assert "could not be confirmed" in r
    assert "possible match only" in r
    assert "low" in r


def test_likely_match_tier2_does_not_use_tier3_wording():
    r = generate_reply(V("Likely match", 2, "r1", 0.75))
    assert "possible match only" not in r
    assert "consistent with the statement" in r


def test_contradicted_lists_field_differences_exactly():
    r = generate_reply(
        V(
            "Contradicted",
            4,
            "r1",
            diffs={
                "amount": "claim=500.0, statement=300.0",
                "payer_name": "claim=Ali, statement=Ayesha",
            },
        )
    )

    assert "amount (submitted: 500.0; statement: 300.0)" in r
    assert "payer name (submitted: Ali; statement: Ayesha)" in r
    assert r.index("amount") < r.index("payer name")


def test_contradicted_without_differences_still_reads_well():
    r = generate_reply(V("Contradicted"))
    assert r.startswith("We found a transaction")
    assert "Differences found" not in r


def test_unparseable_difference_text_is_shown_raw():
    r = generate_reply(
        V("Contradicted", diffs={"direction": "odd text"})
    )
    assert "transaction direction: odd text" in r


def test_not_found_asks_to_recheck_and_share_details():
    r = generate_reply(V("Not found"))
    assert "recheck your UPI/bank app" in r
    assert "reference number, amount and time" in r


def test_not_found_for_consumed_credit_says_so():
    r = generate_reply(
        V(
            "Not found",
            reasons=[
                "The compatible statement credit(s) (r1) were already assigned to claim(s) a"
            ],
        )
    )
    assert "already used for another claim" in r


def test_duplicate_default_and_variants():
    assert "submitted more than once" in generate_reply(V("Duplicate"))

    assert "different payer names" in generate_reply(
        V("Duplicate", reasons=["... different payer names ..."])
    )

    assert "primary submission" in generate_reply(
        V(
            "Duplicate",
            reasons=[
                "Claim a is treated as the primary submission (status: Verified)."
            ],
        )
    )


def test_cant_verify_default_asks_for_newer_statement():
    assert generate_reply(V("Can't verify yet")).endswith(
        "Please provide a newer statement."
    )


def test_cant_verify_follow_up_datetime_is_formatted_deterministically():
    for follow in (
        datetime(2026, 11, 8, 9, 5),
        "2026-11-08T09:05:00",
    ):
        assert (
            "covers at least 08 Nov 2026 09:05."
            in generate_reply(V("Can't verify yet", follow=follow))
        )


@pytest.mark.parametrize(
    "reason,expect",
    [
        (
            "Claim timestamp is before the statement coverage start; an earlier statement is required.",
            "earlier statement",
        ),
        (
            "The claim has no readable amount, so it cannot be compared.",
            "share the payment amount",
        ),
        (
            "The claim has no readable timestamp, so statement coverage cannot be checked.",
            "date and time",
        ),
        (
            "Claim currency is USD; only INR statements are supported.",
            "Only INR",
        ),
        (
            "The statement was parsed with low confidence (0.30); ...",
            "clearer or different export",
        ),
        (
            "The statement contains no readable transactions, ...",
            "no readable transactions",
        ),
        (
            "Statement coverage dates are unknown, so ...",
            "coverage dates",
        ),
    ],
)
def test_cant_verify_next_step_follows_the_reason(reason, expect):
    assert expect in generate_reply(
        V("Can't verify yet", reasons=[reason])
    )


def test_unparseable_follow_up_falls_back_to_newer_statement():
    assert "newer statement" in generate_reply(
        V("Can't verify yet", follow="not a date")
    )


def test_missing_reasons_none_or_empty_do_not_crash():
    for reasons in (None, [], ""):
        v = V("Not found")
        v.reasons = reasons
        assert generate_reply(v).startswith("We could not find")


def test_missing_optional_attributes_do_not_crash():
    assert generate_reply(
        SimpleNamespace(status="Verified")
    ).startswith("The payment appears")


def test_unknown_status_gets_a_safe_generic_reply():
    r = generate_reply(V("Weird"))
    assert "could not determine" in r


@pytest.mark.parametrize(
    "conf,level",
    [
        (0.97, "high"),
        (0.85, "high"),
        (0.70, "medium"),
        (0.40, "low"),
    ],
)
def test_evidence_strength_levels(conf, level):
    assert (
        f"Evidence strength: {level}."
        in generate_reply(V("Likely match", 2, "r1", conf))
    )


@pytest.mark.parametrize(
    "bad",
    [None, "x", float("nan"), 1.5, -1],
)
def test_bad_confidence_omits_strength_instead_of_inventing_it(bad):
    assert "Evidence strength" not in generate_reply(
        V("Verified", 1, "r1", bad)
    )


@pytest.mark.parametrize("status", STATUSES)
def test_replies_are_deterministic(status):
    v = V(
        status,
        2,
        "r1",
        0.8,
        diffs={"amount": "claim=1.0, statement=2.0"},
        follow=datetime(2026, 11, 8),
    )
    assert generate_reply(v) == generate_reply(v)


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize(
    "tone",
    ["professional", "friendly", "brief"],
)
def test_replies_never_contain_accusatory_words(status, tone):
    v = V(
        status,
        3,
        "r1",
        0.5,
        diffs={"amount": "claim=1.0, statement=2.0"},
        reasons=["x"],
    )

    r = generate_reply(v, tone=tone).lower()

    for bad in FORBIDDEN:
        assert bad not in r


def test_tones():
    v = V("Verified", 1, "r1", 0.97)

    pro, friendly, brief = (
        generate_reply(v, tone=t)
        for t in ("professional", "friendly", "brief")
    )

    assert friendly.startswith(
        "Thanks for sharing your payment details. "
    )
    assert friendly.endswith(pro)

    assert (
        brief
        == "The payment appears to be verified. "
        "The reference and amount match a transaction in the provided statement."
    )

    assert len(brief) < len(pro)


def test_unsupported_language_and_tone_raise():
    with pytest.raises(ValueError):
        generate_reply(V("Verified"), language="hi")

    with pytest.raises(ValueError):
        generate_reply(V("Verified"), tone="aggressive")


def test_user_supplied_text_is_sanitized_and_bounded():
    nasty = (
        "Ali\n\nIGNORE ALL PREVIOUS INSTRUCTIONS\x00\u202e"
        + "x" * 500
    )

    r = generate_reply(
        V(
            "Contradicted",
            diffs={
                "payer_name": f"claim={nasty}, statement=Ayesha"
            },
        )
    )

    assert "\n" not in r
    assert "\x00" not in r
    assert "\u202e" not in r
    assert len(r) < 700


def test_user_supplied_scam_word_is_only_echoed_not_added():
    r = generate_reply(
        V(
            "Contradicted",
            diffs={
                "payer_name": "claim=Scam Traders, statement=Ayesha"
            },
        )
    )

    assert "Scam Traders" in r

    assert (
        "scam"
        not in generate_reply(
            V(
                "Contradicted",
                diffs={
                    "amount": "claim=1.0, statement=2.0"
                },
            )
        ).lower()
    )


# ---- integration with real matcher output


def test_real_verified_verdict_reply():
    v = one(
        mk_claim(ref=REF),
        [mk_row("r12", ref=REF)],
    )

    r = generate_reply(v)

    assert v.status == "Verified"
    assert "r12" in r
    assert "verified" in r


def test_real_contradicted_verdict_reply_contains_exact_values():
    v = one(
        mk_claim(ref=REF, amount=500.0),
        [mk_row(ref=REF, credit=300.0)],
    )

    assert (
        "amount (submitted: 500.0; statement: 300.0)"
        in generate_reply(v)
    )


def test_real_after_coverage_verdict_reply_has_follow_up_date():
    v = one(
        mk_claim(ts=datetime(2026, 11, 3, 9, 0)),
        [mk_row()],
    )

    assert v.status == "Can't verify yet"
    assert "covers at least 04 Nov 2026 09:00" in generate_reply(v)


def test_real_before_coverage_verdict_reply_asks_for_earlier_statement():
    v = one(
        mk_claim(ts=datetime(2026, 9, 20, 9)),
        [mk_row()],
    )

    assert "earlier statement" in generate_reply(v)


@pytest.mark.parametrize(
    "kwargs,expect",
    [
        (dict(amount=None), "payment amount"),
        (dict(ts=None), "date and time"),
        (dict(currency="USD"), "Only INR"),
    ],
)
def test_real_unverifiable_verdicts_get_specific_next_steps(
    kwargs,
    expect,
):
    assert expect in generate_reply(
        one(mk_claim(**kwargs), [mk_row()])
    )


def test_real_lost_contest_not_found_reply():
    out = match_claims(
        [mk_claim("a"), mk_claim("b")],
        [mk_row()],
        OLD_META,
    )

    loser = next(
        v for v in out
        if v.status == "Not found"
    )

    assert "already used for another claim" in generate_reply(loser)


def test_real_duplicate_reference_reply():
    out = match_claims(
        [
            mk_claim("a", ref=REF),
            mk_claim("b", ref=REF),
        ],
        [mk_row(ref=REF)],
        OLD_META,
    )

    dup = next(
        v for v in out
        if v.status == "Duplicate"
    )

    assert "duplicate another submitted payment claim" in generate_reply(dup)
    assert "primary submission" in generate_reply(dup)


def test_real_conflicting_names_reply():
    out = match_claims(
        [
            mk_claim(
                "a",
                ref=REF,
                name="Syeda Alizah",
            ),
            mk_claim(
                "b",
                ref=REF,
                name="Rahul Verma",
            ),
        ],
        [mk_row(ref=REF)],
        OLD_META,
    )

    assert all(
        "different payer names" in generate_reply(v)
        for v in out
    )


# ---- attach_replies


def test_attach_replies_fills_suggested_reply_and_changes_nothing_else():
    verdicts = match_claims(
        [
            mk_claim("a", ref=REF),
            mk_claim(
                "b",
                ts=datetime(2026, 12, 1),
            ),
        ],
        [mk_row(ref=REF)],
        OLD_META,
    )

    out = attach_replies(verdicts)

    assert [v.claim_id for v in out] == ["a", "b"]

    for before, after in zip(verdicts, out):
        assert after.suggested_reply
        assert after.suggested_reply == generate_reply(before)

        for f in (
            "claim_id",
            "status",
            "tier",
            "matched_row_id",
            "confidence",
            "reasons",
            "field_differences",
            "follow_up_after",
        ):
            assert getattr(before, f) == getattr(after, f)

        assert not before.suggested_reply


def test_attach_replies_keeps_existing_reply_unless_overwrite():
    v = match_claims(
        [mk_claim(ref=REF)],
        [mk_row(ref=REF)],
        OLD_META,
    )[0]

    mine = v.model_copy(
        update={"suggested_reply": "custom"}
    )

    assert attach_replies([mine])[0].suggested_reply == "custom"

    assert (
        attach_replies(
            [mine],
            overwrite=True,
        )[0].suggested_reply
        != "custom"
    )


def test_attach_replies_empty_and_none():
    assert attach_replies([]) == []
    assert attach_replies(None) == []


def test_attach_replies_tone_is_passed_through():
    v = match_claims(
        [mk_claim(ref=REF)],
        [mk_row(ref=REF)],
        OLD_META,
    )

    assert attach_replies(
        v,
        tone="friendly",
    )[0].suggested_reply.startswith("Thanks")


# ======================================================
# RE-CHECK
# ======================================================


def test_old_statement_leaves_late_claim_unverifiable():
    v = one(
        mk_claim(ts=LATE),
        [mk_row()],
    )

    assert v.status == "Can't verify yet"


def test_newer_statement_with_transaction_resolves_claim():
    claim = mk_claim(
        "late",
        ts=LATE,
        ref=REF,
    )

    first = match_claims(
        [claim],
        [mk_row()],
        OLD_META,
    )

    assert first[0].status == "Can't verify yet"

    new = recheck_claims(
        [claim],
        [mk_row(
            "n1",
            dt=LATE,
            ref=REF,
        )],
        NEW_META,
        previous_verdicts=first,
    )

    assert new[0].status == "Verified"
    assert new[0].matched_row_id == "n1"


def test_newer_statement_soft_match_gives_likely_never_verified():
    claim = mk_claim(
        "late",
        ts=LATE,
    )

    new = recheck_claims(
        [claim],
        [mk_row("n1", dt=LATE)],
        NEW_META,
    )

    assert new[0].status == "Likely match"
    assert new[0].tier == 3


def test_newer_statement_without_transaction_is_not_found():
    claim = mk_claim(
        "late",
        ts=LATE,
    )

    new = recheck_claims(
        [claim],
        [
            mk_row(
                "n1",
                credit=999.0,
                dt=LATE,
            )
        ],
        NEW_META,
    )

    assert new[0].status == "Not found"


def test_newer_statement_that_still_ends_too_early_stays_unresolved():
    claim = mk_claim(
        "later",
        ts=datetime(2026, 12, 20, 10, 0),
    )

    new = recheck_claims(
        [claim],
        [mk_row("n1", dt=LATE)],
        NEW_META,
    )

    assert new[0].status == "Can't verify yet"
    assert new[0].follow_up_after is not None


def test_newer_statement_can_contradict():
    claim = mk_claim(
        "late",
        ts=LATE,
        ref=REF,
        amount=500.0,
    )

    new = recheck_claims(
        [claim],
        [
            mk_row(
                "n1",
                dt=LATE,
                ref=REF,
                credit=300.0,
            )
        ],
        NEW_META,
    )

    assert new[0].status == "Contradicted"


def test_newer_statement_can_produce_duplicate():
    claims = [
        mk_claim("a", ts=LATE, ref=REF),
        mk_claim("b", ts=LATE, ref=REF),
    ]

    new = recheck_claims(
        claims,
        [mk_row("n1", dt=LATE, ref=REF)],
        NEW_META,
    )

    assert sorted(
        v.status for v in new
    ) == ["Duplicate", "Verified"]


def test_only_unresolved_claims_are_rechecked_when_previous_verdicts_given():
    claims = [
        mk_claim("done", ref=REF),
        mk_claim(
            "late",
            ts=LATE,
            ref="210987654321",
        ),
    ]

    first = match_claims(
        claims,
        [mk_row(ref=REF)],
        OLD_META,
    )

    assert {
        v.claim_id: v.status
        for v in first
    } == {
        "done": "Verified",
        "late": "Can't verify yet",
    }

    new = recheck_claims(
        claims,
        [
            mk_row(
                "n1",
                dt=LATE,
                ref="210987654321",
            )
        ],
        NEW_META,
        previous_verdicts=first,
    )

    assert [v.claim_id for v in new] == ["late"]
    assert new[0].status == "Verified"


def test_claims_without_previous_verdict_are_rechecked():
    new = recheck_claims(
        [mk_claim("fresh", ts=LATE)],
        [mk_row("n1", dt=LATE)],
        NEW_META,
        previous_verdicts=[],
    )

    assert [v.claim_id for v in new] == ["fresh"]


def test_unchanged_statement_gives_unchanged_result():
    claim = mk_claim(
        "late",
        ts=LATE,
    )

    first = match_claims(
        [claim],
        [mk_row()],
        OLD_META,
    )

    again = recheck_claims(
        [claim],
        [mk_row()],
        OLD_META,
        previous_verdicts=first,
        with_replies=False,
    )

    assert again[0].status == first[0].status == "Can't verify yet"
    assert again[0].reasons == first[0].reasons
    assert again[0].follow_up_after == first[0].follow_up_after


def test_recheck_reuses_matcher_exactly():
    claims = [
        mk_claim("a", ts=LATE),
        mk_claim("b", ts=LATE, ref=REF),
    ]

    rows = [
        mk_row("n1", dt=LATE),
        mk_row("n2", dt=LATE, ref=REF),
    ]

    direct = match_claims(
        claims,
        rows,
        NEW_META,
    )

    via = recheck_claims(
        claims,
        rows,
        NEW_META,
        with_replies=False,
    )

    assert [
        v.model_dump()
        for v in direct
    ] == [
        v.model_dump()
        for v in via
    ]


def test_recheck_adds_replies_by_default_and_can_skip_them():
    claim = mk_claim(
        "late",
        ts=LATE,
        ref=REF,
    )

    rows = [
        mk_row(
            "n1",
            dt=LATE,
            ref=REF,
        )
    ]

    assert recheck_claims(
        [claim],
        rows,
        NEW_META,
    )[0].suggested_reply

    assert not recheck_claims(
        [claim],
        rows,
        NEW_META,
        with_replies=False,
    )[0].suggested_reply


def test_recheck_is_deterministic():
    claims = [
        mk_claim(
            f"c{i}",
            ts=LATE + timedelta(minutes=i),
        )
        for i in range(5)
    ]

    rows = [
        mk_row(
            f"n{i}",
            dt=LATE + timedelta(minutes=2 * i),
        )
        for i in range(3)
    ]

    runs = [
        [
            v.model_dump()
            for v in recheck_claims(
                claims,
                rows,
                NEW_META,
            )
        ]
        for _ in range(3)
    ]

    assert runs[0] == runs[1] == runs[2]


def test_recheck_empty_inputs():
    assert recheck_claims(
        [],
        [mk_row()],
        NEW_META,
    ) == []

    assert recheck_claims(
        None,
        None,
        None,
    ) == []

    out = recheck_claims(
        [mk_claim(ts=LATE)],
        [],
        NEW_META,
    )

    assert out[0].status == "Can't verify yet"


def test_recheck_does_not_reuse_rows_of_already_verified_reference():
    old_claim = mk_claim(
        "done",
        ref=REF,
    )

    late_claim = mk_claim(
        "late",
        ref=REF,
        ts=BASE + timedelta(hours=1),
    )

    first = match_claims(
        [old_claim],
        [mk_row(ref=REF)],
        OLD_META,
    )

    first += [
        match_claims(
            [
                mk_claim(
                    "late",
                    ts=datetime(2026, 12, 25),
                )
            ],
            [mk_row()],
            OLD_META,
        )[0]
    ]

    overlapping = [
        mk_row(
            "r1",
            ref=REF,
        )
    ]

    new = recheck_claims(
        [old_claim, late_claim],
        overlapping,
        OLD_META,
        previous_verdicts=first,
        with_replies=False,
    )

    assert [v.claim_id for v in new] == ["late"]
    assert new[0].status != "Verified"
    assert "already belongs to claim done" in text(new[0])


def test_merge_rechecked_replaces_by_claim_id_and_keeps_order():
    claims = [
        mk_claim("a", ref=REF),
        mk_claim(
            "late",
            ts=LATE,
            ref="210987654321",
        ),
    ]

    first = match_claims(
        claims,
        [mk_row(ref=REF)],
        OLD_META,
    )

    new = recheck_claims(
        claims,
        [
            mk_row(
                "n1",
                dt=LATE,
                ref="210987654321",
            )
        ],
        NEW_META,
        previous_verdicts=first,
    )

    merged = merge_rechecked(
        first,
        new,
    )

    assert [v.claim_id for v in merged] == [
        "a",
        "late",
    ]

    assert [v.status for v in merged] == [
        "Verified",
        "Verified",
    ]

    assert first[1].status == "Can't verify yet"


def test_recheck_changes_summary():
    claims = [
        mk_claim(
            "late",
            ts=LATE,
            ref=REF,
        )
    ]

    first = match_claims(
        claims,
        [mk_row()],
        OLD_META,
    )

    new = recheck_claims(
        claims,
        [
            mk_row(
                "n1",
                dt=LATE,
                ref=REF,
            )
        ],
        NEW_META,
        previous_verdicts=first,
    )

    assert recheck_changes(
        first,
        new,
    ) == [
        {
            "claim_id": "late",
            "before": "Can't verify yet",
            "after": "Verified",
            "changed": True,
        }
    ]


def test_recheck_does_not_weaken_rules_weak_evidence_still_never_verified():
    for kw in (
        {},
        {"name": "Syeda Alizah"},
    ):
        out = recheck_claims(
            [
                mk_claim(
                    "late",
                    ts=LATE,
                    **kw,
                )
            ],
            [
                mk_row(
                    "n1",
                    dt=LATE,
                    hint="SYEDA ALIZAH",
                )
            ],
            NEW_META,
        )

        assert out[0].status != "Verified"


def test_recheck_custom_statuses():
    claim = mk_claim(
        "nf",
        ts=datetime(2026, 10, 15, 12),
    )

    first = match_claims(
        [claim],
        [mk_row()],
        OLD_META,
    )

    assert first[0].status == "Not found"

    assert recheck_claims(
        [claim],
        [],
        OLD_META,
        previous_verdicts=first,
    ) == []

    again = recheck_claims(
        [claim],
        [
            mk_row(
                "n1",
                dt=datetime(2026, 10, 15, 12),
            )
        ],
        OLD_META,
        previous_verdicts=first,
        recheck_statuses=(
            "Can't verify yet",
            "Not found",
        ),
    )

    assert again[0].status == "Likely match"


# ======================================================
# EDIT HINT
# ======================================================


def png(software=None):
    from PIL import Image, PngImagePlugin

    info = PngImagePlugin.PngInfo()

    if software:
        info.add_text("Software", software)

    buf = io.BytesIO()

    Image.new(
        "RGB",
        (40, 40),
        (200, 220, 240),
    ).save(
        buf,
        "PNG",
        pnginfo=info,
    )

    return buf.getvalue()


def test_hint_shape_and_ranges():
    for h in (
        compute_edit_hint(mk_claim()),
        compute_edit_hint(mk_claim(img=DH_A)),
        compute_edit_hint(
            mk_claim(
                img=DH_A,
                ref=REF,
            ),
            peers=[
                mk_claim(
                    "p",
                    img=DH_A,
                    ref=REF,
                    amount=900.0,
                )
            ],
        ),
    ):
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
        assert h["reason"]


def test_no_image_information_is_none_with_zero_confidence():
    h = compute_edit_hint(
        mk_claim(img=None)
    )

    assert h == {
        "signal": "none",
        "reason": "No image information is available for this claim.",
        "confidence": 0.0,
    }


def test_missing_image_data_with_peers_is_none():
    assert (
        compute_edit_hint(
            mk_claim(img=None),
            peers=[mk_claim("p", img=DH_A)],
        )["signal"]
        == "none"
    )


def test_image_without_peers_is_none_and_does_not_claim_authenticity():
    h = compute_edit_hint(
        mk_claim(img=DH_A)
    )

    assert h["signal"] == "none"
    assert "does not prove" in h["reason"]


def test_identical_image_same_payment_fields_is_not_an_edit_hint():
    a = mk_claim(
        "a",
        img=DH_A,
        ref=REF,
    )

    b = mk_claim(
        "b",
        img=DH_A,
        ref=REF,
    )

    assert compute_edit_hint(
        a,
        peers=[b],
    )["signal"] == "none"


def test_near_identical_image_same_reference_different_amount_is_medium():
    a = mk_claim(
        "a",
        img=DH_A,
        ref=REF,
        amount=500.0,
    )

    b = mk_claim(
        "b",
        img=DH_NEAR,
        ref=REF,
        amount=5000.0,
    )

    h = compute_edit_hint(
        a,
        peers=[b],
    )

    assert h["signal"] == "medium"
    assert "amount" in h["reason"]
    assert "same reference" in h["reason"]
    assert "claim b" in h["reason"]
    assert h["confidence"] <= 0.7


def test_near_identical_image_same_reference_different_payer_name_is_medium():
    a = mk_claim(
        "a",
        img=DH_A,
        ref=REF,
        name="Syeda Alizah",
    )

    b = mk_claim(
        "b",
        img=DH_A,
        ref=REF,
        name="Rahul Verma",
    )

    assert compute_edit_hint(
        a,
        peers=[b],
    )["signal"] == "medium"


def test_near_identical_image_different_amount_without_shared_reference_is_only_low():
    a = mk_claim(
        "a",
        img=DH_A,
        amount=500.0,
    )

    b = mk_claim(
        "b",
        img=DH_A,
        amount=700.0,
    )

    h = compute_edit_hint(
        a,
        peers=[b],
    )

    assert h["signal"] == "low"
    assert h["confidence"] < 0.5
    assert "look alike" in h["reason"]


def test_different_images_give_no_peer_signal():
    a = mk_claim(
        "a",
        img=DH_A,
        ref=REF,
        amount=500.0,
    )

    b = mk_claim(
        "b",
        img=DH_FAR,
        ref=REF,
        amount=900.0,
    )

    assert compute_edit_hint(
        a,
        peers=[b],
    )["signal"] == "none"


def test_sha256_hashes_are_not_perceptually_comparable():
    s = "sha256:" + "a" * 64

    assert compute_edit_hint(
        mk_claim(
            "a",
            img=s,
            amount=1.0,
        ),
        peers=[
            mk_claim(
                "b",
                img=s,
                amount=2.0,
            )
        ],
    )["signal"] == "none"


def test_peer_list_may_include_the_claim_itself():
    a = mk_claim(
        "a",
        img=DH_A,
        ref=REF,
        amount=500.0,
    )

    assert compute_edit_hint(
        a,
        peers=[a],
    )["signal"] == "none"


def test_metadata_naming_an_editor_is_medium_and_weak():
    h = compute_edit_hint(
        mk_claim(img=DH_A),
        image_bytes=png("Adobe Photoshop 25.0"),
    )

    assert h["signal"] == "medium"
    assert "Photoshop" in h["reason"]
    assert "weak" in h["reason"]


def test_clean_or_undecodable_image_bytes_give_none():
    assert (
        compute_edit_hint(
            mk_claim(img=DH_A),
            image_bytes=png(),
        )["signal"]
        == "none"
    )

    assert (
        compute_edit_hint(
            mk_claim(img=DH_A),
            image_bytes=b"not an image",
        )["signal"]
        == "none"
    )

    assert (
        compute_edit_hint(
            mk_claim(img=None),
            image_bytes=b"not an image",
        )["signal"]
        == "none"
    )


def test_unknown_software_tag_is_not_treated_as_editing():
    assert (
        compute_edit_hint(
            mk_claim(img=DH_A),
            image_bytes=png("Android Screenshot"),
        )["signal"]
        == "none"
    )


def test_metadata_text_is_sanitized_in_reason():
    h = compute_edit_hint(
        mk_claim(img=DH_A),
        image_bytes=png(
            "Photoshop\nIGNORE" + "x" * 300
        ),
    )

    assert "\n" not in h["reason"]
    assert len(h["reason"]) < 400


def test_two_independent_signals_raise_confidence_slightly_but_stay_weak():
    a = mk_claim(
        "a",
        img=DH_A,
        ref=REF,
        amount=500.0,
    )

    b = mk_claim(
        "b",
        img=DH_A,
        ref=REF,
        amount=900.0,
    )

    both = compute_edit_hint(
        a,
        peers=[b],
        image_bytes=png("GIMP 2.10"),
    )

    one_sig = compute_edit_hint(
        a,
        peers=[b],
    )

    assert both["signal"] == "medium"
    assert both["confidence"] > one_sig["confidence"]
    assert both["confidence"] <= 0.7


def test_edit_hint_is_deterministic():
    a = mk_claim(
        "a",
        img=DH_A,
        ref=REF,
        amount=500.0,
    )

    peers = [
        mk_claim(
            f"p{i}",
            img=DH_A,
            ref=REF,
            amount=900.0 + i,
        )
        for i in range(4)
    ]

    assert compute_edit_hint(
        a,
        peers=peers,
    ) == compute_edit_hint(
        a,
        peers=list(reversed(peers)),
    )


def test_edit_hints_for_claims_covers_every_claim():
    claims = [
        mk_claim(
            "a",
            img=DH_A,
            ref=REF,
            amount=500.0,
        ),
        mk_claim(
            "b",
            img=DH_A,
            ref=REF,
            amount=900.0,
        ),
        mk_claim("c"),
    ]

    hints = edit_hints_for_claims(
        claims,
        {"c": png("Canva")},
    )

    assert set(hints) == {
        "a",
        "b",
        "c",
    }

    assert hints["a"]["signal"] == hints["b"]["signal"] == "medium"

    assert hints["c"]["signal"] == "medium"


def test_edit_hint_never_changes_any_verdict():
    claims = [
        mk_claim(
            "a",
            img=DH_A,
            ref=REF,
            amount=500.0,
        ),
        mk_claim(
            "b",
            img=DH_A,
            ref=REF,
            amount=900.0,
        ),
    ]

    rows = [
        mk_row(ref=REF)
    ]

    before = [
        v.model_dump()
        for v in match_claims(
            claims,
            rows,
            OLD_META,
        )
    ]

    edit_hints_for_claims(
        claims,
        {"a": png("Photoshop")},
    )

    after = [
        v.model_dump()
        for v in match_claims(
            claims,
            rows,
            OLD_META,
        )
    ]

    assert before == after


def test_edit_hint_output_has_no_verdict_or_accusation_vocabulary():
    a = mk_claim(
        "a",
        img=DH_A,
        ref=REF,
        amount=500.0,
    )

    b = mk_claim(
        "b",
        img=DH_A,
        ref=REF,
        amount=900.0,
    )

    h = compute_edit_hint(
        a,
        peers=[b],
        image_bytes=png("Photoshop"),
    )

    blob = (
        h["reason"] + h["signal"]
    ).lower()

    for w in FORBIDDEN + (
        "verified",
        "contradicted",
    ):
        assert w not in blob


# ======================================================
# REGRESSION
# ======================================================


def test_phase2_public_api_unchanged():
    import inspect

    sig = inspect.signature(match_claims)

    assert list(sig.parameters)[:3] == [
        "claims",
        "statement_rows",
        "statement_meta",
    ]


def test_matcher_leaves_suggested_reply_unset():
    v = match_claims(
        [mk_claim(ref=REF)],
        [mk_row(ref=REF)],
        OLD_META,
    )[0]

    assert not v.suggested_reply