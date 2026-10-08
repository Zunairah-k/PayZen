"""End to end: any statement file in -> StatementRow list + StatementMeta + ParseReport out.

    load  ->  find header  ->  propose mappings  ->  parse with each  ->
    verify with the balance chain  ->  keep the mapping the arithmetic confirms

Design rules
------------
* The model proposes, the math verifies. Both the deterministic mapper and the
  language model only PROPOSE column roles; the balance chain decides.
* Never reject a file for its format. If nothing verifies, the best attempt and
  a preview are returned with ``needs_confirmation=True`` so the UI can ask the
  user to confirm the mapping with one tap (``mapping_override``).
* Never raise to the caller. Problems become ``ok=False`` plus a plain message.
* Privacy: a language model sees only column names + a few MASKED sample rows
  (see ``mapping.mask_for_llm``). Nothing is written to disk.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .chain import STATUS_RANK, ChainResult, choose_order, describe_chain
from .coverage import compute_coverage
from .loader import RawTable, StatementIngestError, detect_header, load_statement, load_text, Source
from .mapping import (
    Mapping,
    default_llm_client,
    heuristic_mapping,
    llm_mapping,
    pick_sample_rows,
)
from .models import StatementMeta, StatementRow
from .normalize import header_tokens
from .parser import ParsedRow, ParseOutput, parse_rows
from .references import RefMatch, extract_name_hint, extract_reference
from .report import ParseReport, build_user_message, compute_parse_confidence

log = logging.getLogger(__name__)

LLM_POLICIES = ("always", "fallback", "never")


@dataclass
class IngestResult:
    ok: bool
    rows: List[StatementRow]
    meta: Optional[StatementMeta]
    report: ParseReport

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "rows": [r.to_dict() for r in self.rows],
            "meta": self.meta.to_dict() if self.meta else None,
            "report": self.report.to_dict(),
        }


@dataclass
class _Candidate:
    mapping: Mapping
    parsed: ParseOutput
    ordered: List[ParsedRow]
    chain: ChainResult
    label: str
    order: int

    def rank(self) -> Tuple:
        return (
            STATUS_RANK[self.chain.status],
            round(self.chain.pass_rate, 4),
            round(self.parsed.parse_rate, 4),
            self.mapping.completeness(),
            -self.order,
        )


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def ingest_statement(
    source: Source,
    filename: Optional[str] = None,
    *,
    llm_policy: str = "always",
    llm_client: Any = None,
    llm_model: Optional[str] = None,
    mapping_override: Optional[Mapping] = None,
    password: Optional[str] = None,
) -> IngestResult:
    """Read a statement file (path or bytes). See module docstring.

    llm_policy: 'always'   consult the language model for every file (default),
                'fallback' only when the deterministic mapper is not verified,
                'never'    fully offline.
    mapping_override: the user's confirmed mapping from the preview screen.
    password: for encrypted PDFs; used only to open the file, never stored.
    """
    try:
        table = load_statement(source, filename, password)
    except StatementIngestError as exc:
        return _failure(exc, source_name=filename)
    except Exception as exc:  # pragma: no cover - last line of defence
        log.exception("unexpected error while loading statement")
        return _failure(StatementIngestError("unexpected", f"Unexpected error while opening the file ({type(exc).__name__}).",
                                              "Try exporting the statement as CSV and upload again."), filename)
    return _ingest_table(table, llm_policy, llm_client, llm_model, mapping_override)


def ingest_text(
    text: str,
    *,
    llm_policy: str = "always",
    llm_client: Any = None,
    llm_model: Optional[str] = None,
    mapping_override: Optional[Mapping] = None,
) -> IngestResult:
    """Same as ingest_statement, for a statement pasted as text."""
    try:
        table = load_text(text)
    except StatementIngestError as exc:
        return _failure(exc, source_name="pasted text")
    return _ingest_table(table, llm_policy, llm_client, llm_model, mapping_override)


# --------------------------------------------------------------------------
# Internals
# --------------------------------------------------------------------------


def _failure(exc: StatementIngestError, source_name: Optional[str] = None) -> IngestResult:
    report = ParseReport(ok=False, source_name=source_name, errors=[exc.message], hint=exc.hint, error_code=exc.code)
    report.user_message = build_user_message(report, None)
    return IngestResult(False, [], None, report)


def _ingest_table(table: RawTable, llm_policy, llm_client, llm_model, mapping_override) -> IngestResult:
    try:
        return _run(table, llm_policy, llm_client, llm_model, mapping_override)
    except StatementIngestError as exc:
        res = _failure(exc, table.source_name)
        res.report.kind, res.report.encoding, res.report.delimiter = table.kind, table.encoding, table.delimiter
        return res
    except Exception as exc:
        log.exception("unexpected error while ingesting statement")
        return _failure(StatementIngestError(
            "unexpected", f"Unexpected error while reading this file ({type(exc).__name__}).",
            "Try exporting the statement as CSV and upload again."), table.source_name)


def _evaluate(mapping: Mapping, data_rows, names, label: str, order: int) -> Optional[_Candidate]:
    parsed = parse_rows(data_rows, mapping, names)
    if not parsed.rows:
        return None
    ordered, chain = choose_order(parsed.rows, parsed.opening_balance)
    return _Candidate(mapping, parsed, ordered, chain, label, order)


def _run(table: RawTable, llm_policy, llm_client, llm_model, mapping_override) -> IngestResult:
    if llm_policy not in LLM_POLICIES:
        raise ValueError(f"llm_policy must be one of {LLM_POLICIES}")

    header = detect_header(table)
    names = header.names
    data_rows = list(zip(table.line_numbers[header.data_start:], table.rows[header.data_start:]))
    if not data_rows:
        raise StatementIngestError("no_transactions", "No transaction rows were found below the header.")

    report = ParseReport(
        source_name=table.source_name, kind=table.kind, encoding=table.encoding, delimiter=table.delimiter,
        sheet=table.sheet, header_line=header.line, header_synthesized=header.synthesized, columns=list(names),
    )
    report.warnings.extend(table.warnings)

    header_norm = tuple(tuple(header_tokens(h)) for h in names)
    # rows used to GUESS the layout must not include repeated header rows (page breaks)
    all_cells = [c for _, c in data_rows if tuple(tuple(header_tokens(x)) for x in c) != header_norm]
    cands: List[_Candidate] = []
    counter = 0

    def consider(mapping: Optional[Mapping], label: str, repair: bool = True) -> None:
        """Parse with ``mapping`` (and, if the balance check fails, its debit/credit
        flipped twin), verify each, and remember the candidates."""
        nonlocal counter
        if mapping is None:
            return
        if not mapping.column_names:
            mapping.column_names = list(names)
        issues = mapping.validate(len(names))
        if issues:
            report.attempts.append({"source": label, "result": "rejected", "detail": "; ".join(issues)})
            return
        variants = [(mapping, label)]
        for variant, vlabel in variants:  # the flipped twin is appended while looping
            cand = _evaluate(variant, data_rows, names, vlabel, counter)
            counter += 1
            if cand is None:
                report.attempts.append({"source": vlabel, "result": "no rows parsed", "layout": variant.layout})
                continue
            cands.append(cand)
            report.attempts.append({
                "source": vlabel, "result": cand.chain.status, "rows": len(cand.parsed.rows),
                "chain": f"{cand.chain.passed}/{cand.chain.checked}", "layout": variant.layout,
            })
            if variant is mapping and repair and cand.chain.status != "pass":
                variants.append((mapping.swapped(), label + "+flip"))

    # ---- language-model availability ----------------------------------------
    client = None
    if llm_policy != "never" and mapping_override is None:
        client = llm_client if llm_client is not None else default_llm_client()
    report.llm = {
        "policy": llm_policy, "used": False, "available": client is not None,
        "sent_to_model": "column names + up to 6 masked sample rows (digits->9, letters->x). "
                         "No names, amounts, references or account numbers.",
    }
    if llm_policy != "never" and client is None and mapping_override is None:
        report.llm["note"] = "No language-model client configured (set GEMINI_API_KEY); used the deterministic mapper."

    # ---- propose + verify -------------------------------------------------------
    if mapping_override is not None:
        mapping_override.source = mapping_override.source or "user"
        consider(mapping_override, "user", repair=False)
    else:
        heuristic = heuristic_mapping(names, all_cells[:60])
        consider(heuristic, "heuristic")
        best_now = max(cands, key=lambda c: c.rank()) if cands else None
        need_llm = client is not None and (
            llm_policy == "always" or (llm_policy == "fallback" and (best_now is None or best_now.chain.status != "pass"))
        )
        if need_llm:
            sample = pick_sample_rows(all_cells)
            m, err = llm_mapping(names, sample, client=client, model=llm_model)
            report.llm["used"] = True
            if err:
                report.llm["error"] = err
                report.attempts.append({"source": "llm", "result": "unavailable", "detail": err})
            else:
                consider(m, "llm")
                if m is not None and heuristic is not None:
                    keys = ("date", "debit", "credit", "amount", "balance")
                    report.llm["agrees_with_deterministic"] = all(getattr(m, k) == getattr(heuristic, k) for k in keys)
            best_now = max(cands, key=lambda c: c.rank()) if cands else None
            if client is not None and best_now is not None and best_now.chain.status != "pass":
                feedback = describe_chain(best_now.chain) + " Mapping used: " + "; ".join(best_now.mapping.describe())
                m2, err2 = llm_mapping(names, sample, client=client, model=llm_model, feedback=feedback)
                if err2:
                    report.attempts.append({"source": "llm_retry", "result": "unavailable", "detail": err2})
                else:
                    consider(m2, "llm_retry")

    if not cands:
        fallback = heuristic_mapping(names, all_cells[:60]) if mapping_override is None else mapping_override
        report.mapping_summary = fallback.describe()
        report.mapping_source = fallback.source
        report.needs_confirmation = True
        report.errors.append("Could not identify the date and amount columns in this file.")
        report.hint = "Choose which column is the date, the debit/credit (or amount) and the balance."
        report.user_message = build_user_message(report, None)
        return IngestResult(False, [], None, report)

    best = max(cands, key=lambda c: c.rank())
    return _assemble(table, header, report, best)


def _assemble(table: RawTable, header, report: ParseReport, best: _Candidate) -> IngestResult:
    parsed, chain, mapping = best.parsed, best.chain, best.mapping
    ordered = best.ordered

    rows: List[StatementRow] = []
    for i, pr in enumerate(ordered, start=1):
        ref = extract_reference(pr.ref_text)
        if ref:
            ref = RefMatch(ref.value, "high", "column")
        else:
            ref = extract_reference(pr.narration)
        rows.append(StatementRow(
            row_id=f"S{i:05d}", datetime=pr.dt, narration=pr.narration, debit=pr.debit, credit=pr.credit,
            balance=pr.balance, extracted_reference=ref.value if ref else None,
            name_hint=extract_name_hint(pr.narration), source_page_or_row=pr.line,
            reference_confidence=ref.confidence if ref else None,
        ))

    has_time = sum(1 for p in ordered if p.has_time) * 2 >= len(ordered)
    start, end = compute_coverage([r.datetime for r in rows], has_time)

    warnings = list(report.warnings)
    if parsed.date_order_status == "assumed":
        warnings.append("Dates like 06/10/2026 are ambiguous in this file; assumed day/month/year.")
    elif parsed.date_order_status == "conflict":
        warnings.append("The date column contains conflicting day/month orders; assumed day/month/year.")
    if not has_time:
        warnings.append("This statement has dates but no times; time-based matching can only be day-level.")
    if chain.status == "partial":
        warnings.append("The balance check failed on a few rows: " + describe_chain(chain))
    elif chain.status == "fail":
        warnings.append("The balance check failed: " + describe_chain(chain))
    elif chain.status == "unavailable":
        warnings.append("There is no balance column, so the numbers could not be self-verified.")
    elif chain.evidence == "weak":
        warnings.append(f"Only {chain.checked} rows could be balance-checked, so the check is weak evidence.")
    if parsed.lost:
        warnings.append(f"{len(parsed.lost)} rows that looked like transactions could not be read "
                        f"(first: line {parsed.lost[0][0]}, {parsed.lost[0][1]}).")
    credit_refs = Counter(r.extracted_reference for r in rows if r.extracted_reference and r.credit)
    dup = sum(1 for _, n in credit_refs.items() if n > 1)
    if dup:
        warnings.append(f"{dup} reference number(s) appear on more than one credit row in the statement itself.")
    if not any(r.extracted_reference for r in rows):
        warnings.append("No 12-digit references were found in the narrations; matching will rely on amount, time and name.")

    complete = mapping.completeness() >= 5 or (mapping.date is not None and bool(mapping.narration)
                                                and any(v is not None for v in (mapping.debit, mapping.credit, mapping.amount)))
    confidence = compute_parse_confidence(chain, parsed.parse_rate, parsed.date_order_status,
                                          header.synthesized, complete)
    needs_confirmation = chain.status != "pass" or confidence < 0.8 or parsed.parse_rate < 0.95

    report.ok = True
    report.mapping_summary = mapping.describe()
    report.mapping_source = best.label
    report.date_order, report.date_order_status = parsed.date_order, parsed.date_order_status
    report.rows_parsed = len(rows)
    report.rows_skipped = len(parsed.skipped)
    report.rows_lost = len(parsed.lost)
    report.wrapped_rows_stitched = parsed.stitched
    report.skipped_samples = [{"line": ln, "reason": why} for ln, why in parsed.skipped[:10]]
    report.lost_samples = [{"line": ln, "reason": why} for ln, why in parsed.lost[:10]]
    report.chain = chain.to_dict()
    report.warnings = warnings
    report.needs_confirmation = needs_confirmation
    report.parse_confidence = confidence
    report.user_message = build_user_message(report, chain)

    meta = StatementMeta(
        coverage_start=start, coverage_end=end, mapping_used=mapping.to_dict(),
        balance_chain_result=chain.to_dict(), parse_confidence=confidence, row_count=len(rows),
        warnings=warnings, has_time_of_day=has_time, needs_confirmation=needs_confirmation,
        source_name=table.source_name,
    )
    return IngestResult(True, rows, meta, report)