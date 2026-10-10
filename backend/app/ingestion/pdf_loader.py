"""Text-PDF statements -> the same raw grid of text cells the CSV loader produces.

Tables are read page by page; the header repeated on every page is dropped later
by the parser. A password is used only to open the file in memory and is never
stored or logged. Scanned PDFs (no selectable text) get a clear message.

Reading order of strategies, per page:
  1. word-coordinate reader (_word_rows): finds the header words (Date / Particulars /
     Deposits / Withdrawals / Balance), then puts every word in a column by its x
     position and groups words into lines by y. This is immune to wrapped narrations
     and to vertically centred cells, where pdfplumber's table finders cut the first
     letter off a word or merge columns.
  2. pdfplumber ruled-line tables, 3. text-aligned tables, 4. plain text lines.
"""

from __future__ import annotations

import io
import re
from typing import Any, Dict, List, Optional, Tuple

_TEXT_SETTINGS = {"vertical_strategy": "text", "horizontal_strategy": "text"}


def _clean(cell: object) -> str:
    s = "" if cell is None else str(cell)
    s = re.sub(r"(?<=\d{5})\s*\n\s*(?=\d)", "", s)  # a long number split across lines
    return " ".join(s.split())


def _table_rows(page, settings=None) -> List[List[str]]:
    tables = page.extract_tables(settings) if settings else page.extract_tables()
    out: List[List[str]] = []
    for tbl in tables or []:
        for row in tbl:
            cells = [_clean(c) for c in row]
            if any(cells):
                out.append(cells)
    return out


def _text_rows(page) -> List[List[str]]:
    out: List[List[str]] = []
    for line in (page.extract_text(layout=True) or "").splitlines():
        cells = [c.strip() for c in re.split(r"\s{2,}|\t", line.strip())]
        if any(cells):
            out.append(cells)
    return out


def _tabular(rows: List[List[str]]) -> int:
    return sum(1 for r in rows if sum(1 for c in r if c) >= 3)


# --------------------------------------------------------------------------
# Word-coordinate reader
# --------------------------------------------------------------------------

_AMT_RE = re.compile(r"^\(?-?\d[\d,]*\.\d{2}\)?$")
_DATE_RE = re.compile(r"^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}$")
_SUFFIX_WORDS = {"cr", "dr", "cr.", "dr."}

_HEADER_ROLES = {
    "date": {"date", "dt"},
    "narration": {"particulars", "narration", "description", "details", "remarks", "narrative"},
    "credit": {"deposits", "deposit", "credit", "credits", "cr"},
    "debit": {"withdrawals", "withdrawal", "debit", "debits", "dr"},
    "balance": {"balance", "bal"},
}


def _group_lines(words: List[Dict[str, Any]], tol: float = 3.0) -> List[List[Dict[str, Any]]]:
    """Words -> visual lines (same y within ``tol`` points), each sorted left to right."""
    lines: List[List[Any]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(w["top"] - lines[-1][0]) <= tol:
            lines[-1][1].append(w)
        else:
            lines.append([w["top"], [w]])
    return [sorted(ws, key=lambda w: w["x0"]) for _, ws in lines]


def _find_header(lines: List[List[Dict[str, Any]]]) -> Optional[Tuple[int, Dict[str, Dict[str, Any]]]]:
    """Index of the first line holding Date + Narration + a money column + Balance."""
    for i, line in enumerate(lines):
        found: Dict[str, Dict[str, Any]] = {}
        for w in line:
            token = re.sub(r"[^a-z]", "", w["text"].lower())
            for role, names in _HEADER_ROLES.items():
                if token in names and role not in found:
                    found[role] = w
                    break
        if {"date", "narration", "balance"} <= found.keys() and ({"credit", "debit"} & found.keys()):
            return i, found
    return None


def _cx(w: Dict[str, Any]) -> float:
    return (w["x0"] + w["x1"]) / 2.0


def _word_rows(page, anchors: Optional[Dict[str, Any]] = None) -> Tuple[Optional[List[List[str]]], Optional[Dict[str, Any]]]:
    """Read one page by word coordinates. Returns (rows or None, anchors to reuse on the next page).

    Rows have the same width on every page: date, narration, then the money columns
    (deposit / withdrawal / balance) in the order the header lists them.
    """
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False, x_tolerance=2, y_tolerance=3)
    if not words:
        return None, anchors
    lines = _group_lines(words)

    header_row: Optional[List[str]] = None
    start = 0
    found = _find_header(lines)
    if found is not None:
        hi, hdr = found
        money_roles = sorted((r for r in ("credit", "debit", "balance") if r in hdr), key=lambda r: hdr[r]["x0"])
        anchors = {
            "roles": money_roles,
            "centers": {r: _cx(hdr[r]) for r in money_roles},
            "money_left": min(hdr[r]["x0"] for r in money_roles) - 15.0,
            "narr_x0": hdr["narration"]["x0"],
            "names": {r: hdr[r]["text"] for r in ("date", "narration", *money_roles)},
        }
        header_row = [anchors["names"]["date"], anchors["names"]["narration"]] + [anchors["names"][r] for r in money_roles]
        start = hi + 1
    elif anchors is None:
        return None, None

    body = lines[start:]
    roles: List[str] = anchors["roles"]
    centers: Dict[str, float] = anchors["centers"]
    money_left: float = anchors["money_left"]

    # ---- date column: first words of lines that look like dates, left of the Particulars header
    date_ws = [ln[0] for ln in body if _DATE_RE.match(ln[0]["text"]) and ln[0]["x0"] < anchors["narr_x0"]]
    if not date_ws:
        rows0 = [header_row] if header_row else []
        return rows0, anchors
    xs = sorted(w["x0"] for w in date_ws)
    med = xs[len(xs) // 2]
    date_right = max(w["x1"] for w in date_ws if abs(w["x0"] - med) <= 30)

    # ---- money columns: merge overlapping x ranges of amount words, map each range to its nearest header
    money_ws = [w for ln in body for w in ln if w["x0"] >= money_left and _AMT_RE.match(w["text"])]
    spans: List[List[float]] = []
    for w in sorted(money_ws, key=lambda w: w["x0"]):
        if spans and w["x0"] <= spans[-1][1] + 2:
            spans[-1][1] = max(spans[-1][1], w["x1"])
        else:
            spans.append([w["x0"], w["x1"]])

    def role_of(w: Dict[str, Any]) -> str:
        for lo, hi_ in spans:
            if lo - 0.5 <= w["x0"] and w["x1"] <= hi_ + 0.5:
                c = (lo + hi_) / 2.0
                return min(roles, key=lambda r: abs(centers[r] - c))
        return min(roles, key=lambda r: abs(centers[r] - _cx(w)))

    out: List[List[str]] = [header_row] if header_row else []
    for ln in body:
        cells: Dict[str, List[str]] = {"date": [], "narration": [], **{r: [] for r in roles}}
        last_money: Optional[str] = None
        for w in ln:
            t = w["text"]
            if w["x1"] <= date_right + 2 and w["x0"] < anchors["narr_x0"]:
                cells["date"].append(t)
            elif w["x0"] >= money_left and _AMT_RE.match(t):
                last_money = role_of(w)
                cells[last_money].append(t)
            elif w["x0"] >= money_left and t.lower() in _SUFFIX_WORDS and last_money and cells[last_money]:
                cells[last_money][-1] += " " + t  # "9,734.67 Cr"
            else:
                cells["narration"].append(t)
        row = [" ".join(cells["date"]), " ".join(cells["narration"])] + [" ".join(cells[r]) for r in roles]
        if any(row):
            out.append(row)
    return out, anchors


def _is_password_error(exc: BaseException) -> bool:
    """pdfplumber may wrap pdfminer's PDFPasswordIncorrect, so look inside the exception too."""
    seen = [exc, exc.__cause__, exc.__context__] + [a for a in getattr(exc, "args", ()) if isinstance(a, BaseException)]
    return any(e is not None and "Password" in type(e).__name__ for e in seen)


def load_pdf_rows(data: bytes, password: Optional[str] = None,
                  allow_vision: bool = False) -> Tuple[List[List[str]], List[int], List[str]]:
    """Return (rows, line_numbers, warnings). Raises StatementIngestError with a
    machine-readable code: pdf_password_required / pdf_password_incorrect /
    pdf_scanned / pdf_unreadable."""
    from .loader import StatementIngestError  # lazy: loader imports this module

    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover
        raise StatementIngestError(
            "pdf_unsupported", "PDF support is not installed on the server.",
            "Download the statement as CSV or XLSX, or paste the table text.") from exc

    try:
        pdf = pdfplumber.open(io.BytesIO(data), password=password or None)
    except Exception as exc:
        if _is_password_error(exc):
            if password:
                raise StatementIngestError(
                    "pdf_password_incorrect", "That password did not open the PDF.",
                    "Check the password and try again.") from exc
            raise StatementIngestError(
                "pdf_password_required", "This PDF is password protected.",
                "Enter its password. It is used only to open the file and is never stored.") from exc
        raise StatementIngestError(
            "pdf_unreadable", "Could not open this PDF.",
            "Download the statement as CSV or XLSX from net banking, or paste the table text.") from exc

    rows: List[List[str]] = []
    lines: List[int] = []
    warnings: List[str] = []
    word_pages = 0
    with pdf:
        pages = list(pdf.pages)
        if not any((p.extract_text() or "").strip() for p in pages):
            if not allow_vision:
                raise StatementIngestError(
                    "pdf_scanned", "This PDF has no selectable text (it looks scanned).",
                    "Tick the consent box to have it read as images by a vision model, "
                    "or download CSV or XLSX from net banking.")
            from .vision_loader import load_page_images_rows

            images = []
            for page in pages[:10]:  # cap the number of pages sent to the model
                buf = io.BytesIO()
                page.to_image(resolution=150).original.save(buf, format="PNG")
                images.append(buf.getvalue())
            return load_page_images_rows(images, True)
        anchors: Optional[Dict[str, Any]] = None
        for page in pages:
            page_rows: Optional[List[List[str]]] = None
            try:
                page_rows, anchors = _word_rows(page, anchors)
            except Exception:  # never let the new reader break the older strategies
                page_rows = None
            if page_rows is not None:
                word_pages += 1
            else:
                page_rows = _table_rows(page)
                if _tabular(page_rows) < 2:
                    alt = _table_rows(page, _TEXT_SETTINGS)
                    if _tabular(alt) > _tabular(page_rows):
                        page_rows = alt
                if _tabular(page_rows) < 2:
                    page_rows = _text_rows(page)
            for r in page_rows:
                rows.append(r)
                lines.append(len(rows))
    warnings.append(f"Read {len(pages)} PDF page(s); table text was extracted page by page.")
    if word_pages:
        warnings.append(f"{word_pages} page(s) were read by word position (header-anchored columns).")
    return rows, lines, warnings