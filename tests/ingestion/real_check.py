"""Check YOUR OWN real statement locally. Nothing is stored or sent to any model (rules only, llm_policy=never).

    python -m tests.ingestion.real_check "C:\\path\\to\\statement.csv" [--password PDFPASSWORD]

Prints only a SAFE summary you can share: counts, how the file was understood, and the SHAPE of three rows
(digits shown as 9, letters as x).
"""

import argparse
import re
from pathlib import Path

from backend.app.ingestion.normalize import mask_cell
from backend.app.ingestion.pipeline import ingest_statement


def _digits(s):
    return re.sub(r"\d", "9", str(s))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--password")
    a = ap.parse_args()
    p = Path(a.path)
    res = ingest_statement(p.read_bytes(), p.name, llm_policy="never", password=a.password)
    r = res.report
    ch = r.chain or {}
    print("\n=== SAFE SUMMARY (no names, amounts or account numbers) ===")
    print("file type:", r.kind, "| read OK:", res.ok, "| error code:", r.error_code)
    print("rows parsed:", r.rows_parsed, "| skipped:", r.rows_skipped, "| could not read:", r.rows_lost)
    print("balance check:", ch.get("status"), f"{ch.get('passed')}/{ch.get('checked')}", "| direction:", ch.get("direction"))
    if ch.get("first_break"):
        print("   first break hint:", ch["first_break"].get("hint"))
    print("date order:", r.date_order, f"({r.date_order_status})", "| parse confidence:", r.parse_confidence,
          "| asks user to confirm:", r.needs_confirmation)
    print("column names:", r.columns)
    print("how it was understood:", r.mapping_summary)
    for w in r.warnings:
        print("warning:", _digits(w))
    print("shape of the first rows (digits=9, letters=x):")
    for row in r.sample_rows[:3]:
        print("   ", [mask_cell(c)[:40] for c in row])