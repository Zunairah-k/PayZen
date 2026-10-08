"""The parse report: what was understood, what was skipped, and how sure we are.

It is shown in the UI preview ("how your file was understood") and feeds
StatementMeta, so a user (and a judge) can see exactly what happened.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .chain import ChainResult, describe_chain
from .models import to_plain

# Confidence is a transparent rule, not a trained probability:
#   base by balance-chain outcome, times the share of data rows that parsed,
#   minus small penalties for ambiguity.
_BASE_CONFIDENCE = {"pass": 0.97, "partial": 0.70, "unavailable": 0.60, "fail": 0.30}


def compute_parse_confidence(
    chain: ChainResult,
    parse_rate: float,
    date_order_status: str,
    header_synthesized: bool,
    mapping_complete: bool,
) -> float:
    conf = _BASE_CONFIDENCE[chain.status]
    if chain.status == "pass" and chain.evidence == "weak":
        conf = 0.85  # only a handful of rows were checkable
    conf *= parse_rate
    if date_order_status == "assumed":
        conf -= 0.03
    elif date_order_status == "conflict":
        conf -= 0.10
    if header_synthesized:
        conf -= 0.10
    if not mapping_complete:
        conf -= 0.10
    return round(max(0.0, min(1.0, conf)), 2)


@dataclass
class ParseReport:
    ok: bool = False
    source_name: Optional[str] = None
    kind: Optional[str] = None
    encoding: Optional[str] = None
    delimiter: Optional[str] = None
    sheet: Optional[str] = None
    header_line: Optional[int] = None
    header_synthesized: bool = False
    columns: List[str] = field(default_factory=list)
    mapping_summary: List[str] = field(default_factory=list)
    mapping_source: Optional[str] = None
    date_order: Optional[str] = None
    date_order_status: Optional[str] = None
    rows_parsed: int = 0
    rows_skipped: int = 0
    rows_lost: int = 0
    wrapped_rows_stitched: int = 0
    skipped_samples: List[Dict[str, Any]] = field(default_factory=list)
    lost_samples: List[Dict[str, Any]] = field(default_factory=list)
    chain: Dict[str, Any] = field(default_factory=dict)
    attempts: List[Dict[str, Any]] = field(default_factory=list)
    llm: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    hint: Optional[str] = None
    error_code: Optional[str] = None
    needs_confirmation: bool = False
    parse_confidence: float = 0.0
    user_message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return to_plain(self)


def build_user_message(report: ParseReport, chain: Optional[ChainResult]) -> str:
    """One plain-language paragraph for the preview screen."""
    if not report.ok:
        return (report.errors[0] if report.errors else "The file could not be read.") + \
            (f" {report.hint}" if report.hint else "")
    parts = [f"Read {report.rows_parsed} transactions"]
    if report.header_line:
        parts[0] += f" (header found on line {report.header_line})"
    parts[0] += "."
    if chain is not None:
        parts.append(describe_chain(chain))
    if report.wrapped_rows_stitched:
        parts.append(f"{report.wrapped_rows_stitched} wrapped narration lines were joined to their transaction.")
    if report.rows_lost:
        parts.append(f"{report.rows_lost} rows that looked like transactions could not be read.")
    if report.needs_confirmation:
        parts.append("Please check the column preview below and fix it if anything looks wrong.")
    return " ".join(parts)