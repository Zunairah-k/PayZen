"""PayZen evaluation harness (EVALUATION USE ONLY).

Runs the real ingestor, matcher and rechecker on the synthetic set and writes
eval/results/results.json and results.md. Claims are built from ground truth
("oracle extraction"), so this measures statement ingestion + matching, not
screenshot extraction.

Usage (from repo root, with the backend venv active):  python eval/run_eval.py
"""
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.models import Claim, StatementMeta, StatementRow  # noqa: E402
from app.services.ingestor import ingest_statement_full  # noqa: E402
from app.services.matcher import match_claims  # noqa: E402
from app.services.rechecker import merge_rechecked, recheck_claims  # noqa: E402

DATA = ROOT / "data" / "synthetic"
OUT = ROOT / "eval" / "results"
OUT.mkdir(parents=True, exist_ok=True)

LAYOUTS = ["statement_01_standard.csv", "statement_02_drcr.csv", "statement_03_signed.csv",
           "statement_04_datetime.csv", "statement_05_indian_junk.csv"]
LATER = "statement_06_later.csv"
BASELINE = LAYOUTS[0]
STATUSES = ["Verified", "Likely match", "Contradicted", "Not found", "Duplicate", "Can't verify yet"]
GENUINE_CATS = ("genuine", "genuine_delayed")


def as_model(cls, obj):
    if isinstance(obj, cls):
        return obj
    if hasattr(obj, "model_dump"):
        return cls(**obj.model_dump())
    return cls(**obj)


def ingest(path: Path):
    rows, meta, preview = ingest_statement_full(path.read_bytes(), path.name, None, False)
    return [as_model(StatementRow, r) for r in rows], as_model(StatementMeta, meta), preview


def load_claims():
    gt = list(csv.DictReader(open(DATA / "ground_truth.csv", encoding="utf-8")))
    claims = []
    for r in gt:
        img = (DATA / r["file"]).read_bytes()
        claims.append(Claim(
            claim_id=r["claim_id"], source_file=r["file"],
            image_hash="sha256:" + hashlib.sha256(img).hexdigest(),
            payer_name=r["payer_name"], payer_upi_id=r["payer_upi"], amount=float(r["amount"]),
            timestamp=r["timestamp"].replace(" ", "T"), reference=r["reference"],
            confidence={"reference": 1.0, "amount": 1.0, "timestamp": 1.0, "payer_name": 1.0}))
    return gt, claims


def ingestion_report(name, rows, meta, truth):
    parsed = sorted(round(r.credit or 0, 2) for r in rows if (r.credit or 0) > 0)
    expected = sorted(round(t["amount"], 2) for t in truth if t["kind"] == "credit")
    true_refs = {t["ref"] for t in truth if t["ref_in_narration"]}
    got_refs = {r.extracted_reference for r in rows if r.extracted_reference}
    hit = len(true_refs & got_refs)
    return {"statement": name, "rows_parsed": len(rows), "rows_expected": len(truth),
            "credits_exact": parsed == expected,
            "ref_recall": round(hit / len(true_refs), 3) if true_refs else None,
            "ref_precision": round(hit / len(got_refs), 3) if got_refs else None,
            "coverage": f"{meta.coverage_start} to {meta.coverage_end}",
            "balance_chain": meta.balance_chain_result, "parse_confidence": meta.parse_confidence,
            "warnings": len(meta.warnings)}


def evaluate(gt, verdicts):
    pred = {v.claim_id: v for v in verdicts}
    conf, cat = defaultdict(Counter), defaultdict(lambda: [0, 0])
    ref_split = defaultdict(lambda: [0, 0])
    false_verified, fake_likely, false_nf, wrong = [], [], [], []
    correct = 0
    for r in gt:
        cid, exp = r["claim_id"], r["expected_verdict"]
        p = pred[cid].status if cid in pred else "MISSING"
        fake = r["category"] not in GENUINE_CATS
        ok = p == exp
        correct += ok
        conf[exp][p] += 1
        cat[r["category"]][0] += ok
        cat[r["category"]][1] += 1
        if r["category"] == "genuine":
            k = "reference in narration" if r["reference_in_narration"] == "True" else "no reference in narration"
            ref_split[k][0] += ok
            ref_split[k][1] += 1
        if fake and p == "Verified":
            false_verified.append(cid)
        if fake and p == "Likely match":
            fake_likely.append(cid)
        if not fake and p == "Not found":
            false_nf.append(cid)
        if not ok:
            wrong.append({"claim_id": cid, "category": r["category"], "expected": exp, "predicted": p,
                          "reasons": (pred[cid].reasons[:2] if cid in pred else [])})
    n_fake = sum(1 for r in gt if r["category"] not in GENUINE_CATS)
    n_gen = len(gt) - n_fake
    return {"n": len(gt), "accuracy": round(correct / len(gt), 3),
            "false_verified": false_verified, "false_verified_rate": f"{len(false_verified)}/{n_fake}",
            "fakes_marked_likely": fake_likely, "false_not_found": false_nf,
            "false_not_found_rate": f"{len(false_nf)}/{n_gen}",
            "by_category": {k: f"{v[0]}/{v[1]}" for k, v in cat.items()},
            "by_reference_availability": {k: f"{v[0]}/{v[1]}" for k, v in ref_split.items()},
            "confusion": {e: dict(c) for e, c in conf.items()}, "mismatches": wrong}


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    return "\n".join(out)


def main():
    gt, claims = load_claims()
    master = json.load(open(DATA / "master_payments.json", encoding="utf-8"))
    truth_main = [t for t in master if not t["ts"].startswith("2026-10-07")]
    truth_late = [t for t in master if t["ts"].startswith("2026-10-07")]
    delayed = [r for r in gt if r["expected_after_recheck"]]

    results = {"claims": len(gt), "ingestion": [], "matching": {}, "recheck": {}}
    later = None
    try:
        later_rows, later_meta, _ = ingest(DATA / "statements" / LATER)
        results["ingestion"].append(ingestion_report(LATER, later_rows, later_meta, truth_late))
        later = (later_rows, later_meta)
    except Exception as e:  # report, never crash
        results["ingestion"].append({"statement": LATER, "error": repr(e)})

    for name in LAYOUTS:
        try:
            rows, meta, _ = ingest(DATA / "statements" / name)
        except Exception as e:
            results["ingestion"].append({"statement": name, "error": repr(e)})
            continue
        results["ingestion"].append(ingestion_report(name, rows, meta, truth_main))
        verdicts = match_claims(claims, rows, meta)
        results["matching"][name] = evaluate(gt, verdicts)
        if later:
            new = recheck_claims(claims, later[0], later[1], previous_verdicts=verdicts, with_replies=False)
            merged = merge_rechecked(verdicts, new)
            after = {v.claim_id: v.status for v in merged}
            before = {v.claim_id: v.status for v in verdicts}
            results["recheck"][name] = {
                "delayed_claims": len(delayed),
                "correct_before_recheck": sum(before[r["claim_id"]] == r["expected_verdict"] for r in delayed),
                "correct_after_recheck": sum(after[r["claim_id"]] == r["expected_after_recheck"] for r in delayed)}

    json.dump(results, open(OUT / "results.json", "w", encoding="utf-8"), indent=2)

    md = ["# PayZen evaluation (synthetic data)", "",
          f"{len(gt)} claims, {len(LAYOUTS)} statement layouts + 1 later statement. Claims use oracle extraction. "
          "Numbers are exactly as produced by eval/run_eval.py. The data is synthetic.", "",
          "## Statement ingestion", ""]
    ing = [r for r in results["ingestion"] if "error" not in r]
    md.append(md_table(["statement", "rows parsed/expected", "credits exact", "ref recall", "ref precision",
                        "coverage", "balance chain", "parse conf", "warnings"],
                       [[r["statement"], f"{r['rows_parsed']}/{r['rows_expected']}", r["credits_exact"], r["ref_recall"],
                         r["ref_precision"], r["coverage"], r["balance_chain"], r["parse_confidence"], r["warnings"]]
                        for r in ing]))
    for r in results["ingestion"]:
        if "error" in r:
            md.append(f"\n**FAILED** {r['statement']}: `{r['error']}`")
    md += ["", "## Verdict accuracy by statement layout", ""]
    md.append(md_table(["layout", "accuracy", "false-Verified", "false Not-found", "fakes marked Likely"],
                       [[n, m["accuracy"], m["false_verified_rate"], m["false_not_found_rate"], len(m["fakes_marked_likely"])]
                        for n, m in results["matching"].items()]))
    base = results["matching"].get(BASELINE)
    if base:
        md += ["", f"## Baseline detail ({BASELINE})", "", "### Confusion matrix (rows = expected, columns = predicted)", ""]
        md.append(md_table(["expected \\ predicted"] + STATUSES,
                           [[e] + [base["confusion"].get(e, {}).get(p, 0) for p in STATUSES] for e in STATUSES]))
        md += ["", "### Accuracy by category", "",
               md_table(["category", "correct"], list(base["by_category"].items())),
               "", "### With vs without a reference in the narration (genuine claims)", "",
               md_table(["case", "correct"], list(base["by_reference_availability"].items())),
               "", "### False-Verified claim ids", "", str(base["false_verified"] or "none"),
               "", "### First 8 mismatches", "",
               md_table(["claim", "category", "expected", "predicted", "reasons"],
                        [[w["claim_id"], w["category"], w["expected"], w["predicted"], " / ".join(w["reasons"])]
                         for w in base["mismatches"][:8]])]
    if results["recheck"]:
        md += ["", "## Re-check on delayed payments", "",
               md_table(["layout", "delayed claims", "correct before", "correct after re-check"],
                        [[n, r["delayed_claims"], r["correct_before_recheck"], r["correct_after_recheck"]]
                         for n, r in results["recheck"].items()])]
    (OUT / "results.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    print(f"\nWrote {OUT / 'results.json'} and {OUT / 'results.md'}")


if __name__ == "__main__":
    main()