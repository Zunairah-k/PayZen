"""Extra date and number edge cases for the value parsers.

Each case documents a deliberate decision: what we accept, what we refuse, and
why. If one of these fails after a change, a real statement format may break.
"""

import datetime as dt
from decimal import Decimal

import pytest

from backend.app.ingestion.pipeline import ingest_text
from backend.app.ingestion.normalize import (
    detect_date_order, parse_amount, parse_balance, parse_datetime_cell, parse_time_cell,
)

D = dt.datetime


# ---------------------------------------------------------------- numbers --------------------


@pytest.mark.parametrize("text,value", [
    ("Rs. 500/-", "500.00"),                 # Indian "rupees only" suffix is NOT a minus sign
    ("500/-", "500.00"),
    ("Rs.1,500.00/-", "1500.00"),
    ("(Rs. 500/-)", "-500.00"),              # brackets still mean negative
    ("-500/-", "-500.00"),
    ("1,00,00,000.00", "10000000.00"),       # one crore, Indian grouping
    ("12,34,567.89", "1234567.89"),
    ("12,345,678.00", "12345678.00"),        # western grouping also fine
    ("1 234,56", "1234.56"),                 # space thousands + decimal comma
    ("1.234,56", "1234.56"),                 # European
    ("12,34", "12.34"),                      # single comma + two digits = decimal comma
    (".50", "0.50"),
    ("0.005", "0.01"),                       # rounds half up to paise
    ("0.004", "0.00"),
    ("\u2212300", "-300.00"),                # real unicode minus sign
    ("\u20b9 1,234.56 CR", "1234.56"),
    ("USD 1,000", "1000.00"),
    ("-0.00", "0.00"),
    ("123456789012.00", "123456789012.00"),  # a big amount is still an amount when it has decimals
])
def test_amount_accepted(text, value):
    p = parse_amount(text)
    assert p.status == "ok" and p.value == Decimal(value)


@pytest.mark.parametrize("text", [
    "1,2,3",          # commas that are not real grouping are never guessed into a number
    "1,234,56",
    "1,5000",
    "1e5",            # scientific notation is not money in a statement
    "NaN",
    "inf",
    "--50",
    "500.00*",
    "12abc",
    "06/10/2026",     # a date is not an amount
    "14:32",
])
def test_amount_refused(text):
    assert parse_amount(text).status == "invalid"


def test_dr_cr_marker_is_reported_not_applied():
    p = parse_amount("500.00 Cr.")
    assert p.value == Decimal("500.00") and p.marker == "cr"
    assert parse_balance("2,000.00 Dr").value == Decimal("-2000.00")


def test_malformed_grouping_row_is_reported_as_unreadable_not_silently_wrong():
    text = ("Date,Narration,Debit,Credit,Balance\n"
            "13/10/2026,a,,100.00,100.00\n"
            "14/10/2026,b,1,2,3,,90.00\n"       # breaks the column count AND is not an amount
            "15/10/2026,c,,5.00,95.00\n")
    res = ingest_text(text, llm_policy="never")
    assert res.ok
    assert all(r.credit != Decimal("123") and r.debit != Decimal("123") for r in res.rows)


# ---------------------------------------------------------------- dates ----------------------


@pytest.mark.parametrize("text,expected", [
    ("29/02/2028", D(2028, 2, 29)),          # leap day exists
    ("06.10.2026", D(2026, 10, 6)),          # dots
    ("06-OCT-2026", D(2026, 10, 6)),         # shouty bank export
    ("6th Oct 2026", D(2026, 10, 6)),
    ("06 Sept 2026", D(2026, 9, 6)),         # 'Sept' as well as 'Sep'
    ("Oct 06, 2026", D(2026, 10, 6)),        # payment-app style
    ("2026/10/06", D(2026, 10, 6)),
    ("6/1/2026", D(2026, 1, 6)),             # no zero padding, day first
    ("Tue, 06 Oct 2026", D(2026, 10, 6)),    # weekday prefix is ignored
    ("Monday 06/10/2026 14:30", D(2026, 10, 6, 14, 30)),
    ("06/10/2026 12:00 AM", D(2026, 10, 6, 0, 0)),
    ("06/10/2026 12:30 PM", D(2026, 10, 6, 12, 30)),
    ("06/10/2026 1:05 pm", D(2026, 10, 6, 13, 5)),
    ("2026-10-06T14:32:10+05:30", D(2026, 10, 6, 14, 32, 10)),   # offset ignored: kept as local time
    ("20261006", D(2026, 10, 6)),
])
def test_date_accepted(text, expected):
    assert parse_datetime_cell(text, "dmy")[0] == expected


@pytest.mark.parametrize("text", [
    "29/02/2026",     # not a leap year
    "31/04/2026",     # April has 30 days
    "00/10/2026",
    "06/00/2026",
    "06/10/20266",
    "06/10/2026 24:00",
    "06/10/2026 13:00 PM",
    "Total",
    "Opening Balance",
    "Page 1 of 3",
])
def test_date_refused(text):
    assert parse_datetime_cell(text, "dmy")[0] is None


def test_two_digit_year_pivot_is_documented():
    assert parse_datetime_cell("01/01/69")[0] == D(2069, 1, 1)
    assert parse_datetime_cell("01/01/70")[0] == D(1970, 1, 1)


def test_midnight_with_a_time_still_counts_as_having_a_time():
    assert parse_datetime_cell("06/10/2026 00:00:00") == (D(2026, 10, 6), True)


def test_time_cells():
    assert parse_time_cell("12:05:09 AM") == dt.time(0, 5, 9)
    assert parse_time_cell("23:59:59") == dt.time(23, 59, 59)
    assert parse_time_cell("25:00") is None


@pytest.mark.parametrize("values,order,status", [
    (["13/10/2026", "01/10/2026"], "dmy", "certain"),
    (["10/13/2026", "10/01/2026"], "mdy", "certain"),
    (["01/10/2026", "02/10/2026"], "dmy", "assumed"),        # ambiguous: assume day first, say so
    (["13/10/2026", "10/13/2026"], "dmy", "conflict"),
    (["2026-10-13", "2026-10-01"], "dmy", "certain"),        # ISO is unambiguous: nothing to assume
    (["06-Oct-2026"], "dmy", "certain"),                     # month names are unambiguous
    ([], "dmy", "assumed"),
])
def test_date_order(values, order, status):
    assert detect_date_order(values) == (order, status)


def test_month_first_statement_end_to_end():
    text = "Date,Description,Amount,Balance\n10/13/2026,a,100.00,100.00\n10/14/2026,b,-20.00,80.00\n10/15/2026,c,5.00,85.00\n"
    res = ingest_text(text, llm_policy="never")
    assert res.ok and res.rows[0].datetime == D(2026, 10, 13)
    assert res.report.date_order == "mdy" and res.report.date_order_status == "certain"


def test_ambiguous_short_statement_asks_about_dates():
    text = "Date,Narration,Debit,Credit,Balance\n01/10/2026,A,,100.00,100.00\n02/10/2026,B,,50.00,150.00\n03/10/2026,C,20.00,,130.00\n"
    res = ingest_text(text, llm_policy="never")
    assert res.report.date_order_status == "assumed"
    assert any("ambiguous" in w for w in res.meta.warnings)


def test_rupees_only_suffix_statement_end_to_end():
    text = "Date,Narration,Debit,Credit,Balance\n13/10/2026,a,,Rs. 100/-,Rs. 100/-\n14/10/2026,b,Rs. 30/-,,Rs. 70/-\n15/10/2026,c,,Rs. 5/-,Rs. 75/-\n"
    res = ingest_text(text, llm_policy="never")
    assert res.ok and [r.credit for r in res.rows] == [Decimal("100.00"), None, Decimal("5.00")]
    assert res.report.chain["status"] == "pass"
