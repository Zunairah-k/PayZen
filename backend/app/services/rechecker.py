"""PayZen — re-check workflow (Alizah, Phase 3).

    recheck_claims(claims, rows, meta, previous_verdicts=None, ...) -> List[Verdict]

Runs the EXISTING matcher (``match_claims``) on unresolved claims against a
newer statement. No matching rules live here, so Phase 2 behaviour is
unchanged and nothing is weakened.

Typical flow
------------
1. First run: ``verdicts = match_claims(claims, rows_v1, meta_v1)``.
2. A newer statement arrives: ``new = recheck_claims(claims, rows_v2, meta_v2, previous_verdicts=verdicts)``.
   Only claims that were "Can't verify yet" (or that have no previous verdict)
   are re-run; resolved claims are left alone.
3. ``merged = merge_rechecked(verdicts, new)`` replaces the old verdicts by claim_id.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .matcher import MatchConfig, match_claims
from .reply_generator import DEFAULT_LANGUAGE, DEFAULT_TONE, attach_replies

UNRESOLVED_STATUSES = ("Can't verify yet",)
CONSUMING_STATUSES = ("Verified", "Likely match")
_REF_RE = re.compile(r"(?<!\d)\d{12}(?!\d)")


def _ref(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = re.sub(r"[\s\-]", "", str(v))
    return s if re.fullmatch(r"\d{12}", s) else None


def _row_refs(row: Any) -> set:
    refs = set()
    r = _ref(getattr(row, "extracted_reference", None))
    if r:
        refs.add(r)
    refs.update(_REF_RE.findall(str(getattr(row, "narration", "") or "")))
    return refs


def _with_extra_reason(verdict: Any, note: str) -> Any:
    old = getattr(verdict, "reasons", None)
    new = (list(old) if isinstance(old, (list, tuple)) else [old] if old else []) + [note]
    if isinstance(old, str):
        new = "; ".join(new)
    return verdict.model_copy(update={"reasons": new}) if hasattr(verdict, "model_copy") else verdict.copy(update={"reasons": new})


def recheck_claims(
    claims: Iterable[Any],
    rows: Iterable[Any],
    meta: Any = None,
    previous_verdicts: Optional[Iterable[Any]] = None,
    *,
    recheck_statuses: Sequence[str] = UNRESOLVED_STATUSES,
    config: Optional[MatchConfig] = None,
    with_replies: bool = True,
    tone: str = DEFAULT_TONE,
    language: str = DEFAULT_LANGUAGE,
) -> List[Any]:
    """Re-run unresolved claims against a (newer) statement.

    previous_verdicts=None  -> every claim passed in is re-checked.
    previous_verdicts given -> only claims whose previous status is in
        ``recheck_statuses`` (default: "Can't verify yet") or that have no
        previous verdict are re-checked. Output order follows ``claims``.

    Already Verified / Likely-match claims keep their rows: statement rows whose
    12-digit reference belongs to such a claim are removed from the pool so a
    re-checked claim cannot consume them again, and an explanatory reason is
    added to any re-checked claim that shares that reference.
    (Rows without a reference cannot be tracked across statements — see README.)
    """
    claims = list(claims or [])
    rows = list(rows or [])
    prev: Dict[str, Any] = {}
    selected = claims
    consumed: Dict[str, Any] = {}  # reference -> (claim_id, status)
    if previous_verdicts is not None:
        prev = {str(getattr(v, "claim_id", "")): v for v in previous_verdicts}
        selected = []
        for c in claims:
            cid = str(getattr(c, "claim_id", ""))
            pv = prev.get(cid)
            if pv is None or getattr(pv, "status", None) in recheck_statuses:
                selected.append(c)
            elif getattr(pv, "status", None) in CONSUMING_STATUSES:
                r = _ref(getattr(c, "reference", None))
                if r and r not in consumed:
                    consumed[r] = (cid, getattr(pv, "status", None))
    pool = [r for r in rows if not (_row_refs(r) & set(consumed))] if consumed else rows

    results = list(match_claims(selected, pool, meta, config))
    if consumed:
        for i, c in enumerate(selected):
            r = _ref(getattr(c, "reference", None))
            if r in consumed:
                other, status = consumed[r]
                results[i] = _with_extra_reason(
                    results[i], f"Reference {r} already belongs to claim {other} ({status}); that statement credit is not reused.")
    return attach_replies(results, tone=tone, language=language) if with_replies else results


def merge_rechecked(previous_verdicts: Iterable[Any], rechecked: Iterable[Any]) -> List[Any]:
    """Previous verdicts with any re-checked ones swapped in (by claim_id); order preserved."""
    new = {str(getattr(v, "claim_id", "")): v for v in rechecked or []}
    return [new.get(str(getattr(v, "claim_id", "")), v) for v in previous_verdicts or []]


def recheck_changes(previous_verdicts: Iterable[Any], rechecked: Iterable[Any]) -> List[Dict[str, Any]]:
    """[{claim_id, before, after, changed}] for each re-checked claim, ordered by claim_id."""
    old = {str(getattr(v, "claim_id", "")): getattr(v, "status", None) for v in previous_verdicts or []}
    out = []
    for v in rechecked or []:
        cid = str(getattr(v, "claim_id", ""))
        out.append({"claim_id": cid, "before": old.get(cid), "after": getattr(v, "status", None),
                    "changed": old.get(cid) != getattr(v, "status", None)})
    return sorted(out, key=lambda d: d["claim_id"])
