"""Screenshot evaluation under four conditions (EVALUATION USE ONLY, synthetic screenshots).

Reads the real payment screenshots with the real extractor, compares every field with ground_truth.csv, and
runs the matcher on what was read, so the result includes the number that matters most: the false-Verified
rate (a fake wrongly marked as paid) when extraction is REAL, not an oracle.

Steps (from the repo root, GEMINI_API_KEY loaded):
    python -m tests.ingestion.make_degraded_screenshots data/synthetic/screenshots     # once
    python eval/screenshot_eval.py --limit 25                                          # about 11 minutes
    python eval/screenshot_eval.py --all                                               # about 45 minutes

Writes eval/results/screenshot_eval.md and screenshot_eval.json. Free-tier Gemini allows about one call every
6.5 seconds, so --limit samples the 100 claims evenly across all categories.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.models import Claim, StatementMeta, StatementRow  # noqa: E402
from app.services.extractor import extract_claim_detailed  # noqa: E402
from app.services.ingestor import ingest_statement_full  # noqa: E402
from app.services.matcher import match_claims  # noqa: E402

DATA = ROOT / "data" / "synthetic"
OUT = ROOT / "eval" / "results"
STATEMENT = DATA / "statements" / "statement_01_standard.csv"
GENUINE = ("genuine", "genuine_delayed")
CONDITIONS = ["clean", "recompressed", "resized", "photographed"]


def _model(cls, obj):
    if isinstance(obj, cls):
        return obj
    return cls(**(obj.model_dump() if hasattr(obj, "model_dump") else obj))


def find_image(row: Dict[str, str], condition: str) -> Optional[Path]:
    if condition == "clean":
        p = DATA / row["file"]
        return p if p.exists() else None
    folder = DATA / "degraded" / condition
    stem = Path(row["file"]).stem
    for ext in (".jpg", ".png", ".jpeg"):
        if (folder / (stem + ext)).exists():
            return folder / (stem + ext)
    return None


def sample(gt: List[Dict[str, str]], limit: Optional[int]) -> List[Dict[str, str]]:
    """Even sample across categories. A duplicate can only be recognised when the claim it copies is in the same
    batch, so every sampled duplicate brings its original along (the sample can be a few claims over the limit)."""
    if not limit or limit >= len(gt):
        return gt
    step = len(gt) / limit
    ids = {gt[int(i * step)]["claim_id"] for i in range(limit)}
    by_id = {r["claim_id"]: r for r in gt}
    ids |= {by_id[c]["original_claim"] for c in list(ids) if by_id[c].get("original_claim") in by_id}
    return [r for r in gt if r["claim_id"] in ids]


def run_condition(rows_gt, condition, rows, meta, provider=None) -> Dict[str, Any]:
    claims, per = [], []
    for r in rows_gt:
        img = find_image(r, condition)
        if img is None:
            per.append({"claim_id": r["claim_id"], "missing_image": True})
            continue
        data = img.read_bytes()
        det = extract_claim_detailed(data, r["claim_id"] + img.suffix, provider=provider)
        c = det.claim
        c.claim_id, c.source_file = r["claim_id"], r["file"]
        if not c.image_hash:
            c.image_hash = "sha256:" + hashlib.sha256(data).hexdigest()
        claims.append(c)
        ts_ok = bool(c.timestamp) and c.timestamp.replace(" ", "T")[:16] == r["timestamp"].replace(" ", "T")[:16]
        per.append({
            "claim_id": r["claim_id"], "empty": c.amount is None and c.reference is None,
            "amount_ok": c.amount is not None and abs(c.amount - float(r["amount"])) < 0.005,
            "reference_ok": c.reference == r["reference"], "timestamp_ok": ts_ok,
            "name_ok": (c.payer_name or "").casefold().strip() == r["payer_name"].casefold().strip(),
            "amount_wrong": c.amount is not None and abs(c.amount - float(r["amount"])) >= 0.005,
            "reference_wrong": c.reference is not None and c.reference != r["reference"]})
    read = [p for p in per if not p.get("missing_image")]
    verdicts = {v.claim_id: v.status for v in match_claims(claims, rows, meta)}
    fake_ids = {r["claim_id"] for r in rows_gt if r["category"] not in GENUINE}
    pred = {r["claim_id"]: verdicts.get(r["claim_id"], "MISSING") for r in rows_gt}
    exp = {r["claim_id"]: r["expected_verdict"] for r in rows_gt}
    got = [r["claim_id"] for r in rows_gt if r["claim_id"] in verdicts]
    n = len(read)

    def count(key):
        return sum(1 for p in read if p.get(key))

    return {
        "condition": condition, "images": n, "empty_reads": count("empty"),
        "amount_ok": count("amount_ok"), "reference_ok": count("reference_ok"), "timestamp_ok": count("timestamp_ok"),
        "name_ok": count("name_ok"), "amount_wrong": count("amount_wrong"), "reference_wrong": count("reference_wrong"),
        "verdict_correct": sum(pred[c] == exp[c] for c in got), "claims_judged": len(got),
        "fakes": sum(1 for c in got if c in fake_ids),
        "false_verified": sorted(c for c in got if c in fake_ids and pred[c] == "Verified"),
        "genuine": sum(1 for c in got if c not in fake_ids),
        "false_not_found": sorted(c for c in got if c not in fake_ids and pred[c] == "Not found"),
        "verdict_counts": dict(Counter(pred[c] for c in got)),
    }


def write_report(results: List[Dict[str, Any]], limit_note: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "screenshot_eval.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    hdr = ["Condition", "Images", "Nothing read", "Amount right", "Reference right", "Time right", "Wrong amount",
           "Wrong reference", "Verdict right", "False-Verified (fake marked paid)", "Genuine marked Not found"]
    lines = ["# Screenshot evaluation, four conditions (synthetic data)", "",
             f"{limit_note} The real extractor read each screenshot; the real matcher judged the result against "
             "`statement_01_standard.csv`. 'Wrong' means a value was read but is not the true value (worse than "
             "'nothing read'). Small sample, synthetic screenshots drawn by our own code, one vision model.", "",
             "| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
    for r in results:
        n = r["images"]
        lines.append("| " + " | ".join(str(x) for x in [
            r["condition"], n, r["empty_reads"], f"{r['amount_ok']}/{n}", f"{r['reference_ok']}/{n}",
            f"{r['timestamp_ok']}/{n}", r["amount_wrong"], r["reference_wrong"],
            f"{r['verdict_correct']}/{r['claims_judged']}", f"{len(r['false_verified'])}/{r['fakes']}",
            f"{len(r['false_not_found'])}/{r['genuine']}"]) + " |")
    lines += ["", "False-Verified is the most important number: a fake payment marked as paid.", ""]
    for r in results:
        if r["false_verified"]:
            lines.append(f"- {r['condition']}: false-Verified claim ids: {', '.join(r['false_verified'])}")
    out = OUT / "screenshot_eval.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main(argv=None, provider=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--conditions", default=",".join(CONDITIONS))
    a = ap.parse_args(argv)
    if provider is None:
        from app.services.vision_gemini import register_gemini_provider
        if not register_gemini_provider():
            print("No GEMINI_API_KEY loaded, so no screenshots can be read. Load your keys and run again.")
            return 1
    gt = list(csv.DictReader(open(DATA / "ground_truth.csv", encoding="utf-8")))
    use = sample(gt, None if a.all else a.limit)
    rows, meta, _ = ingest_statement_full(STATEMENT.read_bytes(), STATEMENT.name, None, False)
    rows, meta = [_model(StatementRow, r) for r in rows], _model(StatementMeta, meta)
    results = []
    for cond in [c for c in a.conditions.split(",") if c in CONDITIONS]:
        print(f"{cond}: reading {len(use)} screenshots ...", flush=True)
        res = run_condition(use, cond, rows, meta, provider)
        print(f"  -> amount right {res['amount_ok']}/{res['images']}, reference right {res['reference_ok']}/{res['images']}, "
              f"wrong amount {res['amount_wrong']}, wrong reference {res['reference_wrong']}, "
              f"false-Verified {len(res['false_verified'])}/{res['fakes']}", flush=True)
        results.append(res)
    note = f"{len(use)} of {len(gt)} claims per condition (a sampled duplicate always brings its original)." if len(use) < len(gt) else f"All {len(gt)} claims per condition."
    print("Wrote", write_report(results, note))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
