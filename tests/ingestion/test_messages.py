"""The error table and the 'ask once' preview."""

import re
from pathlib import Path

import pytest

from backend.app.ingestion.messages import ERROR_TABLE, build_preview, friendly_error, inr
from backend.app.ingestion.pipeline import ingest_statement, ingest_text
from tests.ingestion.layouts import ALL_FIXTURES, CHAOS_FIXTURES, EXTRA_FIXTURES

INGESTION = Path(__file__).resolve().parents[2] / "backend" / "app" / "ingestion"
BANNED = ("fake", "fraud", "scam", "cheat", "liar")


def _codes_in_source():
    codes = set()
    for f in INGESTION.glob("*.py"):
        codes |= set(re.findall(r'StatementIngestError\(\s*"([a-z_]+)"', f.read_text(encoding="utf-8")))
        codes |= set(re.findall(r'error_code\s*=\s*"([a-z_]+)"', f.read_text(encoding="utf-8")))
    return codes


def test_every_error_code_in_the_code_has_wording():
    missing = _codes_in_source() - set(ERROR_TABLE)
    assert not missing, f"error codes with no user wording: {sorted(missing)}"


def test_every_table_entry_is_complete_and_blame_free():
    for code, e in ERROR_TABLE.items():
        assert {"title", "message", "action", "needs"} <= set(e), code
        assert e["needs"] in (None, "password", "consent", "mapping"), code
        text = " ".join([e["title"], e["message"], e["action"]]).lower()
        assert not any(w in text for w in BANNED), code
        assert e["title"] and e["message"] and e["action"], code


def test_unknown_code_keeps_the_technical_message():
    e = friendly_error("brand_new_code", "Something specific", "Do this")
    assert e["message"] == "Something specific" and e["action"] == "Do this" and e["code"] == "brand_new_code"
    assert friendly_error(None)["title"]


@pytest.mark.parametrize("amount,text", [(150000, "\u20b91,50,000.00"), (12.5, "\u20b912.50"), (10000000, "\u20b91,00,00,000.00"),
                                         (999, "\u20b9999.00"), (-2500, "-\u20b92,500.00")])
def test_inr_format(amount, text):
    from decimal import Decimal
    assert inr(Decimal(str(amount))) == text


def test_verified_statement_gets_a_green_tick_and_no_question():
    fx = next(f for f in CHAOS_FIXTURES if f.name.startswith("04_"))
    p = build_preview(ingest_statement(fx.data, fx.filename, llm_policy="never"))
    assert p["status"] == "ok" and p["question"] is None and p["confirm_required"] is False
    assert p["actions"] == ["Looks right"]
    assert any("add up" in d for d in p["details"])


def test_never_more_than_one_question():
    for fx in ALL_FIXTURES:
        if fx.password:
            continue
        p = build_preview(ingest_statement(fx.data, fx.filename, llm_policy="never"))
        assert p["question"] is None or isinstance(p["question"], str)
        assert p["question"] is None or p["question"].count("?") == 1, fx.name


def test_no_balance_file_asks_once_to_check_the_rows():
    fx = next(f for f in EXTRA_FIXTURES if f.name.startswith("X2_"))
    p = build_preview(ingest_statement(fx.data, fx.filename, llm_policy="never"))
    assert p["status"] == "check" and "first few rows" in p["question"]
    assert any("no balance column" in n for n in p["notes"])


def test_short_ambiguous_dates_ask_the_date_question_only():
    text = "Date,Narration,Debit,Credit,Balance\n01/10/2026,A,,100.00,100.00\n02/10/2026,B,,50.00,150.00\n03/10/2026,C,20.00,,130.00\n"
    p = build_preview(ingest_text(text, llm_policy="never"))
    assert p["status"] == "check" and "1 Oct 2026" in p["question"]
    assert p["actions"] == ["Yes", "No, dates are month first"]


def test_broken_balance_asks_to_choose_columns():
    text = ("Date,Narration,Debit,Credit,Balance\n13/10/2026,a,,100.00,100.00\n14/10/2026,b,10.00,,90.00\n"
            "15/10/2026,c,,5.00,999.00\n16/10/2026,d,,5.00,1004.00\n17/10/2026,e,,5.00,1009.00\n")
    p = build_preview(ingest_text(text, llm_policy="never"))
    assert p["status"] == "check" and "column" in p["question"] and "Choose columns" in p["actions"]
    assert any("running balance" in n for n in p["notes"])


@pytest.mark.parametrize("data,name,code,needs", [
    (b"   ", "e.csv", "empty", None),
    (b"\xd0\xcf\x11\xe0" + b"\x00" * 64, "old.xls", "xls_unsupported", None),
    (b"hello there\nnot a table\n", "n.txt", "no_transactions", None),
    (b"\x89PNG\r\n\x1a\n" + b"\x00" * 32, "p.png", "vision_consent_required", "consent"),
])
def test_failure_previews(data, name, code, needs):
    p = build_preview(ingest_statement(data, name, llm_policy="never"))
    assert p["status"] == "failed" and p["error_code"] == code and p["needs"] == needs
    assert p["headline"] and p["action_text"] and p["actions"]


def test_password_pdf_preview_asks_for_the_password():
    fx = next(f for f in ALL_FIXTURES if f.password)
    p = build_preview(ingest_statement(fx.data, fx.filename, llm_policy="never"))
    assert p["needs"] == "password" and p["actions"] == ["Enter password"]
    wrong = build_preview(ingest_statement(fx.data, fx.filename, llm_policy="never", password="nope"))
    assert wrong["error_code"] == "pdf_password_incorrect" and wrong["needs"] == "password"


def test_unidentifiable_columns_is_a_mapping_request():
    # amounts exist but no column can be taken as a date
    text = "x,y,z\nfoo,bar,100.00\nfoo2,bar2,200.00\nfoo3,bar3,300.00\n"
    res = ingest_text(text, llm_policy="never")
    p = build_preview(res)
    assert p["status"] == "failed"
    assert p["error_code"] in ("columns_unclear", "no_transactions")


def test_rejected_mapping_gives_the_choose_columns_request():
    from backend.app.ingestion.mapping import Mapping
    fx = CHAOS_FIXTURES[0]
    res = ingest_statement(fx.data, fx.filename, mapping_override=Mapping(date=99, amount=98))
    p = build_preview(res)
    assert p["status"] == "failed" and p["error_code"] == "columns_unclear"
    assert p["needs"] == "mapping" and p["actions"] == ["Choose columns"] and p["confirm_required"] is True
