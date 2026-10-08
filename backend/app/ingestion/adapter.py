"""Convert ingestion output to the team's shared API models (backend/app/models.py)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..models import StatementMeta as SharedMeta
from ..models import StatementRow as SharedRow
from .pipeline import IngestResult


def _f(x: Any) -> Optional[float]:
    return float(x) if x is not None else None


def _flatten_mapping(mapping_used: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {"source": str(mapping_used.get("source", "")), "layout": str(mapping_used.get("layout", ""))}
    for role, name in (mapping_used.get("column_names") or {}).items():
        if isinstance(name, list):
            name = "; ".join(str(n) for n in name if n)
        if name:
            out[role] = str(name)
    return out


def to_shared(result: IngestResult) -> Tuple[List[SharedRow], SharedMeta]:
    """(rows, meta) in the shared models. On failure: no rows and a meta whose warnings carry the message."""
    if not result.ok or result.meta is None:
        return [], SharedMeta(warnings=[result.report.user_message or "The statement could not be read."])
    rows = [
        SharedRow(
            row_id=r.row_id, datetime=r.datetime.isoformat(), narration=r.narration,
            debit=_f(r.debit), credit=_f(r.credit), balance=_f(r.balance),
            extracted_reference=r.extracted_reference, name_hint=r.name_hint,
            source_page_or_row=str(r.source_page_or_row) if r.source_page_or_row is not None else None,
        )
        for r in result.rows
    ]
    m = result.meta
    chain = m.balance_chain_result or {}
    meta = SharedMeta(
        coverage_start=m.coverage_start.isoformat() if m.coverage_start else None,
        coverage_end=m.coverage_end.isoformat() if m.coverage_end else None,
        mapping_used=_flatten_mapping(m.mapping_used),
        balance_chain_result=f"{chain.get('status', 'unavailable')}: {chain.get('note', '')}".strip(),
        parse_confidence=m.parse_confidence, row_count=m.row_count, warnings=list(m.warnings),
    )
    return rows, meta