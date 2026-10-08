"""Plain-language wording for everything statement ingestion can tell a user.

Two things live here, both pure functions of the ingestion result:

1. ERROR_TABLE      error code -> what to say and what the user can do next.
2. build_preview()  the "ask once" preview shown after a statement is read:
                    either a green tick, or ONE question (never a stream of them).

The wording follows the project rules: simple words, no blame, no jargon, and
never the words "fake" or "fraud". Technical detail stays in the parse report.

Nothing here changes how a file is parsed. It only explains the outcome.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

# needs: what the screen must collect before trying again
#   'password' | 'consent' | 'mapping' | None
ERROR_TABLE: Dict[str, Dict[str, Any]] = {
    "empty": {
        "title": "This file is empty",
        "message": "There is nothing to read in this file.",
        "action": "Choose the statement you downloaded from your bank and try again.",
        "needs": None,
    },
    "not_found": {
        "title": "File not found",
        "message": "We could not find that file.",
        "action": "Choose the file again.",
        "needs": None,
    },
    "too_large": {
        "title": "This file is too big",
        "message": "The file is larger than we can read in one go.",
        "action": "Download a shorter date range (for example one month) and upload that.",
        "needs": None,
    },
    "too_many_rows": {
        "title": "Too many rows",
        "message": "This statement has more rows than we can read in one go.",
        "action": "Download a shorter date range (for example one month) and upload that.",
        "needs": None,
    },
    "csv_unreadable": {
        "title": "We could not read this as a table",
        "message": "The file did not look like a table of rows and columns.",
        "action": "Download the statement again as CSV or Excel (.xlsx). If that fails, paste the table as text.",
        "needs": None,
    },
    "xlsx_unreadable": {
        "title": "We could not open this Excel file",
        "message": "The Excel file could not be opened. It may be damaged or password protected.",
        "action": "Remove the password in Excel, or save the statement as CSV, then upload again.",
        "needs": None,
    },
    "xls_unsupported": {
        "title": "This is an old Excel file (.xls)",
        "message": "Old .xls files cannot be read directly.",
        "action": "Open it in Excel, choose Save As, pick .xlsx (or CSV), and upload that file.",
        "needs": None,
    },
    "no_transactions": {
        "title": "No transactions found",
        "message": "We could not find any rows that have both a date and an amount.",
        "action": "Check that this is the statement itself (not a summary or another report) and try again.",
        "needs": None,
    },
    "columns_unclear": {
        "title": "We could not tell which column is which",
        "message": "We found the table, but could not work out which columns hold the date, the amounts and the balance.",
        "action": "Pick the date, the debit and credit (or amount) and the balance columns once, and we will read it again.",
        "needs": "mapping",
    },
    "pdf_password_required": {
        "title": "This PDF has a password",
        "message": "The PDF is protected, so it cannot be opened without its password.",
        "action": "Enter the password. It is used only to open this file and is not saved.",
        "needs": "password",
    },
    "pdf_password_incorrect": {
        "title": "That password did not work",
        "message": "The password you entered did not open the PDF.",
        "action": "Check it against the message your bank sent with the statement, and try again.",
        "needs": "password",
    },
    "pdf_unreadable": {
        "title": "We could not open this PDF",
        "message": "The PDF could not be opened. It may be damaged.",
        "action": "Download the statement again, or export it as CSV or Excel instead.",
        "needs": None,
    },
    "pdf_scanned": {
        "title": "This PDF is a scan",
        "message": "The pages are pictures, so there is no text we can read directly.",
        "action": "You can allow a vision model to read the page images (they are sent to the model), "
                  "or upload the statement as CSV or Excel instead.",
        "needs": "consent",
    },
    "pdf_unsupported": {
        "title": "PDF reading is not available",
        "message": "This server cannot read PDF files right now.",
        "action": "Upload the statement as CSV or Excel instead.",
        "needs": None,
    },
    "vision_consent_required": {
        "title": "This is a picture of a statement",
        "message": "To read a picture, a vision model has to see the image.",
        "action": "Allow this once to continue, or upload the statement as CSV or Excel instead.",
        "needs": "consent",
    },
    "vision_unavailable": {
        "title": "Reading pictures is not set up",
        "message": "No vision model is configured on this server.",
        "action": "Upload the statement as CSV or Excel instead.",
        "needs": None,
    },
    "vision_failed": {
        "title": "We could not read a table from this picture",
        "message": "The picture did not give us usable rows.",
        "action": "Try a sharper, straight-on photo with the whole table in view, or upload CSV or Excel instead.",
        "needs": None,
    },
    "unexpected": {
        "title": "Something went wrong",
        "message": "An unexpected problem stopped us from reading this file.",
        "action": "Try again, or upload the statement as CSV or Excel.",
        "needs": None,
    },
}

UNKNOWN_ERROR: Dict[str, Any] = {
    "title": "We could not read this file",
    "message": "The statement could not be read.",
    "action": "Try again, or upload the statement as CSV or Excel.",
    "needs": None,
}


def friendly_error(code: Optional[str], fallback_message: Optional[str] = None,
                   fallback_hint: Optional[str] = None) -> Dict[str, Any]:
    """Wording for an error code. Unknown codes fall back to the technical message
    (so nothing is ever hidden) wrapped in a generic title."""
    entry = ERROR_TABLE.get(code or "")
    if entry is not None:
        return {"code": code, **entry}
    out = dict(UNKNOWN_ERROR)
    if fallback_message:
        out["message"] = fallback_message
    if fallback_hint:
        out["action"] = fallback_hint
    return {"code": code or "unknown", **out}


# --------------------------------------------------------------------------
# Money / date formatting
# --------------------------------------------------------------------------


def inr(amount: Decimal) -> str:
    """Indian grouping with the rupee sign: 150000 -> '\u20b91,50,000.00'."""
    s = f"{abs(amount):.2f}"
    whole, frac = s.split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts: List[str] = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return ("-" if amount < 0 else "") + "\u20b9" + whole + "." + frac


def _day(d) -> str:
    return d.strftime("%d %b %Y").lstrip("0")


# --------------------------------------------------------------------------
# The "ask once" preview
# --------------------------------------------------------------------------


def build_preview(result) -> Dict[str, Any]:
    """Preview card for a finished ingestion (an IngestResult).

    status   'ok'      everything verified: show a green tick and the summary.
             'check'   something is uncertain: show the summary and ONE question.
             'failed'  the file could not be read: show the error wording.
    question exactly one question (or None). Extra worries go in ``notes``.
    actions  the buttons to show, as plain labels.
    """
    report = result.report
    if not result.ok or result.meta is None:
        err = friendly_error(report.error_code, report.errors[0] if report.errors else None, report.hint)
        needs = err["needs"]
        actions = {"password": ["Enter password"], "consent": ["Allow and continue", "Choose another file"],
                   "mapping": ["Choose columns"]}.get(needs, ["Choose another file"])
        return {
            "status": "failed", "headline": err["title"], "details": [err["message"]], "notes": [],
            "question": None, "action_text": err["action"], "actions": actions,
            "needs": needs, "error_code": err["code"], "confirm_required": needs == "mapping",
        }

    rows, meta, chain = result.rows, result.meta, report.chain or {}
    credits = [r.credit for r in rows if r.credit]
    debits = [r.debit for r in rows if r.debit]
    details = [f"{len(rows)} transactions, {_day(meta.coverage_start)} to {_day(meta.coverage_end)}."]
    if credits:
        details.append(f"Money in: {len(credits)} payments, {inr(sum(credits, Decimal(0)))}.")
    if debits:
        details.append(f"Money out: {len(debits)} payments, {inr(sum(debits, Decimal(0)))}.")

    status = chain.get("status")
    if status == "pass":
        details.append(f"The numbers add up: the running balance matches on all {chain.get('checked', 0)} rows checked.")
    if report.mapping_summary:
        details.append("Columns we used: " + "; ".join(report.mapping_summary) + ".")

    notes: List[str] = []
    first_break = chain.get("first_break") or {}
    if status in ("partial", "fail"):
        where = f" (first at line {first_break['source_line']})" if first_break.get("source_line") else ""
        notes.append(f"The running balance does not add up on some rows{where}, so a column may be read wrongly.")
    elif status == "unavailable":
        notes.append("This file has no balance column, so we cannot double-check the amounts.")
    elif status == "pass" and chain.get("evidence") == "weak":
        notes.append("Only a few rows could be double-checked, so the check is weak.")
    if report.rows_lost:
        notes.append(f"{report.rows_lost} rows looked like payments but could not be read.")
    dates_assumed = report.date_order_status in ("assumed", "conflict")
    if dates_assumed:
        notes.append("Dates like 06/10/2026 could mean 6 October or 10 June. We assumed day first.")
    if not meta.has_time_of_day:
        notes.append("This statement shows dates but no times, so payments can only be matched by day.")
    if report.header_synthesized:
        notes.append("There was no header row, so the columns were worked out from the values.")

    question: Optional[str] = None
    actions = ["Looks right"]
    if status in ("partial", "fail") or report.rows_lost or report.header_synthesized:
        question = "Is each column below read correctly? If not, choose the right ones."
        actions = ["Looks right", "Choose columns"]
    elif status == "unavailable":
        question = "Do the first few rows below match your statement?"
        actions = ["Looks right", "Choose columns"]
    elif dates_assumed:
        question = f"Your first transaction is shown as {_day(rows[0].datetime)}. Is that the right date?"
        actions = ["Yes", "No, dates are month first"]
    elif report.needs_confirmation:
        question = "Please look over the summary. Does it match your statement?"
        actions = ["Looks right", "Choose columns"]

    if question is None:
        headline = "Statement read and checked"
    else:
        headline = "Please check how we read your statement"
    return {
        "status": "ok" if question is None else "check", "headline": headline, "details": details,
        "notes": notes, "question": question, "action_text": None, "actions": actions,
        "needs": None, "error_code": None, "confirm_required": question is not None,
    }
