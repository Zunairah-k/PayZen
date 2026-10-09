"""Loader tests: decoding, delimiter detection, header detection, spacer columns."""
import pytest

from backend.app.ingestion.loader import StatementIngestError
from backend.app.ingestion.pipeline import ingest_statement
from backend.app.ingestion.loader import detect_header, load_statement, load_text

BASIC = "Date,Narration,Debit,Credit,Balance\n01/10/2026,UPI/123456789012/A B,,100.00,100.00\n02/10/2026,x,10.00,,90.00\n"


def test_utf8_bom_crlf_and_blank_lines():
    data = ("\ufeff" + BASIC.replace("\n", "\r\n") + "\r\n\r\n").encode("utf-8")
    t = load_statement(data, "a.csv")
    assert t.encoding == "utf-8-sig" and t.delimiter == "," and len(t.rows) == 3


def test_utf16_with_bom():
    t = load_statement(BASIC.encode("utf-16"), "a.csv")
    assert t.encoding == "utf-16" and len(t.rows) == 3


def test_cp1252_is_decoded():
    t = load_statement("Date;Narration;Debit;Credit;Balance\n01/10/2026;Jos\u00e9;;1,00;1,00\n".encode("cp1252"), "a.csv")
    assert "Jos\u00e9" in t.rows[1][1] and t.delimiter == ";"


@pytest.mark.parametrize("delim", [",", ";", "\t", "|"])
def test_delimiters(delim):
    t = load_text(BASIC.replace(",", delim) if delim != "," else BASIC)
    assert t.delimiter == delim and len(t.rows[0]) == 5


def test_excel_sep_directive_line():
    t = load_text("sep=;\n" + BASIC.replace(",", ";"))
    assert t.delimiter == ";" and t.rows[0][0] == "Date"


def test_quoted_multiline_narration_is_one_cell():
    text = 'Date,Narration,Debit,Credit,Balance\n01/10/2026,"UPI/123456789012/A\nB, extra",,100.00,100.00\n'
    t = load_text(text)
    assert len(t.rows) == 2 and "A B, extra" in t.rows[1][1]


def test_blank_spacer_columns_are_dropped():
    t = load_text("Date,,Narration,,Debit,Credit,Balance\n01/10/2026,,x,,,100.00,100.00\n")
    assert len(t.rows[0]) == 5


def test_line_numbers_are_original_lines():
    t = load_text("Bank\n\nAccount: 1\nDate,Narration,Debit,Credit,Balance\n01/10/2026,x,,100.00,100.00\n")
    h = detect_header(t)
    assert h.line == 4 and t.line_numbers[h.data_start] == 5


def test_header_found_below_junk_and_not_mistaken_for_data():
    t = load_text("Sample Bank\nStatement period: 01/10/2026 to 31/10/2026\nAddress, Hyderabad, India\n" + BASIC)
    h = detect_header(t)
    assert h.names[0] == "Date" and not h.synthesized


def test_header_without_any_data_is_an_error():
    with pytest.raises(StatementIngestError) as e:
        detect_header(load_text("just,some,words\nand,more,words\n"))
    assert e.value.code == "no_transactions"


def test_too_many_rows_message():
    import backend.app.ingestion.loader as L
    old = L.MAX_ROWS
    L.MAX_ROWS = 3
    try:
        res = ingest_statement(("Date,N,D,C,B\n" + "01/10/2026,x,,1.00,1.00\n" * 10).encode(), "a.csv", llm_policy="never")
        assert res.ok is False and "rows" in res.report.user_message.lower()
    finally:
        L.MAX_ROWS = old


def test_corrupt_xlsx_fails_politely():
    res = ingest_statement(b"PK\x03\x04 not really a workbook", "a.xlsx", llm_policy="never")
    assert res.ok is False and "excel" in res.report.user_message.lower()


def test_repeated_header_row_is_skipped_and_first_row_kept():
    text = ("Date,Narration,Debit,Credit,Balance\n01/10/2026,a,,100.00,100.00\n"
            "Date,Narration,Debit,Credit,Balance\n02/10/2026,b,10.00,,90.00\n03/10/2026,c,,5.00,95.00\n")
    res = ingest_statement(text.encode(), "a.csv", llm_policy="never")
    assert res.ok and len(res.rows) == 3 and res.report.header_line == 1
    assert any(s["reason"] == "repeated header row" for s in res.report.skipped_samples)
    assert res.meta.balance_chain_result["status"] == "pass"
