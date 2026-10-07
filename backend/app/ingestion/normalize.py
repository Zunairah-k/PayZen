"""Turn messy statement cell text into clean values.

Everything here is deterministic and side-effect free. Money is parsed to
``Decimal`` rounded to 2 places (INR statements are always 2-decimal).

Main entry points
-----------------
parse_amount(text)            -> AmountParse(value, marker, status)
parse_datetime_cell(text, o)  -> (datetime | None, has_time)
parse_time_cell(text)         -> datetime.time | None
detect_date_order(values)     -> ("dmy" | "mdy", "certain" | "assumed" | "conflict")
mask_cell(text)               -> shape-preserving mask used before any LLM call
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, List, Optional, Tuple

TWO_PLACES = Decimal("0.01")

# --------------------------------------------------------------------------
# Generic cell helpers
# --------------------------------------------------------------------------


def clean_cell(text: object) -> str:
    """Collapse whitespace (including newlines / non-breaking spaces)."""
    if text is None:
        return ""
    return " ".join(str(text).replace("\u00a0", " ").split())


def header_tokens(text: object) -> List[str]:
    """'Withdrawal Amt.' -> ['withdrawal', 'amt']  (lowercase alphanumeric words)."""
    return re.findall(r"[a-z0-9]+", clean_cell(text).lower())


# --------------------------------------------------------------------------
# Amounts
# --------------------------------------------------------------------------

_EMPTY_TOKENS = {"", "-", "--", "---", "\u2014", "\u2013", "nil", "na", "n/a", "null", "none", "."}
_CURRENCY_RE = re.compile(r"(?i)(?:rs\.?|inr|\u20b9|us\$|usd|\$|eur|\u20ac|\u00a3|gbp)")
_SUFFIX_MARK_RE = re.compile(r"(?i)(?<=[\d\s.)])(dr|cr|d|c)\.?\s*$")
_PREFIX_MARK_RE = re.compile(r"(?i)^\s*(dr|cr)\.?[\s:]+")
_NUM_RE = re.compile(r"^(?:\d+(?:\.\d+)?|\.\d+)$")

_DR_WORDS = {"dr", "debit", "debited", "d", "db", "withdrawal", "w", "out", "paid", "sent"}
_CR_WORDS = {"cr", "credit", "credited", "c", "cred", "deposit", "dep", "in", "received"}


@dataclass(frozen=True)
class AmountParse:
    value: Optional[Decimal]
    marker: Optional[str]  # 'dr' | 'cr' | None  (from a Dr/Cr word next to the number)
    status: str  # 'ok' | 'empty' | 'invalid'


def marker_from_word(text: object) -> Optional[str]:
    """Map words like 'DEBIT', 'Cr', 'D' to 'dr' / 'cr'. Unknown -> None."""
    word = clean_cell(text).lower().strip(".:/ ")
    if word in _DR_WORDS:
        return "dr"
    if word in _CR_WORDS:
        return "cr"
    return None


def _normalise_separators(s: str) -> str:
    """Resolve thousands vs decimal separators.

    '1,50,000.00' -> '150000.00'    (Indian grouping)
    '1.234,56'    -> '1234.56'      (European: last separator is the decimal)
    '1234,56'     -> '1234.56'      (single comma + 1-2 digits = decimal comma)
    '1,500'       -> '1500'         (single comma + 3 digits = thousands)
    """
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            return s.replace(".", "").replace(",", ".")
        return s.replace(",", "")
    if "," in s:
        head, _, tail = s.rpartition(",")
        if s.count(",") == 1 and len(tail) in (1, 2):
            return f"{head}.{tail}"
        return s.replace(",", "")
    if s.count(".") > 1:
        return s.replace(".", "")
    return s


def parse_amount(text: object) -> AmountParse:
    """Parse a money cell.

    Handles currency symbols (Rs., INR, rupee sign), Indian grouping,
    brackets / trailing minus / leading minus as negatives, and a Dr/Cr
    marker before or after the number (returned separately, NOT applied to
    the sign - the caller decides what the marker means).
    """
    if text is None:
        return AmountParse(None, None, "empty")
    s = str(text).replace("\u00a0", " ").replace("\u2212", "-").strip()
    if s.lower() in _EMPTY_TOKENS:
        return AmountParse(None, None, "empty")

    marker: Optional[str] = None
    m = _SUFFIX_MARK_RE.search(s)
    if m:
        marker = "dr" if m.group(1).lower() in ("dr", "d") else "cr"
        s = s[: m.start()].strip()
    else:
        m = _PREFIX_MARK_RE.match(s)
        if m:
            marker = "dr" if m.group(1).lower() == "dr" else "cr"
            s = s[m.end():].strip()

    s = _CURRENCY_RE.sub("", s).strip()
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1].strip()
    if s.endswith("-"):
        negative = True
        s = s[:-1].strip()
    if s.startswith("-"):
        negative = True
        s = s[1:].strip()
    elif s.startswith("+"):
        s = s[1:].strip()
    s = s.replace(" ", "")
    if not s:
        return AmountParse(None, marker, "empty")

    s = _normalise_separators(s)
    if not _NUM_RE.match(s):
        return AmountParse(None, marker, "invalid")
    value = Decimal(s).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    return AmountParse(-value if negative else value, marker, "ok")


def parse_balance(text: object) -> AmountParse:
    """Like parse_amount, but a 'Dr' marker means an overdrawn (negative) balance."""
    p = parse_amount(text)
    if p.value is not None and p.marker == "dr":
        return AmountParse(-abs(p.value), p.marker, p.status)
    return p


def is_amount_like(text: object) -> bool:
    """True for things that look like a money amount (not a 12-digit reference)."""
    raw = clean_cell(text)
    if not raw:
        return False
    p = parse_amount(raw)
    if p.status != "ok":
        return False
    digits = re.sub(r"\D", "", raw)
    if "." not in raw and "," not in raw and len(digits) > 9:
        return False  # long bare integers are references / account numbers
    return True


# --------------------------------------------------------------------------
# Dates and times
# --------------------------------------------------------------------------

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_TIME_TAIL_RE = re.compile(
    r"(?:^|[\s,]|(?<=\d)T)(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?\s*([AaPp]\.?[Mm]\.?)?"
    r"\s*(?:Z|UTC|IST|[+-]\d{2}:?\d{2})?$"
)
_TIME_ONLY_RE = re.compile(
    r"^(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?\s*([AaPp]\.?[Mm]\.?)?\s*(?:Z|UTC|IST|[+-]\d{2}:?\d{2})?$"
)
_NUM_DATE_RE = re.compile(r"^(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{2,4})$")
_NAME_DATE_DMY_RE = re.compile(
    r"^(\d{1,2})(?:st|nd|rd|th)?[\s\-/.,]*([A-Za-z]{3,9})\.?[\s\-/.,]*(\d{2,4})$"
)
_NAME_DATE_MDY_RE = re.compile(
    r"^([A-Za-z]{3,9})\.?[\s\-/.]*(\d{1,2})(?:st|nd|rd|th)?,?[\s\-/.]*(\d{4})$"
)
_COMPACT_DATE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$|^(\d{2})(\d{2})(\d{4})$")


def _year(y: int, width: int) -> int:
    if width <= 2:
        return 2000 + y if y <= 69 else 1900 + y
    return y


def _mk_date(y: int, m: int, d: int) -> Optional[dt.date]:
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def _mk_time(hour: int, minute: int, second: int, ampm: Optional[str]) -> Optional[dt.time]:
    if ampm:
        pm = ampm.lower().startswith("p")
        if not 1 <= hour <= 12:
            return None
        hour = (hour % 12) + (12 if pm else 0)
    try:
        return dt.time(hour, minute, second)
    except ValueError:
        return None


def _split_time(text: str) -> Tuple[str, Optional[dt.time]]:
    m = _TIME_TAIL_RE.search(text)
    if not m:
        return text, None
    t = _mk_time(int(m.group(1)), int(m.group(2)), int(m.group(3) or 0), m.group(4))
    if t is None:
        return text, None
    return text[: m.start()].strip(" ,T"), t


def _parse_date_part(text: str, order: str) -> Optional[dt.date]:
    s = text.strip()
    m = _NUM_DATE_RE.match(s)
    if m:
        a, b, c = m.group(1), m.group(2), m.group(3)
        if len(a) == 4:  # yyyy-mm-dd
            return _mk_date(int(a), int(b), int(c))
        if len(c) == 3:
            return None
        year = _year(int(c), len(c))
        if order == "mdy":
            return _mk_date(year, int(a), int(b))
        return _mk_date(year, int(b), int(a))
    m = _NAME_DATE_DMY_RE.match(s)
    if m and m.group(2).lower() in _MONTHS:
        return _mk_date(_year(int(m.group(3)), len(m.group(3))), _MONTHS[m.group(2).lower()], int(m.group(1)))
    m = _NAME_DATE_MDY_RE.match(s)
    if m and m.group(1).lower() in _MONTHS:
        return _mk_date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
    m = _COMPACT_DATE_RE.match(s)
    if m:
        if m.group(1):
            return _mk_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return _mk_date(int(m.group(6)), int(m.group(5)), int(m.group(4)))
    return None


def parse_datetime_cell(text: object, order: str = "dmy") -> Tuple[Optional[dt.datetime], bool]:
    """Parse a date (optionally with a time) cell.

    Returns (datetime or None, has_time). When the cell has no time the
    datetime is midnight and has_time is False. ``order`` ('dmy' or 'mdy')
    only matters for all-numeric dates like 06/10/2026; ISO (2026-10-06) and
    month-name dates are unambiguous.
    """
    s = clean_cell(text)
    if not s:
        return None, False
    date_text, t = _split_time(s)
    d = _parse_date_part(date_text, order)
    if d is None:
        return None, False
    if t is None:
        return dt.datetime.combine(d, dt.time(0, 0)), False
    return dt.datetime.combine(d, t), True


def parse_time_cell(text: object) -> Optional[dt.time]:
    """Parse a time-of-day cell ('14:32', '2:32:10 PM', or a full datetime)."""
    s = clean_cell(text)
    if not s:
        return None
    m = _TIME_ONLY_RE.match(s)
    if m:
        return _mk_time(int(m.group(1)), int(m.group(2)), int(m.group(3) or 0), m.group(4))
    parsed, has_time = parse_datetime_cell(s)
    if parsed is not None and has_time:
        return parsed.time()
    return None


def is_date_like(text: object) -> bool:
    s = clean_cell(text)
    if not s:
        return False
    return parse_datetime_cell(s, "dmy")[0] is not None or parse_datetime_cell(s, "mdy")[0] is not None


def is_time_like(text: object) -> bool:
    s = clean_cell(text)
    return bool(s) and bool(_TIME_ONLY_RE.match(s)) and parse_time_cell(s) is not None


def detect_date_order(values: Iterable[object]) -> Tuple[str, str]:
    """Decide DD/MM vs MM/DD from the evidence in a whole date column.

    A first part above 12 proves day-first; a second part above 12 proves
    month-first. With no evidence we assume day-first (Indian statements) and
    say so: status is 'assumed'. Contradictory evidence gives 'conflict'.
    """
    dmy = mdy = 0
    for v in values:
        s = clean_cell(v)
        if not s:
            continue
        date_text, _ = _split_time(s)
        m = _NUM_DATE_RE.match(date_text)
        if not m or len(m.group(1)) == 4:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 >= b:
            dmy += 1
        elif b > 12 >= a:
            mdy += 1
    if dmy and mdy:
        return "dmy", "conflict"
    if mdy:
        return "mdy", "certain"
    if dmy:
        return "dmy", "certain"
    return "dmy", "assumed"


# --------------------------------------------------------------------------
# Masking (privacy) - used before sending anything to a language model
# --------------------------------------------------------------------------

_SAFE_TOKENS = {
    "dr", "cr", "db", "debit", "credit", "d", "c", "upi", "imps", "neft", "rtgs",
    "ach", "nach", "atm", "pos", "ecs", "chq", "ref", "utr", "rrn", "by", "to",
    "from", "transfer", "payment", "am", "pm", "nil", "na", "inr", "rs", "t",
    "z", "utc", "ist",
} | set(_MONTHS)

_MASK_TOKEN_RE = re.compile(r"[A-Za-z]+|\d|.", re.S)


def mask_cell(text: object) -> str:
    """Keep the SHAPE of a cell but hide the content.

    digits -> '9', letters -> 'x'/'X' (except structural words such as Dr, Cr,
    UPI, month names). '1,50,000.00' -> '9,99,999.99'; 'Rahul Sharma' ->
    'Xxxxx Xxxxxx'. Layout, number style, and Dr/Cr markers survive; amounts,
    names and reference numbers do not.
    """
    out: List[str] = []
    for tok in _MASK_TOKEN_RE.findall(clean_cell(text)):
        if tok.isdigit():
            out.append("9")
        elif tok[0].isalpha():
            if tok.lower() in _SAFE_TOKENS:
                out.append(tok)
            else:
                out.append("".join("X" if ch.isupper() else "x" for ch in tok))
        else:
            out.append(tok)
    return "".join(out)