"""Live check of the photo-of-statement path (calls the Gemini free tier; synthetic data only).

Run:  python -m tests.ingestion.vision_check      (needs GEMINI_API_KEY in this terminal)
"""

from __future__ import annotations

import io
from decimal import Decimal

from PIL import Image, ImageDraw, ImageFont

from backend.app.ingestion.pipeline import ingest_statement
from tests.ingestion.layouts import TRUTH, f2, narration

N = 15
ZERO = Decimal("0")


def render(truth) -> bytes:
    try:
        font = ImageFont.load_default(size=18)
    except TypeError:  # older Pillow
        font = ImageFont.load_default()
    header = ["Date", "Narration", "Withdrawals", "Deposits", "Balance"]
    xs = [10, 140, 760, 900, 1040]
    img = Image.new("RGB", (1200, 50 + 30 * (len(truth) + 1)), "white")
    d = ImageDraw.Draw(img)
    for x, h in zip(xs, header):
        d.text((x, 10), h, fill="black", font=font)
    for i, t in enumerate(truth, start=1):
        cells = [t.dt.strftime("%d/%m/%Y"), narration(t), f2(t.debit), f2(t.credit), f2(t.balance)]
        for x, c in zip(xs, cells):
            d.text((x, 10 + 30 * i), c, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


if __name__ == "__main__":
    truth = TRUTH[:N]
    png = render(truth)
    r = ingest_statement(png, "photo.png", llm_policy="never")
    print("without consent ->", r.report.error_code)
    r = ingest_statement(png, "photo.png", llm_policy="never", allow_vision=True)
    print("ok:", r.ok, "| rows:", len(r.rows), "of", N, "| chain:", r.report.chain.get("status"),
          "|", r.report.chain.get("note"))
    if not r.ok:
        print(r.report.user_message)
    else:
        wrong_amt = sum(1 for a, t in zip(r.rows, truth)
                        if (a.credit or ZERO) != (t.credit or ZERO) or (a.debit or ZERO) != (t.debit or ZERO))
        wrong_ref = sum(1 for a, t in zip(r.rows, truth) if a.extracted_reference != t.ref)
        print(f"wrong amounts: {wrong_amt} | wrong references: {wrong_ref} | confirm needed: {r.report.needs_confirmation}")