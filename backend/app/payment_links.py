"""Unique payment link + QR per payer (the 'prevent' feature). PROTOTYPE.

The link is a standard UPI deep link; the payer's tag goes in the transaction note (tn). Many banks copy the
note into the statement narration, so the payment can then be matched by the tag alone. Unverified for any
specific bank until tested with a real transfer.
"""

from __future__ import annotations

import base64
import io
import re
import secrets
from decimal import Decimal
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

TAG_RE = re.compile(r"PZ-[A-Z0-9]{6}")
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_tag() -> str:
    return "PZ-" + "".join(secrets.choice(_ALPHABET) for _ in range(6))


def make_upi_link(payee_vpa: str, payee_name: str, amount: float, tag: str) -> str:
    return (f"upi://pay?pa={quote(payee_vpa, safe='@')}&pn={quote(payee_name)}"
            f"&am={float(amount):.2f}&cu=INR&tn={quote(tag)}")


def make_qr_png(link: str) -> bytes:
    import segno

    buf = io.BytesIO()
    segno.make(link, error="m").save(buf, kind="png", scale=8, border=2)
    return buf.getvalue()


def find_tag(text: Optional[str]) -> Optional[str]:
    m = TAG_RE.search((text or "").upper())
    return m.group(0) if m else None


def reconcile_by_tag(rows: List[Any], issued: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """rows: StatementRow list from ingestion. issued: [{'tag','amount','payer'}]. Matches credits by tag."""
    by_tag: Dict[str, List[Any]] = {}
    for r in rows:
        if r.credit:
            t = find_tag(r.narration)
            if t:
                by_tag.setdefault(t, []).append(r)
    out = []
    for item in issued:
        found = by_tag.get(item["tag"].upper(), [])
        if not found:
            status, why = "not_found_yet", "no credit carries this tag (check the statement covers the payment time)"
        elif len(found) > 1:
            status, why = "duplicate", "more than one credit carries this tag"
        elif abs(found[0].credit - Decimal(str(item["amount"]))) > Decimal("0.01"):
            status, why = "amount_differs", f"credit is {found[0].credit}, expected {item['amount']}"
        else:
            status, why = "paid", "one credit with this tag and the right amount"
        out.append({"payer": item.get("payer"), "tag": item["tag"], "status": status, "why": why,
                    "row_id": found[0].row_id if len(found) == 1 else None})
    return out


router = APIRouter(prefix="/links", tags=["payment links"])


class LinkRequest(BaseModel):
    payee_vpa: str
    payee_name: str
    amount: float
    payer_label: str = ""


@router.post("/new")
def new_link(req: LinkRequest):
    tag = new_tag()
    link = make_upi_link(req.payee_vpa, req.payee_name, req.amount, tag)
    try:
        png = make_qr_png(link)
    except ImportError:
        raise HTTPException(status_code=503, detail="QR support is not installed (pip install segno).")
    return {"tag": tag, "link": link, "payer": req.payer_label,
            "qr_png_base64": base64.b64encode(png).decode("ascii")}