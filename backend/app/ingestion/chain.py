"""Balance-chain self-verification.

If the column mapping is right, every row obeys

    balance[i] = balance[i-1] + credit[i] - debit[i]

(oldest to newest). Real arithmetic over real data is very hard to satisfy by
accident, so a chain that holds across dozens of rows is strong evidence that
date order, debit/credit direction and the balance column were all read
correctly. A chain that breaks says exactly WHERE and usually WHY (swapped
debit/credit, a missing row), which feeds the retry and the preview.

Statements may be newest-first (app exports). ``choose_order`` tries both
directions and keeps the one the arithmetic supports.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

TOLERANCE = Decimal("0.01")
STATUS_RANK = {"pass": 3, "partial": 2, "unavailable": 1, "fail": 0}


@dataclass
class ChainResult:
    status: str  # 'pass' | 'partial' | 'fail' | 'unavailable'
    direction: str  # 'oldest_first' | 'newest_first' | 'unknown'
    checked: int
    passed: int
    pass_rate: float
    evidence: str  # 'strong' (>= 10 checks) | 'weak' | 'none'
    opening_used: bool
    first_break: Optional[Dict[str, Any]]
    note: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status, "direction": self.direction, "checked": self.checked,
            "passed": self.passed, "pass_rate": round(self.pass_rate, 4), "evidence": self.evidence,
            "opening_balance_used": self.opening_used, "first_break": self.first_break, "note": self.note,
        }


def _hint(prev: Decimal, row) -> str:
    credit = row.credit or Decimal("0")
    debit = row.debit or Decimal("0")
    if abs(prev + debit - credit - row.balance) <= TOLERANCE:
        return "debit and credit look swapped"
    if debit == 0 and credit == 0:
        return "balance changed but the row has no amount - a row may be missing or mis-read"
    delta = row.balance - prev
    if abs(delta) == debit or abs(delta) == credit:
        return "balance moved by the amount in the opposite direction - check sign / Dr-Cr handling"
    return "balance does not follow from the previous row - a row may be missing, duplicated or mis-read"


def check_chain(rows: Sequence[Any], opening: Optional[Decimal] = None, direction: str = "oldest_first") -> ChainResult:
    """Verify ``rows`` (already in chronological order). Rows need
    .debit .credit .balance and .line attributes."""
    prev: Optional[Decimal] = opening
    checked = passed = 0
    first_break: Optional[Dict[str, Any]] = None
    opening_used = False

    for idx, row in enumerate(rows, start=1):
        if row.balance is None:
            prev = None
            continue
        if prev is not None:
            expected = prev + (row.credit or Decimal("0")) - (row.debit or Decimal("0"))
            checked += 1
            if abs(expected - row.balance) <= TOLERANCE:
                passed += 1
            elif first_break is None:
                first_break = {
                    "row_number": idx, "source_line": row.line, "expected": str(expected),
                    "actual": str(row.balance), "difference": str(row.balance - expected),
                    "hint": _hint(prev, row),
                }
            if idx == 1 and opening is not None:
                opening_used = True
        prev = row.balance

    if checked == 0:
        return ChainResult("unavailable", direction, 0, 0, 0.0, "none", opening_used, None,
                           "No balance column to verify against.")
    rate = passed / checked
    status = "pass" if passed == checked else "partial" if rate >= 0.9 else "fail"
    evidence = "strong" if checked >= 10 else "weak"
    if status == "pass":
        note = f"Balance chain holds on all {checked} checked rows."
    else:
        note = f"Balance chain holds on {passed} of {checked} checked rows."
    return ChainResult(status, direction, checked, passed, rate, evidence, opening_used, first_break, note)


def _rank(res: ChainResult) -> Tuple[int, float, int]:
    return (STATUS_RANK[res.status], res.pass_rate, res.checked)


def choose_order(rows_in_file_order: Sequence[Any], opening: Optional[Decimal] = None) -> Tuple[List[Any], ChainResult]:
    """Return (rows in chronological order, chain result).

    Both file directions are verified; the one the arithmetic supports wins.
    With no balance evidence the date trend decides.
    """
    rows = list(rows_in_file_order)
    forward = check_chain(rows, opening, "oldest_first")
    backward = check_chain(list(reversed(rows)), opening, "newest_first")

    descending = len(rows) > 1 and rows[0].dt > rows[-1].dt
    if _rank(forward) > _rank(backward):
        pick_forward = True
    elif _rank(backward) > _rank(forward):
        pick_forward = False
    else:
        pick_forward = not descending

    if pick_forward:
        return rows, forward
    return list(reversed(rows)), backward


def describe_chain(res: ChainResult) -> str:
    if res.status == "pass":
        order = "newest first" if res.direction == "newest_first" else "oldest first"
        return f"Balance check passed on {res.passed}/{res.checked} rows (file is {order})."
    if res.status == "unavailable":
        return "No balance column, so the numbers could not be self-checked."
    if res.first_break:
        b = res.first_break
        return (f"Balance check passed on {res.passed}/{res.checked} rows; first break at line "
                f"{b['source_line']} (expected {b['expected']}, found {b['actual']}): {b['hint']}.")
    return res.note