"""Read a statement file into a plain grid of text cells and find the header row.

Supported now: CSV (any delimiter / encoding), XLSX, and pasted text.
PDF / scanned / photo statements are Day-2 work; they fail with a clear,
actionable message instead of a stack trace (``StatementIngestError``).

The loader never interprets money or dates. It only:
  * decodes the bytes (BOM, UTF-8, charset detection, cp1252 fallback),
  * finds the delimiter by looking at which one gives consistent column counts,
  * returns every non-empty row with its ORIGINAL line / sheet-row number,
  * drops fully blank columns (spacer columns, unused merged-cell leftovers),
  * finds the true header row among junk lines (bank name, address, period...).
"""

from __future__ import annotations

import csv
import io
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

from .normalize import clean_cell, header_tokens, is_amount_like, is_date_like

MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 100_000
_CANDIDATE_DELIMITERS = [",", ";", "\t", "|"]

csv.field_size_limit(10_000_000)


class StatementIngestError(Exception):
    """A problem the user can act on. ``code`` is machine readable."""

    def __init__(self, code: str, message: str, hint: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


@dataclass
class RawTable:
    rows: List[List[str]]
    line_numbers: List[int]  # 1-based line (CSV) or sheet row (XLSX) of each row
    kind: str  # 'csv' | 'xlsx' | 'text'
    source_name: Optional[str] = None
    encoding: Optional[str] = None
    delimiter: Optional[str] = None
    sheet: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class HeaderInfo:
    index: Optional[int]  # index into RawTable.rows (None when synthesized)
    names: List[str]
    data_start: int  # index of the first data row
    synthesized: bool
    confidence: float
    line: Optional[int]  # original line number of the header row


# --------------------------------------------------------------------------
# Public loaders
# --------------------------------------------------------------------------

Source = Union[str, os.PathLike, bytes, bytearray]


def load_statement(source: Source, filename: Optional[str] = None, password: Optional[str] = None) -> RawTable:
    """Load a statement from a path or raw bytes."""
    if isinstance(source, (str, os.PathLike)):
        path = Path(source)
        if not path.is_file():
            raise StatementIngestError("not_found", f"File not found: {path.name}")
        if path.stat().st_size > MAX_BYTES:
            raise _too_big()
        data = path.read_bytes()
        name = filename or path.name
    else:
        data = bytes(source)
        name = filename
    if len(data) > MAX_BYTES:
        raise _too_big()
    if not data.strip():
        raise StatementIngestError("empty", "The file is empty.", "Choose the statement file you downloaded.")

    head = data[:8]
    if head.startswith(b"%PDF"):
        from .pdf_loader import load_pdf_rows

        rows, lines, pdf_warnings = load_pdf_rows(data, password)
        return _finish(rows, lines, None, pdf_warnings, kind="pdf", source_name=name)
    
    if head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8"):
        raise StatementIngestError(
            "image_unsupported",
            "Photos of statements are not supported in this build yet.",
            "Download the statement as CSV or XLSX from net banking, or paste the table text.",
        )
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        raise StatementIngestError(
            "xls_unsupported",
            "This is an old .xls file.",
            "Open it in Excel and use Save As -> .xlsx (or .csv), then upload again.",
        )
    if head.startswith(b"PK\x03\x04"):
        return _finish(*_load_xlsx(data), kind="xlsx", source_name=name)

    text, encoding = _decode(data)
    table = _table_from_text(text, kind="csv", source_name=name)
    table.encoding = encoding
    return table


def load_text(text: str, source_name: Optional[str] = "pasted text") -> RawTable:
    """Load a statement pasted as text (comma / tab / semicolon / column-aligned)."""
    if not text or not text.strip():
        raise StatementIngestError("empty", "Nothing was pasted.")
    if len(text) > MAX_BYTES:
        raise _too_big()
    table = _table_from_text(text, kind="text", source_name=source_name)
    table.encoding = "text"
    return table


def _too_big() -> StatementIngestError:
    return StatementIngestError(
        "too_large",
        f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.",
        "Export a shorter date range and upload again.",
    )


# --------------------------------------------------------------------------
# Text / CSV
# --------------------------------------------------------------------------


def _decode(data: bytes) -> Tuple[str, str]:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8"), "utf-8-sig"
    if data.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return data.decode("utf-32"), "utf-32"
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16"), "utf-16"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes  # optional dependency

        best = from_bytes(data).best()
        if best is not None and best.encoding:
            return str(best), best.encoding
    except Exception:  # pragma: no cover - detection is best effort
        pass
    try:
        return data.decode("cp1252"), "cp1252"
    except UnicodeDecodeError:
        return data.decode("latin-1"), "latin-1"


def _detect_delimiter(lines: Sequence[str]) -> Optional[str]:
    best: Optional[str] = None
    best_score = 0
    for delim in _CANDIDATE_DELIMITERS:
        counts: Counter = Counter()
        try:
            for row in csv.reader(lines, delimiter=delim):
                if any(c.strip() for c in row):
                    counts[len(row)] += 1
        except csv.Error:
            continue
        score = max((c * (n - 1) for n, c in counts.items() if n >= 2), default=0)
        if score > best_score:
            best, best_score = delim, score
    return best


def _table_from_text(text: str, kind: str, source_name: Optional[str]) -> RawTable:
    text = text.lstrip("\ufeff")
    lines = text.splitlines()
    offset = 0
    delimiter: Optional[str] = None
    if lines and re.match(r"(?i)^sep=(.)\s*$", lines[0]):
        delimiter = lines[0].strip()[4]
        lines = lines[1:]
        offset = 1
    sample = [ln for ln in lines if ln.strip()][:300]
    warnings: List[str] = []
    if delimiter is None:
        delimiter = _detect_delimiter(sample)

    rows: List[List[str]] = []
    line_numbers: List[int] = []
    if delimiter is None:
        warnings.append("No delimiter found; split columns on tabs or runs of spaces.")
        for i, ln in enumerate(lines, start=1 + offset):
            cells = [clean_cell(c) for c in re.split(r"\t|\s{2,}", ln.strip())]
            if any(cells):
                rows.append(cells)
                line_numbers.append(i)
    else:
        reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)
        try:
            for row in reader:
                cells = [clean_cell(c) for c in row]
                if any(cells):
                    rows.append(cells)
                    line_numbers.append(reader.line_num + offset)
                if len(rows) > MAX_ROWS:
                    raise StatementIngestError(
                        "too_many_rows", f"More than {MAX_ROWS:,} rows.", "Export a shorter date range."
                    )
        except csv.Error as exc:
            raise StatementIngestError("csv_unreadable", f"Could not read the CSV: {exc}") from exc

    table = _finish(rows, line_numbers, None, warnings, kind=kind, source_name=source_name)
    table.delimiter = delimiter if delimiter is not None else "whitespace"
    return table


# --------------------------------------------------------------------------
# XLSX
# --------------------------------------------------------------------------


def _cell_to_str(v: object) -> str:
    import datetime as dt

    if v is None:
        return ""
    if isinstance(v, dt.datetime):
        if v.time() == dt.time(0, 0):
            return v.strftime("%Y-%m-%d")
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, dt.date):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, dt.time):
        return v.strftime("%H:%M:%S")
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return ""
        return format(Decimal(repr(v)), "f")
    return clean_cell(v)


def _load_xlsx(data: bytes) -> Tuple[List[List[str]], List[int], Optional[str], List[str]]:
    try:
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise StatementIngestError(
            "xlsx_unreadable",
            "Could not open this Excel file.",
            "Check that it is a real .xlsx (not password protected), or export it as CSV.",
        ) from exc

    warnings: List[str] = []
    best: Optional[Tuple[int, str, List[List[str]], List[int]]] = None
    try:
        for ws in wb.worksheets:
            if getattr(ws, "sheet_state", "visible") != "visible":
                continue
            try:
                ws.reset_dimensions()
            except Exception:  # pragma: no cover
                pass
            rows: List[List[str]] = []
            lines: List[int] = []
            for i, raw in enumerate(ws.iter_rows(values_only=True), start=1):
                cells = [_cell_to_str(c) for c in raw]
                if any(cells):
                    rows.append(cells)
                    lines.append(i)
                if len(rows) > MAX_ROWS:
                    raise StatementIngestError(
                        "too_many_rows", f"More than {MAX_ROWS:,} rows.", "Export a shorter date range."
                    )
            score = sum(1 for r in rows if sum(1 for c in r if c) >= 3)
            if best is None or score > best[0]:
                best = (score, ws.title, rows, lines)
        visible = [w for w in wb.worksheets if getattr(w, "sheet_state", "visible") == "visible"]
        if len(visible) > 1 and best is not None:
            warnings.append(f"Workbook has {len(visible)} sheets; used '{best[1]}' (the one with most table rows).")
    finally:
        wb.close()

    if best is None or not best[2]:
        raise StatementIngestError("empty", "The workbook has no data.")
    return best[2], best[3], best[1], warnings


# --------------------------------------------------------------------------
# Shared finishing
# --------------------------------------------------------------------------


def _finish(
    rows: List[List[str]],
    line_numbers: List[int],
    sheet: Optional[str],
    warnings: List[str],
    kind: str,
    source_name: Optional[str],
) -> RawTable:
    if not rows:
        raise StatementIngestError("empty", "No rows could be read from the file.")
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    keep = [j for j in range(width) if any(r[j] for r in rows)]
    if len(keep) < width:
        rows = [[r[j] for j in keep] for r in rows]
    return RawTable(rows=rows, line_numbers=line_numbers, kind=kind, source_name=source_name,
                    sheet=sheet, warnings=list(warnings))


# --------------------------------------------------------------------------
# Header detection
# --------------------------------------------------------------------------

_HEADER_WORDS = {
    "date", "dt", "narration", "description", "particulars", "details", "remarks", "debit",
    "credit", "withdrawal", "withdrawals", "deposit", "deposits", "balance", "bal", "amount",
    "amt", "ref", "reference", "utr", "rrn", "cheque", "chq", "txn", "transaction", "tran",
    "value", "dr", "cr", "type", "time", "timestamp", "payee", "memo", "narrative", "mode",
}


def _dataish(cells: Sequence[str]) -> bool:
    return any(is_date_like(c) for c in cells if c) and any(is_amount_like(c) for c in cells if c)


def detect_header(table: RawTable) -> HeaderInfo:
    """Find the real header row among junk lines.

    A header row: at least 3 filled cells, mostly words (not numbers), no date
    value inside, contains header vocabulary (date, narration, debit, ...),
    and is followed by rows that look like transactions (a date plus an amount).
    If no such row exists the first transaction-looking row is used and
    generic column names are invented (never rejecting the file).
    """
    rows = table.rows
    width = len(rows[0]) if rows else 0
    candidates = []  # (index, hits, follow, score)

    for i in range(min(len(rows), 80)):
        cells = [c for c in rows[i] if c]
        if len(cells) < 3:
            continue
        if any(is_date_like(c) for c in cells):
            continue
        if sum(1 for c in cells if is_amount_like(c)) / len(cells) > 0.3:
            continue
        hits = sum(1 for c in cells if set(header_tokens(c)) & _HEADER_WORDS)
        window = rows[i + 1: i + 9]
        follow = (sum(1 for r in window if _dataish(r)) / len(window)) if window else 0.0
        candidates.append((i, hits, follow, hits * 3 + follow * 5 + (1 if len(cells) >= 4 else 0)))

    best_i, best_hits, best_follow = None, 0, 0.0
    if candidates:
        top = max(candidates, key=lambda c: c[3])
        # A header repeated later (page break) can score higher than the real first one,
        # so take the EARLIEST row that looks equally header-like and is followed by data.
        first = next(c for c in candidates if c[1] >= top[1] and c[2] > 0) if top[2] > 0 else top
        best_i, best_hits, best_follow = first[0], first[1], first[2]

    if best_i is not None and (best_hits >= 2 or (best_hits >= 1 and best_follow >= 0.4) or best_follow >= 0.6):
        names = [c if c else f"col_{j + 1}" for j, c in enumerate(rows[best_i])]
        confidence = min(1.0, 0.4 + 0.15 * best_hits + 0.3 * best_follow)
        return HeaderInfo(best_i, names, best_i + 1, False, round(confidence, 2), table.line_numbers[best_i])

    for j, r in enumerate(rows):
        if _dataish(r):
            names = [f"col_{k + 1}" for k in range(width)]
            table.warnings.append("No header row found; columns were inferred from their contents.")
            return HeaderInfo(None, names, j, True, 0.3, None)

    raise StatementIngestError(
        "no_transactions",
        "No transaction rows (a date plus an amount) were found in this file.",
        "Check you uploaded the statement itself, and that it is not a summary or a different report.",
    )