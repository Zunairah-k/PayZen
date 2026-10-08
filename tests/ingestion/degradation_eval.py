"""Photo-of-statement evaluation under four conditions (synthetic data only).

Run (needs GEMINI_API_KEY loaded; takes about 5 minutes because of the free-tier rate limit):
    python -m tests.ingestion.degradation_eval
Writes docs/photo_degradation_results.md and docs/photo_degradation_results.csv
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import time
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

from backend.app.ingestion.pipeline import ingest_statement
from tests.ingestion.layouts import TRUTH
from tests.ingestion.vision_check import render

ROOT = Path(__file__).resolve().parents[2]
N = 15
SAMPLES = [TRUTH[0:N], TRUTH[N:2 * N], TRUTH[2 * N:3 * N]]
ZERO = Decimal("0")


def _png(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _jpeg(img, quality):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def c_clean(img):
    return _png(img), "clean.png"


def c_recompressed(img):
    return _jpeg(img, 35), "recompressed.jpg"


def c_resized(img):
    w, h = img.size
    return _png(img.resize((int(w * 0.6), int(h * 0.6)), Image.Resampling.LANCZOS)), "resized.png"


def c_photographed(img):
    x = img.convert("RGB").rotate(2.0, expand=True, fillcolor=(225, 225, 225), resample=Image.Resampling.BICUBIC)
    x = x.filter(ImageFilter.GaussianBlur(1.0))
    x = ImageEnhance.Brightness(x).enhance(0.85)
    noise = Image.effect_noise(x.size, 25).convert("RGB")
    x = Image.blend(x, noise, 0.10)
    return _jpeg(x, 55), "photographed.jpg"


CONDITIONS = [
    ("clean", "original image, no damage", c_clean),
    ("recompressed", "saved as a small JPEG (quality 35)", c_recompressed),
    ("resized", "shrunk to 60% of its size", c_resized),
    ("photographed", "tilted 2 degrees, blurred, darker, grainy, JPEG quality 55", c_photographed),
]


def evaluate_sample(truth, fn):
    img = Image.open(io.BytesIO(render(truth))).convert("RGB")
    data, name = fn(img)
    res = ingest_statement(data, name, llm_policy="never", allow_vision=True)
    if not res.ok and res.report.error_code == "vision_failed":
        time.sleep(20)  # most likely the free-tier rate limit: wait and try once more
        res = ingest_statement(data, name, llm_policy="never", allow_vision=True)
    out = {"ingest_ok": res.ok, "error_code": res.report.error_code, "rows_read": len(res.rows),
           "rows_expected": len(truth), "chain": (res.report.chain or {}).get("status", "-"),
           "needs_confirmation": res.report.needs_confirmation, "exact_rows": 0,
           "wrong_amount": None, "wrong_ref": None, "note": ""}
    if not res.ok:
        out["note"] = res.report.user_message
    elif len(res.rows) != len(truth):
        out["note"] = f"read {len(res.rows)} of {len(truth)} rows"
    else:
        wa = wr = ex = 0
        for i, (r, t) in enumerate(zip(res.rows, truth), start=1):
            amt_ok = (r.credit or ZERO) == (t.credit or ZERO) and (r.debit or ZERO) == (t.debit or ZERO)
            ref_ok = r.extracted_reference == t.ref
            bal_ok = r.balance == t.balance
            wa += not amt_ok
            wr += not ref_ok
            ex += amt_ok and ref_ok and bal_ok
            if not (amt_ok and ref_ok and bal_ok) and not out["note"]:
                out["note"] = (f"row {i}: read debit={r.debit} credit={r.credit} balance={r.balance} "
                               f"ref={r.extracted_reference}; expected debit={t.debit} credit={t.credit} "
                               f"balance={t.balance} ref={t.ref}")
        out.update(exact_rows=ex, wrong_amount=wa, wrong_ref=wr)
    return out


def summarize(name, note, samples):
    return {
        "condition": name, "how": note, "samples": len(samples),
        "statements_read": sum(1 for s in samples if s["ingest_ok"]),
        "right_row_count": sum(1 for s in samples if s["ingest_ok"] and s["rows_read"] == s["rows_expected"]),
        "rows_correct": sum(s["exact_rows"] for s in samples),
        "rows_expected": sum(s["rows_expected"] for s in samples),
        "wrong_amounts": sum(s["wrong_amount"] or 0 for s in samples),
        "wrong_references": sum(s["wrong_ref"] or 0 for s in samples),
        "chain_pass": sum(1 for s in samples if s["chain"] == "pass"),
        "asked_confirm": sum(1 for s in samples if s["needs_confirmation"]),
        "notes": [s["note"] for s in samples if s["note"]],
    }


def write_files(summaries):
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    cols = ["condition", "samples", "statements_read", "right_row_count", "rows_correct", "rows_expected",
            "wrong_amounts", "wrong_references", "chain_pass", "asked_confirm"]
    with (docs / "photo_degradation_results.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for s in summaries:
            w.writerow([s[c] for c in cols])
    md = [
        "# Photo-of-statement test under four conditions",
        "",
        f"Generated {_dt.date.today().isoformat()} by `python -m tests.ingestion.degradation_eval`.",
        "",
        f"Each condition uses {len(SAMPLES)} synthetic statement images of {N} rows (images are drawn by our own test code, "
        "then damaged). The vision model reads each image; the balance check verifies it. A row counts as correct only when "
        "its amounts, balance and 12-digit reference all match the truth, and rows are counted as 0 when the number of rows "
        "read is wrong. Small sample, synthetic data, one vision model.",
        "",
        "| Condition | What was done | Statements read | Right number of rows | Rows fully correct | Wrong amounts | Wrong references | Balance check passed | Asked user to confirm |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        md.append(f"| {s['condition']} | {s['how']} | {s['statements_read']}/{s['samples']} | {s['right_row_count']}/{s['samples']} "
                  f"| {s['rows_correct']}/{s['rows_expected']} | {s['wrong_amounts']} | {s['wrong_references']} "
                  f"| {s['chain_pass']}/{s['samples']} | {s['asked_confirm']}/{s['samples']} |")
    md += ["", "## Failure examples", ""]
    any_notes = False
    for s in summaries:
        for n in s["notes"]:
            md.append(f"- **{s['condition']}**: {n}")
            any_notes = True
    if not any_notes:
        md.append("None on this run.")
    md += ["", "## Reading these results", "",
           "- This tests the *photo* path only. Spreadsheet, CSV and text-PDF statements do not use the vision model.",
           "- Real phone photos (glare, folds, a hand in the frame) are harder than these simulated ones.", ""]
    (docs / "photo_degradation_results.md").write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    summaries = []
    for name, how, fn in CONDITIONS:
        samples = []
        for i, truth in enumerate(SAMPLES, start=1):
            print(f"{name}: sample {i}/{len(SAMPLES)} ...", flush=True)
            samples.append(evaluate_sample(truth, fn))
        s = summarize(name, how, samples)
        summaries.append(s)
        print(f"  -> rows fully correct {s['rows_correct']}/{s['rows_expected']}, "
              f"wrong amounts {s['wrong_amounts']}, wrong references {s['wrong_references']}, "
              f"balance check passed {s['chain_pass']}/{s['samples']}\n", flush=True)
    write_files(summaries)
    print("Wrote docs/photo_degradation_results.md and docs/photo_degradation_results.csv")