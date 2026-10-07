"""PayZen — verification / matching engine (Alizah, Phase 2).

    match_claims(claims, statement_rows, statement_meta=None, config=None) -> List[Verdict]

Pure and deterministic: no I/O, no randomness, no ML. Same input => same
output, in the same order as ``claims``. See PHASE2_README.md for the full
rules; the short version:

1. Reference ladder (Tier 1 / Tier 4)
   exact 12-digit reference + equal amount (+ no conflicting field) -> Verified.
   exact reference but a conflicting field -> Contradicted (never "search for a
   convenient match" instead).
2. Soft ladder (Tier 2 / Tier 3), only for claims whose reference is NOT on any
   statement row: equal amount + time inside a window + payer identity
   evidence -> Likely match (Tier 2); amount + time only -> low-confidence
   Likely match (Tier 3). These tiers can NEVER produce Verified.
3. One-to-one: every candidate (claim, credit-row) edge gets a score; each
   connected component is solved as a maximum-weight assignment (Hungarian
   algorithm). A credit row is consumed by at most one claim.
4. Duplicates: shared reference, byte-identical file, or a corroborated
   perceptual-hash match link claims into groups; only one claim per group
   keeps its verdict, the rest become Duplicate. Evidence, not an accusation.
5. Coverage: no candidate => "Not found" only when the claim is safely inside
   the statement coverage; otherwise "Can't verify yet" (+ follow_up_after).

``suggested_reply`` is left unset: reply generation is Phase 3.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from pydantic import ValidationError

from ..models import Claim, StatementMeta, StatementRow, Verdict

__all__ = ["MatchConfig", "match_claims", "name_similarity"]

VERIFIED = "Verified"
LIKELY = "Likely match"
CONTRADICTED = "Contradicted"
NOT_FOUND = "Not found"
DUPLICATE = "Duplicate"
CANT_VERIFY = "Can't verify yet"


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class MatchConfig:
    #: Tier 2/3 window: |claim time - statement time| must be <= this.
    time_window_minutes: int = 30
    #: Tier 1 only: same reference but times further apart than this => Contradicted.
    reference_time_conflict_hours: int = 24
    #: name similarity >= this counts as "similar".
    name_similar_threshold: float = 0.80
    #: name similarity < this (names both present, statement name from a hint)
    #: counts as "clearly different".
    name_conflict_threshold: float = 0.30
    #: two claims' names below this are "conflicting" for the same-reference rule.
    claim_name_conflict_threshold: float = 0.50
    #: dHash bit distance (of 256) still treated as "near identical".
    near_hash_bits: int = 6
    #: hash evidence needs amount equal and times within this many seconds.
    image_corroboration_seconds: int = 60
    #: Can't verify yet: how long after the claim a newer statement is suggested.
    follow_up_delay_hours: int = 24
    #: statements parsed below this confidence never support "Not found".
    min_parse_confidence: float = 0.5
    #: two scores within this many points count as an ambiguous tie.
    ambiguity_points: float = 10.0


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def _as_dt(v: Any) -> Optional[datetime]:
    """datetime / date / ISO string -> naive datetime. Timezones are dropped
    (wall-clock is compared as-is)."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, datetime):
        d = v
    elif isinstance(v, date):
        d = datetime(v.year, v.month, v.day)
    elif isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return d.replace(tzinfo=None) if d.tzinfo is not None else d


def _paise(v: Any) -> Optional[int]:
    if v is None or isinstance(v, bool):
        return None
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        return None
    if not d.is_finite():
        return None
    return int((d * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _money(p: int) -> str:
    return f"INR {p // 100}.{p % 100:02d}"


def _num(p: int) -> float:
    return p / 100


_REF_RE = re.compile(r"(?<!\d)\d{12}(?!\d)")


def _norm_ref(v: Any) -> Optional[str]:
    if v is None or isinstance(v, bool):
        return None
    s = re.sub(r"[\s\-]", "", str(v))
    return s if re.fullmatch(r"\d{12}", s) and len(set(s)) > 1 else None


def _txt(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s or None


def _conf_of(conf: Any, key: str) -> Optional[float]:
    try:
        v = conf.get(key) if conf else None
        v = float(v) if v is not None else None
    except (TypeError, ValueError, AttributeError):
        return None
    return v if v is not None and 0.0 <= v <= 1.0 else None


def _clamp(x: float) -> float:
    return round(min(1.0, max(0.0, x)), 4)


def _mins(td_seconds: float) -> str:
    m = td_seconds / 60
    if m < 90:
        return f"{m:.0f} min"
    return f"{m / 60:.1f} h"


# --------------------------------------------------------------------------
# Name similarity (conservative, deterministic)
# --------------------------------------------------------------------------

_TITLES = {"mr", "mrs", "ms", "miss", "shri", "smt", "sri", "shree", "dr", "prof"}


def _name_tokens(s: Any) -> List[str]:
    t = unicodedata.normalize("NFKC", str(s or "")).casefold()
    return [w for w in re.findall(r"[^\W\d_]+", t) if w not in _TITLES]


def _tok_score(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if len(a) == 1 or len(b) == 1:  # initial vs full token
        return 0.6 if a[0] == b[0] else 0.0
    r = SequenceMatcher(None, a, b).ratio()
    return 0.9 * r if r >= 0.85 else 0.0  # typo tolerance only


def name_similarity(a: Any, b: Any) -> Optional[float]:
    """0..1 similarity, or None if either side has no usable name.

    Order-insensitive. Tokens match exactly (1.0), as an initial (0.6) or as a
    near-identical spelling (<=0.9). The score is scaled down when one name
    has fewer tokens than the other, and one-word names are capped at 0.75, so
    "Ali" vs "Ali Khan" is never "similar".
    """
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return None
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    free = list(range(len(long_)))
    total = 0.0
    for tok in short:
        best, best_i = 0.0, None
        for i in free:
            s = _tok_score(tok, long_[i])
            if s > best:
                best, best_i = s, i
        if best_i is not None:
            free.remove(best_i)
        total += best
    sim = (total / len(short)) * math.sqrt(len(short) / len(long_))
    if len(short) == 1:
        sim = min(sim, 0.75)
    return round(sim, 4)


# --------------------------------------------------------------------------
# Prepared (normalized) inputs
# --------------------------------------------------------------------------

@dataclass
class _Row:
    pos: int
    row_id: str
    credit: Optional[int]
    debit: Optional[int]
    dt: Optional[datetime]
    date_only: bool
    refs: Dict[str, str]          # reference -> "statement reference field" | "narration"
    name_hint: Optional[str]
    narration: str
    key: Tuple[str, int] = (" ", 0)


@dataclass
class _Claim:
    pos: int
    claim_id: str
    amount: Optional[int]
    ts: Optional[datetime]
    ref: Optional[str]
    name: Optional[str]
    upi: Optional[str]
    img: Optional[str]
    status_shown: Optional[str]
    currency: Optional[str]
    conf: Any
    key: Tuple[str, int] = (" ", 0)


def _prep_row(pos: int, r: Any) -> _Row:
    credit, debit = _paise(getattr(r, "credit", None)), _paise(getattr(r, "debit", None))
    dt = _as_dt(getattr(r, "datetime", None))
    narration = _txt(getattr(r, "narration", None)) or ""
    refs: Dict[str, str] = {}
    ext = _norm_ref(getattr(r, "extracted_reference", None))
    if ext:
        refs[ext] = "statement reference field"
    for m in _REF_RE.finditer(narration):
        if len(set(m.group(0))) > 1:
            refs.setdefault(m.group(0), "narration")
    rid = _txt(getattr(r, "row_id", None)) or f"row{pos}"
    return _Row(
        pos=pos, row_id=rid,
        credit=credit if credit and credit > 0 else None,
        debit=debit if debit and debit > 0 else None,
        dt=dt,
        date_only=bool(dt and dt.time() == time(0, 0)),
        refs=refs,
        name_hint=_txt(getattr(r, "name_hint", None)),
        narration=narration,
        key=(rid, pos),
    )


def _prep_claim(pos: int, c: Any) -> _Claim:
    amount = _paise(getattr(c, "amount", None))
    cid = _txt(getattr(c, "claim_id", None)) or f"claim{pos}"
    cur = _txt(getattr(c, "currency", None))
    return _Claim(
        pos=pos, claim_id=cid,
        amount=amount if amount and amount > 0 else None,
        ts=_as_dt(getattr(c, "timestamp", None)),
        ref=_norm_ref(getattr(c, "reference", None)),
        name=_txt(getattr(c, "payer_name", None)),
        upi=(_txt(getattr(c, "payer_upi_id", None)) or "").lower() or None,
        img=_txt(getattr(c, "image_hash", None)),
        status_shown=(_txt(getattr(c, "status_shown", None)) or "").lower() or None,
        currency=cur.upper() if cur else None,
        conf=getattr(c, "confidence", None),
        key=(cid, pos),
    )


# --------------------------------------------------------------------------
# Evidence helpers
# --------------------------------------------------------------------------

def _upi_in_narration(c: _Claim, r: _Row) -> bool:
    return bool(c.upi and "*" not in c.upi and "•" not in c.upi and c.upi in r.narration.lower())


def _name_evidence(c: _Claim, r: _Row) -> Tuple[Optional[float], Optional[str]]:
    """(similarity, source). Statement name hint can support OR contradict;
    narration can only support."""
    if not c.name:
        return None, None
    if r.name_hint:
        s = name_similarity(c.name, r.name_hint)
        if s is not None:
            return s, "hint"
    toks = _name_tokens(c.name)
    if len(toks) >= 2 and r.narration:
        words = set(_name_tokens(r.narration))
        if all(t in words for t in toks):
            return 0.85, "narration"
    return None, None


def _time_delta(c: _Claim, r: _Row) -> Optional[float]:
    """Seconds between claim and row, None if not comparable (missing/date-only)."""
    if c.ts is None or r.dt is None or r.date_only:
        return None
    return abs((c.ts - r.dt).total_seconds())


def _extraction_conf(c: _Claim, keys: Sequence[str]) -> Optional[float]:
    vals = [v for v in (_conf_of(c.conf, k) for k in keys) if v is not None]
    return min(vals) if vals else None


# --------------------------------------------------------------------------
# Candidate edges
# --------------------------------------------------------------------------

@dataclass
class _Edge:
    c: _Claim
    r: _Row
    tier: int                      # 1, 2 or 3
    points: float                  # 0..100, see README "Candidate scoring"
    delta: Optional[float]         # seconds
    sim: Optional[float]
    sim_src: Optional[str]
    upi: bool
    ref_source: Optional[str] = None
    ref_note: Optional[str] = None
    date_only: bool = False
    ambiguous_with: int = 0


def _points(c: _Claim, r: _Row, delta: Optional[float], window: float, sim: Optional[float],
            upi: bool, name_used: bool) -> float:
    """30 time + 40 name + 20 UPI id + 10 extraction confidence = 100 max.
    Missing evidence scores 0 (never a free pass)."""
    if delta is not None:
        prox = max(0.0, 1.0 - delta / window) if window > 0 else 0.0
    elif r.date_only and c.ts is not None and r.dt is not None and c.ts.date() == r.dt.date():
        prox = 0.2
    else:
        prox = 0.0
    ec = _extraction_conf(c, ("amount", "timestamp") + (("payer_name",) if name_used else ()))
    return round(30 * prox + 40 * (sim or 0.0) + 20 * (1.0 if upi else 0.0) + 10 * (ec if ec is not None else 0.5), 3)


def _ref_pair_conflicts(c: _Claim, r: _Row, cfg: MatchConfig) -> Dict[str, Tuple[str, float]]:
    """For a claim whose reference is on row r: {field: (difference text, strength)}."""
    out: Dict[str, Tuple[str, float]] = {}
    if c.amount != r.credit:
        out["amount"] = (f"claim={_num(c.amount)}, statement={_num(r.credit) if r.credit else None}", 0.90)
    sim, src = _name_evidence(c, r)
    if sim is not None and src == "hint" and sim < cfg.name_conflict_threshold and not _upi_in_narration(c, r):
        out["payer_name"] = (f"claim={c.name}, statement={r.name_hint}", 0.70)
    if c.ts is not None and r.dt is not None:
        if r.date_only:
            conflict = abs((c.ts.date() - r.dt.date()).days) > 1
        else:
            conflict = abs((c.ts - r.dt).total_seconds()) > cfg.reference_time_conflict_hours * 3600
        if conflict:
            out["timestamp"] = (f"claim={c.ts.isoformat()}, statement={r.dt.isoformat()}", 0.75)
    if c.status_shown in ("failed", "fail", "failure"):
        out["status_shown"] = ("claim=failed, statement=credit recorded", 0.60)
    return out


def _soft_edge(c: _Claim, r: _Row, cfg: MatchConfig) -> Tuple[Optional[_Edge], Optional[str]]:
    """Tier 2/3 edge for (claim, credit row) or (None, why-excluded)."""
    if c.amount is None or r.credit != c.amount or c.ts is None or r.dt is None:
        return None, None
    window = cfg.time_window_minutes * 60.0
    delta = None
    if r.date_only:
        if c.ts.date() != r.dt.date():
            return None, None
    else:
        delta = abs((c.ts - r.dt).total_seconds())
        if delta > window:
            return None, None
    ref_note = None
    if c.ref and r.refs:
        if c.ref not in r.refs:
            return None, "ref"
    elif c.ref:
        ref_note = "Claim reference could not be checked: the statement row carries no reference."
    elif r.refs:
        ref_note = "Claim has no reference to compare with the statement row."
    sim, src = _name_evidence(c, r)
    upi = _upi_in_narration(c, r)
    if sim is not None and src == "hint" and sim < cfg.name_conflict_threshold and not upi:
        return None, f"name:{r.name_hint}"
    identity = upi or (sim is not None and sim >= cfg.name_similar_threshold)
    tier = 2 if (identity and not r.date_only) else 3
    return _Edge(c, r, tier, _points(c, r, delta, window, sim, upi, sim is not None), delta, sim, src, upi,
                 ref_note=ref_note, date_only=r.date_only), None


# --------------------------------------------------------------------------
# Maximum-weight assignment (Hungarian algorithm, integer weights)
# --------------------------------------------------------------------------

def _hungarian_max(w: List[List[int]]) -> List[int]:
    """w[i][j] >= 0 (0 = no edge). Returns col index per row or -1."""
    n, m = len(w), len(w[0]) if w else 0
    N = max(n, m)
    INF = 1 << 62
    a = [[0] * (N + 1) for _ in range(N + 1)]
    for i in range(n):
        for j in range(m):
            a[i + 1][j + 1] = -w[i][j]
    u, v, p, way = [0] * (N + 1), [0] * (N + 1), [0] * (N + 1), [0] * (N + 1)
    for i in range(1, N + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (N + 1)
        used = [False] * (N + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], INF, 0
            for j in range(1, N + 1):
                if not used[j]:
                    cur = a[i0][j] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(N + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    res = [-1] * n
    for j in range(1, N + 1):
        i = p[j]
        if 1 <= i <= n and j <= m and w[i - 1][j - 1] > 0:
            res[i - 1] = j - 1
    return res


def _assign(edges: List[_Edge]) -> Dict[int, _Edge]:
    """Global one-to-one assignment. Returns {claim.pos: edge}.

    Edge weight = tier bonus (T1 > T2 > T3) + points, so a better tier always
    wins and more assigned pairs beat fewer. Exact ties are broken in favour of
    the lower (claim_id, input position) claim and lower (row_id, position)
    row, via a tiny perturbation.
    """
    parent: Dict[Tuple[str, int], Tuple[str, int]] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in edges:
        a, b = find(("c", e.c.pos)), find(("r", e.r.pos))
        if a != b:
            parent[max(a, b)] = min(a, b)
    comps: Dict[Tuple[str, int], List[_Edge]] = defaultdict(list)
    for e in edges:
        comps[find(("c", e.c.pos))].append(e)

    result: Dict[int, _Edge] = {}
    for root in sorted(comps):
        es = comps[root]
        cl = sorted({e.c.pos: e.c for e in es}.values(), key=lambda c: c.key)
        rw = sorted({e.r.pos: e.r for e in es}.values(), key=lambda r: r.key)
        ci = {c.pos: i for i, c in enumerate(cl)}
        ri = {r.pos: j for j, r in enumerate(rw)}
        factor = len(cl) * (len(rw) + 1) + 1
        w = [[0] * len(rw) for _ in cl]
        by: Dict[Tuple[int, int], _Edge] = {}
        for e in es:
            i, j = ci[e.c.pos], ri[e.r.pos]
            base = (4 - e.tier) * 10_000_000 + int(round(e.points * 1000))
            w[i][j] = base * factor - (i * (len(rw) + 1) + j)
            by[(i, j)] = e
        for i, j in enumerate(_hungarian_max(w)):
            if j >= 0:
                result[cl[i].pos] = by[(i, j)]
    return result


# --------------------------------------------------------------------------
# Outcomes
# --------------------------------------------------------------------------

@dataclass
class _Out:
    status: str
    tier: Optional[int] = None
    row: Optional[str] = None
    conf: float = 0.0
    reasons: List[str] = field(default_factory=list)
    diffs: Dict[str, str] = field(default_factory=dict)
    follow: Optional[str] = None
    row_pos: Optional[int] = None


def _name_reason(e: _Edge, cfg: MatchConfig) -> str:
    if e.upi:
        return "Payer UPI ID appears in the statement narration."
    if e.sim is None:
        return "Payer name was not compared: it is missing on the claim or the statement has no name information."
    where = "statement name hint" if e.sim_src == "hint" else "statement narration"
    if e.sim >= cfg.name_similar_threshold:
        return f"Payer name is similar to the {where} (similarity {e.sim:.2f})."
    return f"Payer name is only weakly similar to the {where} (similarity {e.sim:.2f}); not enough to confirm identity."


def _verified_out(e: _Edge, cfg: MatchConfig) -> _Out:
    c, r = e.c, e.r
    conf = 0.97
    reasons = [
        f"Exact 12-digit reference {c.ref} matches statement row {r.row_id} ({e.ref_source}).",
        f"Amount matches: claim {_money(c.amount)} vs statement credit {_money(r.credit)}.",
    ]
    d = _time_delta(c, r)
    if d is not None and d <= cfg.time_window_minutes * 60:
        reasons.append(f"Transaction time is within {cfg.time_window_minutes} minutes of the claim (differs by {_mins(d)}).")
    elif d is not None:
        conf -= 0.07
        reasons.append(f"Transaction time differs from the claim by {_mins(d)}, outside the {cfg.time_window_minutes}-minute window "
                       f"but within {cfg.reference_time_conflict_hours} hours; the exact reference still matches.")
    elif r.date_only and c.ts is not None and r.dt is not None:
        reasons.append("Statement row has a date only; the date is consistent with the claim.")
    else:
        conf -= 0.02
        reasons.append("Time was not compared: the claim or the statement row has no usable time.")
    reasons.append(_name_reason(e, cfg))
    if e.sim is not None and not e.upi and e.sim < cfg.name_similar_threshold:
        conf -= 0.04
    if e.ref_source == "narration":
        conf -= 0.02
    if (e.c.status_shown or "") in ("pending", "processing"):
        conf -= 0.03
        reasons.append("Screenshot shows the payment as pending, but a matching credit is on the statement.")
    ec = _extraction_conf(c, ("reference", "amount"))
    if ec is not None and ec < 0.9:
        conf -= (0.9 - ec) * 0.1
        reasons.append("Screenshot extraction confidence for reference/amount was below 0.90.")
    return _Out(VERIFIED, 1, r.row_id, _clamp(max(conf, 0.85)), reasons, row_pos=r.pos)


def _likely_out(e: _Edge, cfg: MatchConfig) -> _Out:
    c, r = e.c, e.r
    reasons = [f"Amount matches: claim {_money(c.amount)} vs statement credit {_money(r.credit)} (row {r.row_id})."]
    if e.delta is not None:
        reasons.append(f"Transaction time is within {cfg.time_window_minutes} minutes of the claim (differs by {_mins(e.delta)}).")
    else:
        reasons.append("Statement row has a date only; the date matches but the time of day could not be compared.")
    prox = max(0.0, 1.0 - e.delta / (cfg.time_window_minutes * 60)) if e.delta is not None else 0.2
    if e.tier == 2:
        reasons.append(_name_reason(e, cfg))
        sim_part = 0.0 if e.sim is None else max(0.0, (min(e.sim, 1.0) - cfg.name_similar_threshold) / (1 - cfg.name_similar_threshold))
        conf = min(0.89, 0.65 + 0.15 * sim_part + 0.04 * prox + (0.05 if e.upi else 0.0))
        floor = 0.60
    else:
        reasons.append("Reference evidence is missing: no reference on the claim or none that could be verified against the statement."
                       if (not c.ref) or e.ref_note else "No exact reference match.")
        reasons.append(_name_reason(e, cfg))
        reasons.append("Payer identity could not be confirmed. Amount and time alone are not enough to verify this payment; "
                       "treat it as a possible match only.")
        conf = 0.40 + 0.14 * prox + (0.04 * e.sim if e.sim is not None else 0.0)
        conf = min(conf, 0.60)
        floor = 0.35
    if e.ref_note:
        reasons.append(e.ref_note)
    if e.ambiguous_with > 1:
        conf -= 0.08
        reasons.append(f"{e.ambiguous_with} statement credits match this claim about equally well, so the choice is ambiguous.")
    ec = _extraction_conf(c, ("amount", "timestamp"))
    if ec is not None and ec < 0.5:
        conf -= 0.10
        reasons.append("Screenshot extraction confidence for amount/time was low (below 0.50).")
    return _Out(LIKELY, e.tier, r.row_id, _clamp(max(conf, floor)), reasons, row_pos=r.pos)


def _contradicted_out(c: _Claim, r: _Row, diffs: Dict[str, Tuple[str, float]], extra_rows: int) -> _Out:
    reasons = []
    ref = c.ref
    if "amount" in diffs:
        reasons.append(f"Reference {ref} appears on statement row {r.row_id}, but the amount differs: "
                       f"claim {_money(c.amount)} vs statement credit {_money(r.credit)}.")
    else:
        reasons.append(f"Reference {ref} appears on statement row {r.row_id}, so this row is the relevant evidence.")
    if "payer_name" in diffs:
        reasons.append(f"Payer information is incompatible: claim '{c.name}' vs statement '{r.name_hint}'.")
    if "timestamp" in diffs:
        reasons.append("Transaction times are far apart for the same reference "
                       f"(claim {c.ts.isoformat()} vs statement {r.dt.isoformat()}).")
    if "status_shown" in diffs:
        reasons.append("The screenshot itself shows a failed payment, yet a credit with this reference is on the statement.")
    if extra_rows:
        reasons.append(f"{extra_rows} other statement row(s) share this reference; the closest one is shown.")
    reasons.append("Because the reference exists on the statement, the claim is reported as a mismatch "
                   "instead of searching for another match.")
    strengths = sorted((s for _, s in diffs.values()), reverse=True)
    conf = min(0.95, strengths[0] + 0.02 * (len(strengths) - 1))
    rc = _conf_of(c.conf, "reference")
    if rc is not None and rc < 0.5:
        conf *= 0.8
    return _Out(CONTRADICTED, 4, r.row_id, _clamp(conf), reasons, {k: v[0] for k, v in diffs.items()}, row_pos=r.pos)


# --------------------------------------------------------------------------
# Coverage-aware "no candidate" outcome
# --------------------------------------------------------------------------

@dataclass
class _Ctx:
    cfg: MatchConfig
    has_rows: bool
    start: Optional[datetime]
    end: Optional[datetime]
    parse_conf: Optional[float]


def _build_ctx(rows: List[_Row], meta: Any, cfg: MatchConfig) -> _Ctx:
    start, end = _as_dt(getattr(meta, "coverage_start", None)), _as_dt(getattr(meta, "coverage_end", None))
    if end is not None and end.time() == time(0, 0):  # date-only end is inclusive of that whole day
        end = end + timedelta(days=1) - timedelta(seconds=1)
    pc = getattr(meta, "parse_confidence", None)
    try:
        pc = float(pc) if pc is not None else None
    except (TypeError, ValueError):
        pc = None
    return _Ctx(cfg, bool(rows), start, end, pc)


def _no_candidate_out(c: _Claim, ctx: _Ctx, search_notes: List[str], excl: Dict[str, Any]) -> _Out:
    cfg = ctx.cfg
    W = timedelta(minutes=cfg.time_window_minutes)

    def cvy(msg: str, follow: Optional[datetime] = None) -> _Out:
        notes = [msg] + search_notes
        return _Out(CANT_VERIFY, None, None, 0.0, notes, follow=follow.isoformat() if follow else None)

    if not ctx.has_rows:
        return cvy("The statement contains no readable transactions, so absence of a payment cannot be concluded.")
    if ctx.parse_conf is not None and ctx.parse_conf < cfg.min_parse_confidence:
        return cvy(f"The statement was parsed with low confidence ({ctx.parse_conf:.2f}); a missing payment cannot be concluded.")
    if c.ts is None:
        return cvy("The claim has no readable timestamp, so statement coverage cannot be checked.")
    if ctx.start is None or ctx.end is None:
        return cvy("Statement coverage dates are unknown, so a missing payment cannot be concluded.")
    if ctx.end < ctx.start:
        return cvy("Statement coverage dates are inconsistent (end before start).")
    follow = c.ts + timedelta(hours=cfg.follow_up_delay_hours)
    if c.ts > ctx.end:
        return cvy("Claim timestamp is after the statement coverage end; a newer statement is required.", follow)
    if c.ts > ctx.end - W:
        return cvy("Claim timestamp is too close to the statement coverage end; a matching credit may be posted after it. "
                   "A newer statement is required.", follow)
    if c.ts < ctx.start:
        return cvy("Claim timestamp is before the statement coverage start; an earlier statement is required.")
    if c.ts < ctx.start + W:
        return cvy("Claim timestamp is too close to the statement coverage start; an earlier statement is required.")
    reasons = [f"Claim time {c.ts.isoformat()} is inside the statement coverage "
               f"({ctx.start.isoformat()} to {ctx.end.isoformat()}), not near either boundary."]
    if c.ref:
        reasons.append(f"No statement credit carries reference {c.ref}.")
    if c.amount is not None:
        reasons.append(f"No statement credit of {_money(c.amount)} exists within {cfg.time_window_minutes} minutes of the claim time"
                       f"{' that is compatible with the claim' if excl else ''}.")
    if excl.get("ref"):
        reasons.append(f"{excl['ref']} credit(s) with the same amount and time carry a different reference.")
    for nm in excl.get("names", []):
        reasons.append(f"A credit with the same amount and time exists, but the statement name '{nm}' differs from the claimed payer.")
    if c.status_shown in ("failed", "fail", "failure"):
        reasons.append("The screenshot itself shows a failed payment.")
    reasons += search_notes
    conf = 0.70 if not c.ref else 0.75
    if ctx.parse_conf is not None:
        conf *= 0.5 + 0.5 * ctx.parse_conf
    return _Out(NOT_FOUND, 5, None, _clamp(conf), reasons)


# --------------------------------------------------------------------------
# Verdict construction (adapts to models.py without editing it)
# --------------------------------------------------------------------------

def _build_verdict(claim_id: str, o: _Out) -> Verdict:
    base: Dict[str, Any] = dict(
        claim_id=claim_id, status=o.status, tier=o.tier, matched_row_id=o.row,
        confidence=_clamp(o.conf), reasons=list(o.reasons), field_differences=dict(o.diffs),
        follow_up_after=o.follow, suggested_reply=None,
    )
    last: Optional[ValidationError] = None
    for drop_none in (False, True):
        for fill in (False, True):
            for reasons_str in (False, True):
                d = dict(base)
                if fill:
                    d["tier"] = 0 if d["tier"] is None else d["tier"]
                    d["suggested_reply"] = ""
                if reasons_str:
                    d["reasons"] = "; ".join(d["reasons"])
                if drop_none:
                    d = {k: v for k, v in d.items() if v is not None}
                try:
                    return Verdict(**d)
                except ValidationError as exc:
                    last = exc
    raise last  # type: ignore[misc]


# --------------------------------------------------------------------------
# Duplicate evidence
# --------------------------------------------------------------------------

_SHA = "sha256:"
_DH = "dhash256:"


def _hamming(a: str, b: str) -> Optional[int]:
    if a.startswith(_DH) and b.startswith(_DH):
        try:
            return bin(int(a[len(_DH):], 16) ^ int(b[len(_DH):], 16)).count("1")
        except ValueError:
            return None
    return None


@dataclass
class _Link:
    ref: bool = False
    sha: bool = False
    hash_kind: Optional[str] = None      # "identical" | "near"
    corroborated: bool = False
    uncorroborated_hash: bool = False

    @property
    def linked(self) -> bool:
        return self.ref or self.sha or (self.hash_kind is not None and self.corroborated)

    @property
    def strength(self) -> float:
        if self.sha:
            return 0.95
        if self.ref:
            return 0.85
        if self.hash_kind == "identical" and self.corroborated:
            return 0.80
        if self.hash_kind == "near" and self.corroborated:
            return 0.70
        return 0.0


def _pair_link(a: _Claim, b: _Claim, cfg: MatchConfig) -> _Link:
    lk = _Link(ref=bool(a.ref and a.ref == b.ref))
    if a.img and b.img:
        if a.img.startswith(_SHA) and a.img == b.img:
            lk.sha = True
        else:
            h = _hamming(a.img, b.img)
            if h is not None and h <= cfg.near_hash_bits:
                lk.hash_kind = "identical" if h == 0 else "near"
    corr = lk.ref
    if (not corr and a.amount is not None and a.amount == b.amount and a.ts and b.ts
            and abs((a.ts - b.ts).total_seconds()) <= cfg.image_corroboration_seconds):
        corr = True
    lk.corroborated = corr
    lk.uncorroborated_hash = lk.hash_kind is not None and not corr and not lk.sha
    return lk


def _names_conflict(a: _Claim, b: _Claim, cfg: MatchConfig) -> bool:
    s = name_similarity(a.name, b.name) if a.name and b.name else None
    return s is not None and s < cfg.claim_name_conflict_threshold


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def match_claims(
    claims: Iterable[Claim],
    statement_rows: Iterable[StatementRow],
    statement_meta: Optional[StatementMeta] = None,
    config: Optional[MatchConfig] = None,
) -> List[Verdict]:
    """Verify every claim against the statement. One Verdict per claim, same order."""
    cfg = config or MatchConfig()
    cl = [_prep_claim(i, c) for i, c in enumerate(list(claims or []))]
    rw = [_prep_row(j, r) for j, r in enumerate(list(statement_rows or []))]
    if not cl:
        return []
    ctx = _build_ctx(rw, statement_meta, cfg)

    credit_by_ref: Dict[str, List[_Row]] = defaultdict(list)
    debit_by_ref: Dict[str, List[_Row]] = defaultdict(list)
    credit_by_amt: Dict[int, List[_Row]] = defaultdict(list)
    for r in sorted(rw, key=lambda r: r.key):
        if r.credit:
            credit_by_amt[r.credit].append(r)
            for ref in r.refs:
                credit_by_ref[ref].append(r)
        elif r.debit:
            for ref in r.refs:
                debit_by_ref[ref].append(r)

    fixed: Dict[int, _Out] = {}                 # decided before assignment
    edges: List[_Edge] = []
    excl: Dict[int, Dict[str, Any]] = {}        # exclusion evidence for Not found reasons
    edges_by_claim: Dict[int, List[_Edge]] = defaultdict(list)
    ref_rows_of: Dict[int, List[_Row]] = {}     # tier-1 candidate rows per claim (for duplicate reporting)

    for c in sorted(cl, key=lambda c: c.key):
        if c.currency not in (None, "INR"):
            fixed[c.pos] = _Out(CANT_VERIFY, reasons=[f"Claim currency is {c.currency}; only INR statements are supported."])
            continue
        crow = credit_by_ref.get(c.ref, []) if c.ref else []
        drow = debit_by_ref.get(c.ref, []) if c.ref else []
        if c.amount is None:
            msg = "The claim has no readable amount, so it cannot be compared with the statement."
            if crow:
                msg += (f" Its reference {c.ref} does appear on statement row {crow[0].row_id} "
                        f"(credit {_money(crow[0].credit)}); please confirm the amount.")
            fixed[c.pos] = _Out(CANT_VERIFY, reasons=[msg])
            continue
        if crow:
            ref_rows_of[c.pos] = crow
            viable, bad = [], []
            for r in crow:
                diffs = _ref_pair_conflicts(c, r, cfg)
                if diffs:
                    bad.append((len(diffs), abs(c.amount - r.credit), r.key, r, diffs))
                else:
                    sim, _src = _name_evidence(c, r)
                    d = _time_delta(c, r)
                    pts = _points(c, r, d, cfg.time_window_minutes * 60.0, sim, _upi_in_narration(c, r), sim is not None)
                    viable.append(_Edge(c, r, 1, pts, d, sim, _src, _upi_in_narration(c, r), ref_source=r.refs[c.ref]))
            if viable:
                edges += viable
                edges_by_claim[c.pos] += viable
            else:
                bad.sort(key=lambda t: t[:3])
                _, _, _, r, diffs = bad[0]
                fixed[c.pos] = _contradicted_out(c, r, diffs, len(crow) - 1)
            continue
        if drow:
            r = sorted(drow, key=lambda r: r.key)[0]
            fixed[c.pos] = _Out(
                CONTRADICTED, 4, r.row_id, 0.70,
                [f"Reference {c.ref} appears on statement row {r.row_id}, but as a debit (money going out), not a credit.",
                 "Because the reference exists on the statement, the claim is reported as a mismatch "
                 "instead of searching for another match."],
                {"direction": "claim=credit received, statement=debit"}, row_pos=r.pos)
            continue
        if c.status_shown in ("failed", "fail", "failure"):
            continue  # no soft matching for a screenshot that itself says "failed"
        found: List[_Edge] = []
        ex: Dict[str, Any] = {}
        for r in credit_by_amt.get(c.amount, []):
            e, why = _soft_edge(c, r, cfg)
            if e:
                found.append(e)
            elif why == "ref":
                ex["ref"] = ex.get("ref", 0) + 1
            elif why and why.startswith("name:"):
                ex.setdefault("names", []).append(why[5:])
        ex_names = sorted(set(ex.get("names", [])))
        if ex_names:
            ex["names"] = ex_names
        excl[c.pos] = ex
        if found:
            ranked = sorted(found, key=lambda e: (-(4 - e.tier), -e.points, e.r.key))
            top = ranked[0]
            close = [e for e in ranked if e.tier == top.tier and top.points - e.points < cfg.ambiguity_points]
            for e in found:
                e.ambiguous_with = len(close) if any(e is x for x in close) else 0
            edges += found
            edges_by_claim[c.pos] += found

    assigned = _assign(edges)
    row_by_pos = {r.pos: r for r in rw}
    claim_by_pos = {c.pos: c for c in cl}

    # ---- provisional outcomes ------------------------------------------------
    outs: Dict[int, _Out] = {}
    for c in cl:
        if c.pos in fixed:
            outs[c.pos] = fixed[c.pos]
        elif c.pos in assigned:
            e = assigned[c.pos]
            outs[c.pos] = _verified_out(e, cfg) if e.tier == 1 else _likely_out(e, cfg)
        elif c.pos in edges_by_claim:
            outs[c.pos] = _Out(NOT_FOUND, 5)  # lost a contest; refined below
        else:
            ex = excl.get(c.pos, {})
            outs[c.pos] = _no_candidate_out(c, ctx, [], ex)

    # ---- duplicate evidence between claims ---------------------------------------
    order = sorted(cl, key=lambda c: c.key)
    parent = {c.pos: c.pos for c in cl}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    links: Dict[Tuple[int, int], _Link] = {}
    buckets: Dict[Tuple[str, str], List[_Claim]] = defaultdict(list)
    dh_claims: List[_Claim] = []
    for c in order:
        if c.ref:
            buckets[("ref", c.ref)].append(c)
        if c.img:
            buckets[("img", c.img)].append(c)
            if c.img.startswith(_DH):
                dh_claims.append(c)
    cand_pairs = set()
    for lst in buckets.values():
        for i in range(len(lst)):
            for j in range(i + 1, len(lst)):
                cand_pairs.add((lst[i].pos, lst[j].pos))
    for i in range(len(dh_claims)):
        for j in range(i + 1, len(dh_claims)):
            cand_pairs.add((dh_claims[i].pos, dh_claims[j].pos))
    key_rank = {c.pos: n for n, c in enumerate(order)}
    for a, b in sorted(cand_pairs, key=lambda p: (key_rank[p[0]], key_rank[p[1]])):
        lk = _pair_link(claim_by_pos[a], claim_by_pos[b], cfg)
        links[(a, b)] = lk
        if lk.linked:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)

    def status_rank(pos: int) -> int:
        if pos in assigned and assigned[pos].tier == 1:
            return 0
        if pos in assigned:
            return 1
        return 2

    groups: Dict[int, List[int]] = defaultdict(list)
    for c in order:
        groups[find(c.pos)].append(c.pos)

    note_orig: Dict[int, List[str]] = defaultdict(list)
    note_other: Dict[int, List[str]] = defaultdict(list)
    for root in sorted(groups, key=lambda g: key_rank[g]):
        members = groups[root]
        if len(members) < 2:
            continue
        eligible = [p for p in members if outs[p].status != CONTRADICTED]
        eligible.sort(key=lambda p: (status_rank(p), key_rank[p]))
        in_group_links = {k: lk for k, lk in links.items() if lk.linked and k[0] in members and k[1] in members}
        for p in members:  # informational notes for members that are not demoted
            if p not in eligible:
                others = [claim_by_pos[q].claim_id for q in members if q != p]
                note_other[p].append(f"Reference/fingerprint is shared with claim(s) {', '.join(others[:3])}; "
                                     "this is duplicate evidence, not proof of misconduct.")
        if len(eligible) < 2:
            continue
        # same reference + conflicting payer names, not resolved by the statement?
        conflict_pair = None
        for (a, b), lk in sorted(in_group_links.items(), key=lambda kv: (key_rank[kv[0][0]], key_rank[kv[0][1]])):
            if lk.ref and a in eligible and b in eligible and _names_conflict(claim_by_pos[a], claim_by_pos[b], cfg):
                ca, cb = claim_by_pos[a], claim_by_pos[b]
                rows = ref_rows_of.get(a) or ref_rows_of.get(b) or []
                resolved = False
                if rows and any(r.name_hint for r in rows):
                    sa = max((name_similarity(ca.name, r.name_hint) or 0.0) for r in rows if r.name_hint)
                    sb = max((name_similarity(cb.name, r.name_hint) or 0.0) for r in rows if r.name_hint)
                    resolved = ((sa >= cfg.name_similar_threshold and sb < cfg.claim_name_conflict_threshold)
                                or (sb >= cfg.name_similar_threshold and sa < cfg.claim_name_conflict_threshold))
                if not resolved:
                    conflict_pair = (a, b)
                    break
        if conflict_pair:
            keep: Optional[int] = None
            demote = list(eligible)
        else:
            keep, demote = eligible[0], eligible[1:]
        contested = None
        for p in eligible:
            if p in assigned and assigned[p].tier == 1:
                contested = assigned[p].r
                break
            if ref_rows_of.get(p):
                contested = contested or ref_rows_of[p][0]
        for p in demote:
            cp = claim_by_pos[p]
            ev: List[str] = []
            best = 0.0
            for q in members:
                if q == p:
                    continue
                lk = links.get((p, q)) or links.get((q, p))
                if lk is None or not lk.linked:
                    continue
                cq = claim_by_pos[q]
                best = max(best, lk.strength)
                if lk.sha:
                    ev.append(f"Screenshot file is byte-identical to claim {cq.claim_id}'s (SHA-256 match).")
                if lk.ref:
                    ev.append(f"Same 12-digit reference {cp.ref} as claim {cq.claim_id}.")
                if lk.hash_kind and lk.corroborated and not lk.sha:
                    kind = "identical" if lk.hash_kind == "identical" else "near-identical"
                    ev.append(f"Image fingerprint is {kind} to claim {cq.claim_id}'s and amount/time/reference also agree "
                              "(supporting evidence, not proof).")
            if conflict_pair:
                ca, cb = (claim_by_pos[conflict_pair[0]], claim_by_pos[conflict_pair[1]])
                ev.append(f"Claims {ca.claim_id} and {cb.claim_id} give the same reference but different payer names "
                          f"('{ca.name}' vs '{cb.name}'). One statement credit can belong to only one payer, so none is "
                          "verified automatically.")
                best = 0.65
            elif keep is not None:
                ev.append(f"Claim {claim_by_pos[keep].claim_id} is treated as the primary submission "
                          f"(status: {outs[keep].status}).")
            ev.append("Duplicate evidence is not proof of misconduct; please confirm with the payer(s).")
            row = contested or (assigned[keep].r if keep is not None and keep in assigned else None)
            outs[p] = _Out(DUPLICATE, None, row.row_id if row else None, _clamp(best or 0.5), ev)
        if keep is not None:
            dup_ids = [claim_by_pos[p].claim_id for p in demote]
            note_orig[keep].append(f"Also submitted as claim(s) {', '.join(dup_ids[:3])}"
                                   f"{' (+%d more)' % (len(dup_ids) - 3) if len(dup_ids) > 3 else ''}; marked Duplicate.")

    # ---- uncorroborated hash notes ------------------------------------------------
    for (a, b), lk in sorted(links.items()):
        if lk.uncorroborated_hash and find(a) != find(b):
            for p, q in ((a, b), (b, a)):
                note_other[p].append(f"Image fingerprint resembles claim {claim_by_pos[q].claim_id}'s, but the extracted "
                                     "payment fields differ, so it is not treated as a duplicate.")

    # ---- claims that lost a contest for their only compatible credits ---------------
    for c in order:
        o = outs[c.pos]
        if c.pos in edges_by_claim and c.pos not in assigned and o.status == NOT_FOUND:
            es = sorted(edges_by_claim[c.pos], key=lambda e: e.r.key)
            winners = []
            for e in es:
                for q, we in assigned.items():
                    if we.r.pos == e.r.pos and q != c.pos:
                        winners.append((claim_by_pos[q], we))
            winners.sort(key=lambda t: t[0].key)
            dup_of = None
            for wc, we in winners:
                s = name_similarity(c.name, wc.name) if c.name and wc.name else None
                near = c.ts and wc.ts and abs((c.ts - wc.ts).total_seconds()) <= cfg.time_window_minutes * 60
                if s is not None and s >= cfg.name_similar_threshold and near:
                    dup_of = (wc, we, s)
                    break
            ids = ", ".join(sorted({wc.claim_id for wc, _ in winners})[:3])
            rows = ", ".join(sorted({we.r.row_id for _, we in winners})[:3])
            if dup_of:
                wc, we, s = dup_of
                outs[c.pos] = _Out(DUPLICATE, None, we.r.row_id, 0.70, [
                    f"Competes with claim {wc.claim_id} for statement row {we.r.row_id}; that row can verify only one claim.",
                    f"Same payer name (similarity {s:.2f}), same amount {_money(c.amount)} and times within "
                    f"{cfg.time_window_minutes} minutes of claim {wc.claim_id}.",
                    "Duplicate evidence is not proof of misconduct; please confirm with the payer.",
                ])
            else:
                outs[c.pos] = _Out(NOT_FOUND, 5, None, 0.55, [
                    f"The compatible statement credit(s) ({rows}) were already assigned to claim(s) {ids}; "
                    "a statement credit can verify only one claim.",
                    f"No other unassigned credit of {_money(c.amount)} exists within {cfg.time_window_minutes} minutes "
                    "of the claim time.",
                    "No shared reference, payer name or screenshot evidence links this claim to the other claim(s), "
                    "so it is not treated as a duplicate.",
                ])

    # ---- final notes + build ----------------------------------------------------------
    verdicts: List[Verdict] = []
    for c in cl:
        o = outs[c.pos]
        o.reasons = list(o.reasons) + note_orig.get(c.pos, []) + note_other.get(c.pos, [])
        if not o.reasons:
            o.reasons = ["No evidence was available for this claim."]
        verdicts.append(_build_verdict(c.claim_id, o))
    return verdicts
