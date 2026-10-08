"""Text-PDF statements -> the same raw grid of text cells the CSV loader produces.

Tables are read page by page; the header repeated on every page is dropped later
by the parser. A password is used only to open the file in memory and is never
stored or logged. Scanned PDFs (no selectable text) get a clear message.
"""

from __future__ import annotations

import io
import re
from typing import List, Optional, Tuple

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
        for page in pages:
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
    return rows, lines, [f"Read {len(pages)} PDF page(s); table text was extracted page by page."]