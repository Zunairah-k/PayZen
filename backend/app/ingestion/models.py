"""Data contracts for statement ingestion (fields frozen in the team contracts doc)."""

from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional


def to_plain(obj: Any) -> Any:
    """Dataclasses / Decimal / datetime -> JSON-friendly values (Decimal becomes str, exact)."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_plain(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (dt.datetime, dt.date, dt.time)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_plain(v) for v in obj]
    return obj


@dataclass
class StatementRow:
    row_id: str
    datetime: dt.datetime
    narration: str
    debit: Optional[Decimal] = None
    credit: Optional[Decimal] = None
    balance: Optional[Decimal] = None
    extracted_reference: Optional[str] = None
    name_hint: Optional[str] = None
    source_page_or_row: Optional[int] = None
    reference_confidence: Optional[str] = None  # 'high' | 'medium' | 'low' | None

    def to_dict(self) -> Dict[str, Any]:
        return to_plain(self)


@dataclass
class StatementMeta:
    coverage_start: Optional[dt.datetime]
    coverage_end: Optional[dt.datetime]
    mapping_used: Dict[str, Any]
    balance_chain_result: Dict[str, Any]
    parse_confidence: float
    row_count: int
    warnings: List[str] = field(default_factory=list)
    has_time_of_day: bool = True
    needs_confirmation: bool = False
    source_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return to_plain(self)