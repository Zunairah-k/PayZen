"""Make a plain and a password-locked statement PDF from a synthetic CSV (EVALUATION USE ONLY)."""
import csv
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

ROOT = Path(__file__).resolve().parent.parent
src = ROOT / "data" / "synthetic" / "statements" / "statement_03_signed.csv"
out = Path(r"C:\temp")
out.mkdir(exist_ok=True)

rows = list(csv.reader(open(src, encoding="utf-8")))[:41]  # header + 40 rows, spans pages
for name, pw in (("statement_plain.pdf", None), ("statement_locked.pdf", "test123")):
    doc = SimpleDocTemplate(str(out / name), pagesize=landscape(A4), encrypt=pw)
    table = Table(rows, repeatRows=1, colWidths=[110, 330, 80, 100])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
    ]))
    doc.build([table])
    print("wrote", out / name)