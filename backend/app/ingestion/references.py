"""Pull the 12-digit UPI/IMPS reference and a payer-name hint out of a narration.

Banks write narrations in many shapes, so several patterns are tried from the
most to the least trustworthy. Each result carries a confidence label so the
matcher can refuse to give a "Verified" verdict on a shaky reference:

    high    labelled ("UTR: 123...", "RRN 123...") or right after UPI/IMPS/NEFT/RTGS
    medium  a single bare 12-digit number, or several candidates after a keyword
    low     several different bare 12-digit numbers - the first is returned

12 digits is the UPI/IMPS reference length. Longer alphanumeric NEFT UTRs are
deliberately NOT returned (they are not 12-digit UPI references).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from .normalize import clean_cell

_LABELLED_RE = re.compile(
    r"(?i)\b(?:upi\s*ref(?:erence)?(?:\s*(?:no|num|number|id))?|rrn|utr(?:\s*(?:no|num|number))?"
    r"|ref(?:erence)?(?:\s*(?:no|num|number|id))?|txn\s*id|transaction\s*(?:id|ref(?:erence)?))"
    r"\b\s*[:#.\-/=]*\s*(?<!\d)(\d{12})(?!\d)"
)
_KEYWORD_RE = re.compile(r"(?i)\b(?:upi|imps|neft|rtgs)\b.{0,80}?(?<!\d)(\d{12})(?!\d)")
_BARE_RE = re.compile(r"(?<![0-9A-Za-z])(\d{12})(?![0-9A-Za-z])")


@dataclass(frozen=True)
class RefMatch:
    value: str
    confidence: str  # 'high' | 'medium' | 'low'
    source: str  # 'labelled' | 'keyword' | 'bare' | 'column'


def extract_reference(text: object) -> Optional[RefMatch]:
    """Best 12-digit reference found in ``text`` (or None)."""
    s = clean_cell(text)
    if not s:
        return None

    m = _LABELLED_RE.search(s)
    if m:
        return RefMatch(m.group(1), "high", "labelled")

    m = _KEYWORD_RE.search(s)
    if m:
        # several different 12-digit numbers in the same narration -> less sure
        others = {x for x in _BARE_RE.findall(s)} - {m.group(1)}
        return RefMatch(m.group(1), "medium" if others else "high", "keyword")

    bare = _BARE_RE.findall(s)
    if bare:
        distinct = list(dict.fromkeys(bare))
        return RefMatch(distinct[0], "medium" if len(distinct) == 1 else "low", "bare")
    return None


# --------------------------------------------------------------------------
# Payer / payee name hint
# --------------------------------------------------------------------------

_STOP_WORDS = {
    "upi", "imps", "neft", "rtgs", "p2a", "p2p", "p2m", "payment", "pay", "paid", "transfer",
    "trf", "from", "to", "by", "cr", "dr", "ref", "utr", "rrn", "mob", "mobile", "banking",
    "netbanking", "ib", "ifsc", "account", "credit", "debit", "sent", "received", "collect",
    "fund", "funds", "txn", "transaction", "no", "number", "bank", "ltd", "limited", "chq",
    "cheque", "cash", "atm", "pos", "ach", "nach", "ecs", "fee", "fest", "registration",
}
_HANDLE_RE = re.compile(
    r"(?i)^(?:ok)?(?:sbi|hdfc|icici|axis|ybl|ibl|axl|paytm|apl|kotak|pnb|boi|bob|canara|union|"
    r"idfc|idfcfirst|yes|indus|upi|fbl|rbl|aubank|sbin|hdfcbank|icicibank)\w*$"
)
_SPLIT_RE = re.compile(r"[/|,;:\-\n]")
_TITLE_RE = re.compile(r"(?i)^(mr|mrs|ms|miss|shri|smt|dr|prof)\.?\s+")


def extract_name_hint(narration: object) -> Optional[str]:
    """Best-effort payer/payee name from a narration. A HINT only - the matcher
    compares names fuzzily and never relies on this for a Verified verdict."""
    s = clean_cell(narration)
    if not s:
        return None

    candidates: List[str] = []
    for seg in _SPLIT_RE.split(s):
        seg = clean_cell(seg)
        if not seg or "@" in seg:
            continue
        letters = re.sub(r"[^A-Za-z ]", " ", seg)
        words = [w for w in letters.split() if len(w) >= 2]
        if not words:
            continue
        if sum(ch.isdigit() for ch in seg) > 2:
            continue
        if all(w.lower() in _STOP_WORDS for w in words):
            continue
        if len(words) == 1 and _HANDLE_RE.match(words[0]):
            continue
        words = [w for w in words if w.lower() not in _STOP_WORDS] or words
        name = " ".join(words)
        name = _TITLE_RE.sub("", name).strip()
        if len(name) >= 3:
            candidates.append(name)

    if not candidates:
        return None
    pick = next((c for c in candidates if " " in c), candidates[0])
    return pick.title() if pick.isupper() or pick.islower() else pick