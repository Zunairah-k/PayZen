"""Apply a column mapping to raw rows and produce clean transactions.

This is the deterministic half of "the model proposes, the math verifies":
given a Mapping it parses every row the same way, and records exactly what it
skipped and why, so the parse report can explain itself.

Row classes
-----------
transaction   has a parseable date AND at least one amount
continuation  no date, no amounts, no balance, only narration text ->
              stitched onto the previous transaction (wrapped narrations)
opening       a balance-only row labelled "Opening balance" / "B/F"
              -> used as the starting point of the balance chain
skipped       everything else (junk header lines, footers, totals, page text,
              repeated headers) - counted and sampled in the report
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional, Sequence, Tuple

from .mapping import Mapping
from .normalize import (
    clean_cell,
    detect_date_order,
    header_tokens,
    marker_from_word,
    parse_amount,
    parse_balance,
    parse_datetime_cell,
    parse_time_cell,
)

_OPENING_RE = re.compile(r"(?i)\b(opening\s+balance|balance\s+b/?f|brought\s+forward|b/f|balance\s+forward)\b")
_FOOTER_END_RE = re.compile(
    r"(?i)\b(total|grand\s+total|closing\s+balance|statement\s+summary|end\s+of\s+statement|"
    r"carried\s+forward|c/f)\b|\*{3,}"
)
_FOOTER_TEXT_RE = re.compile(
    r"(?i)(computer\s+generated|page\s+\d+\s+(of|/)\s+\d+|generated\s+on|this\s+is\s+a\s+system|"
    r"registered\s+office|toll\s+free|customer\s+care|disclaimer|please\s+examine)"
)


@dataclass
class ParsedRow:
    line: int  # original line / sheet row of the first line of this transaction
    dt: dt.datetime
    has_time: bool
    narration: str
    debit: Optional[Decimal]
    credit: Optional[Decimal]
    balance: Optional[Decimal]
    ref_text: str = ""  # text of a dedicated reference column, if mapped


@dataclass
class ParseOutput:
    rows: List[ParsedRow] = field(default_factory=list)  # in FILE order
    opening_balance: Optional[Decimal] = None
    skipped: List[Tuple[int, str]] = field(default_factory=list)  # (line, reason)
    lost: List[Tuple[int, str]] = field(default_factory=list)  # data-looking rows we could NOT use
    stitched: int = 0
    date_order: str = "dmy"
    date_order_status: str = "assumed"

    @property
    def parse_rate(self) -> float:
        total = len(self.rows) + len(self.lost)
        return len(self.rows) / total if total else 0.0


def _join_wrapped(prev: str, cont: str) -> str:
    """Join a wrapped narration. A break between two digits is almost always a
    split inside one number (a 12-digit reference), so no space is inserted."""
    if prev and cont and prev[-1].isdigit() and cont[0].isdigit():
        return prev + cont
    return f"{prev} {cont}".strip()


def _cell(cells: Sequence[str], idx: Optional[int]) -> str:
    return cells[idx] if idx is not None and 0 <= idx < len(cells) else ""


def parse_rows(
    data_rows: Sequence[Tuple[int, Sequence[str]]],
    mapping: Mapping,
    header_names: Optional[Sequence[str]] = None,
) -> ParseOutput:
    """Parse ``(line_number, cells)`` pairs using ``mapping``."""
    out = ParseOutput()
    if mapping.date is None:
        return out

    out.date_order, out.date_order_status = detect_date_order(_cell(c, mapping.date) for _, c in data_rows)
    header_norm = [tuple(header_tokens(h)) for h in (header_names or [])]
    footer_started = False
    last: Optional[ParsedRow] = None

    for line, cells in data_rows:
        narr_parts = [clean_cell(_cell(cells, i)) for i in mapping.narration]
        narration = " ".join(p for p in narr_parts if p)
        row_text = " ".join(c for c in cells if c)
        if not row_text:
            continue

        # a repeated header row (page break in a pasted table)
        if header_norm and tuple(tuple(header_tokens(c)) for c in cells) == tuple(header_norm):
            out.skipped.append((line, "repeated header row"))
            continue

        date_text = clean_cell(_cell(cells, mapping.date))
        dt_value, has_time = parse_datetime_cell(date_text, out.date_order) if date_text else (None, False)

        debit_p = parse_amount(_cell(cells, mapping.debit)) if mapping.debit is not None else None
        credit_p = parse_amount(_cell(cells, mapping.credit)) if mapping.credit is not None else None
        amount_p = parse_amount(_cell(cells, mapping.amount)) if mapping.amount is not None else None
        balance_p = parse_balance(_cell(cells, mapping.balance)) if mapping.balance is not None else None
        balance = balance_p.value if balance_p is not None else None

        has_amount = any(p is not None and p.value is not None for p in (debit_p, credit_p, amount_p))
        bad_amount = [p for p in (debit_p, credit_p, amount_p, balance_p) if p is not None and p.status == "invalid"]

        # opening balance anchor: balance-only row labelled opening / b/f
        if balance is not None and not has_amount and _OPENING_RE.search(row_text):
            if out.opening_balance is None:
                out.opening_balance = balance
            else:
                out.skipped.append((line, "extra opening-balance row"))
            continue

        if dt_value is None:
            if footer_started or _FOOTER_TEXT_RE.search(row_text):
                out.skipped.append((line, "footer text"))
                continue
            if _FOOTER_END_RE.search(row_text):
                footer_started = True
                out.skipped.append((line, "totals / footer row"))
                continue
            if narration and not has_amount and balance is None and last is not None:
                last.narration = _join_wrapped(last.narration, narration)
                if mapping.reference is not None and not last.ref_text:
                    last.ref_text = clean_cell(_cell(cells, mapping.reference))
                out.stitched += 1
                continue
            if has_amount:
                out.lost.append((line, f"amount present but date not understood: '{date_text[:30]}'"))
            else:
                out.skipped.append((line, "no date (header / title / junk line)"))
            continue

        # ---- dated row -----------------------------------------------------
        if mapping.time is not None:
            t = parse_time_cell(_cell(cells, mapping.time))
            if t is not None:
                dt_value = dt.datetime.combine(dt_value.date(), t)
                has_time = True

        if not has_amount:
            if bad_amount:
                out.lost.append((line, "amount cell not understood"))
            elif balance is not None and _FOOTER_END_RE.search(row_text):
                out.skipped.append((line, "closing balance row"))
            else:
                out.skipped.append((line, "dated row without an amount"))
            continue

        debit, credit = _resolve_direction(mapping, debit_p, credit_p, amount_p, cells)
        if mapping.swap_direction:
            debit, credit = credit, debit

        last = ParsedRow(
            line=line, dt=dt_value, has_time=has_time, narration=narration, debit=debit, credit=credit,
            balance=balance, ref_text=clean_cell(_cell(cells, mapping.reference)),
        )
        out.rows.append(last)
        footer_started = False

    return out


def _resolve_direction(mapping, debit_p, credit_p, amount_p, cells) -> Tuple[Optional[Decimal], Optional[Decimal]]:
    debit = abs(debit_p.value) if debit_p is not None and debit_p.value is not None else None
    credit = abs(credit_p.value) if credit_p is not None and credit_p.value is not None else None

    if amount_p is not None and amount_p.value is not None:
        direction = amount_p.marker
        if direction is None and mapping.direction_column is not None:
            direction = marker_from_word(_cell(cells, mapping.direction_column))
        if direction is None:
            direction = "dr" if amount_p.value < 0 else "cr"
        value = abs(amount_p.value)
        if direction == "dr":
            debit = value
        else:
            credit = value

    # "0.00" in the unused column of a two-column layout is not a real amount
    if debit == 0 and credit not in (None, Decimal("0.00")):
        debit = None
    if credit == 0 and debit not in (None, Decimal("0.00")):
        credit = None
    return debit, credit