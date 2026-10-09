"""Writes small demo files that trigger each statement prompt in the UI (synthetic data only).
Run:  python -m tests.ingestion.make_demo_files      -> data/synthetic/demo/
"""

import csv
from pathlib import Path

from tests.ingestion.layouts import ALL_FIXTURES, CHAOS_FIXTURES, TRUTH
from tests.ingestion.vision_check import render

ROOT = Path(__file__).resolve().parents[2]


def _write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh, lineterminator="\n").writerows(rows)


if __name__ == "__main__":
    out = ROOT / "data" / "synthetic" / "demo"
    out.mkdir(parents=True, exist_ok=True)
    rows = list(csv.reader(CHAOS_FIXTURES[0].data.decode().splitlines()))
    _write(out / "demo_0_clean_green_tick.csv", rows)
    _write(out / "demo_1_no_balance_check_card.csv", [r[:-1] for r in rows])
    _write(out / "demo_2_ambiguous_dates_card.csv", rows[:13])
    _write(out / "demo_3_missing_row_check_card.csv", rows[:40] + rows[41:])
    notes = ["demo_0: a normal statement -> green tick",
             "demo_1: no balance column -> the arithmetic check is unavailable -> 'please check' card",
             "demo_2: dates like 01/10/26 are ambiguous -> 'is this the right date?' card (Yes / No, month first)",
             "demo_3: one row missing in the middle -> the balance check breaks -> 'please check' card"]
    pdf = next((f for f in ALL_FIXTURES if f.password), None)
    if pdf:
        (out / "demo_4_password_pdf.pdf").write_bytes(pdf.data)
        notes.append(f"demo_4: password-protected PDF -> password card. Password: {pdf.password}")
    (out / "demo_5_picture_vision_consent.png").write_bytes(render(TRUTH[:15]))
    notes.append("demo_5: picture of a statement -> vision consent card, then a 'check the dates' card")
    (out / "README.txt").write_text("\n".join(notes), encoding="utf-8")
    print("Wrote", out)