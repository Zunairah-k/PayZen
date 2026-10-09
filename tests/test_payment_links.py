from decimal import Decimal

from backend.app.ingestion.models import StatementRow
from backend.app.payment_links import find_tag, make_upi_link, new_tag, reconcile_by_tag
import datetime as dt


def _row(i, narration, credit):
    return StatementRow(row_id=f"S{i}", datetime=dt.datetime(2026, 10, 9, 10, 0), narration=narration,
                        credit=Decimal(credit))


def test_link_and_tag():
    tag = new_tag()
    link = make_upi_link("fest@examplebank", "Fest Society", 500, tag)
    assert link.startswith("upi://pay?pa=fest@examplebank") and f"tn={tag}" in link and "am=500.00" in link
    assert find_tag(f"UPI/123456789012/Ayesha/{tag.lower()}/Fest") == tag


def test_reconcile_by_tag():
    rows = [_row(1, "UPI/111/Ayesha/PZ-AAAAAA/x", "500.00"), _row(2, "UPI/222/Rahul/PZ-BBBBBB/x", "50.00")]
    issued = [{"tag": "PZ-AAAAAA", "amount": 500, "payer": "Ayesha"},
              {"tag": "PZ-BBBBBB", "amount": 500, "payer": "Rahul"},
              {"tag": "PZ-CCCCCC", "amount": 500, "payer": "Divya"}]
    status = [r["status"] for r in reconcile_by_tag(rows, issued)]
    assert status == ["paid", "amount_differs", "not_found_yet"]