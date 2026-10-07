"""Parse every synthetic layout and compare with ground truth.

pytest:        python -m pytest tests/ingestion -q
table+report:  python -m tests.ingestion.test_layouts
with the model (needs ANTHROPIC_API_KEY):
               $env:INGEST_TEST_POLICY="always"; python -m tests.ingestion.test_layouts
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from backend.app.ingestion.pipeline import ingest_statement
from tests.ingestion.layouts import ALL_FIXTURES, Fixture

ZERO = Decimal("0")
POLICY = os.getenv("INGEST_TEST_POLICY", "never")


def check(fx: Fixture):
    res = ingest_statement(fx.data, fx.filename, llm_policy=POLICY)
    if not res.ok:
        return res, [f"ingest failed: {res.report.user_message}"]
    rows, truth = res.rows, fx.truth
    if len(rows) != len(truth):
        return res, [f"row count {len(rows)} != {len(truth)} "
                     f"(lost={res.report.rows_lost}, skipped={res.report.rows_skipped})"]

    no_balance = fx.name.startswith("X2")
    wrong = {"date": [], "amount": [], "balance": [], "reference": []}
    for i, (r, t) in enumerate(zip(rows, truth), start=1):
        if r.datetime.date() != t.dt.date() or (
                fx.has_time and r.datetime.replace(second=0, microsecond=0) != t.dt):
            wrong["date"].append((i, r.datetime, t.dt))
        if (r.credit or ZERO) != (t.credit or ZERO) or (r.debit or ZERO) != (t.debit or ZERO):
            wrong["amount"].append((i, (r.debit, r.credit), (t.debit, t.credit)))
        if not no_balance and r.balance != t.balance:
            wrong["balance"].append((i, r.balance, t.balance))
        if r.extracted_reference != t.ref:
            wrong["reference"].append((i, r.extracted_reference, t.ref))

    problems = []
    for key, items in wrong.items():
        if items:
            i, got, exp = items[0]
            problems.append(f"{key}: {len(items)} wrong (first at row {i}: got {got}, expected {exp})")
    expected_chain = "unavailable" if no_balance else "pass"
    got_chain = res.report.chain.get("status")
    if got_chain != expected_chain:
        problems.append(f"balance chain {got_chain}, expected {expected_chain}")
    return res, problems


@pytest.mark.parametrize("fx", ALL_FIXTURES, ids=lambda f: f.name)
def test_layout(fx):
    _, problems = check(fx)
    assert not problems, "; ".join(problems)


def run_all():
    results = []
    for fx in ALL_FIXTURES:
        res, problems = check(fx)
        rep = res.report
        ch = rep.chain or {}
        results.append({
            "name": fx.name, "problems": problems, "rows": rep.rows_parsed, "truth": len(fx.truth),
            "chain": ch.get("status", "-"),
            "checked": f"{ch.get('passed', 0)}/{ch.get('checked', 0)}" if ch else "-",
            "mapping": rep.mapping_source or "-",
            "llm_used": bool((rep.llm or {}).get("used")),
        })
    return results


def write_report(results) -> Path:
    root = Path(__file__).resolve().parents[2]
    out = root / "docs" / "day1_ingestion_report.md"
    out.parent.mkdir(exist_ok=True)
    clean = sum(1 for r in results if not r["problems"])
    llm_used = sum(1 for r in results if r["llm_used"])
    md = [
        "# Day 1 report: statement ingestion",
        "",
        f"Generated {_dt.date.today().isoformat()} by `python -m tests.ingestion.test_layouts` "
        f"(language-model policy: `{POLICY}`; model consulted on {llm_used} of {len(results)} layouts).",
        "",
        "## What was built (`backend/app/ingestion`)",
        "",
        "- `loader.py`: CSV, XLSX and pasted text; encoding and delimiter detection, true header row among junk lines, spacer columns dropped.",
        "- `mapping.py`: deterministic column mapper plus a language-model mapper that sees only column names and masked sample rows; replies validated as column indices only.",
        "- `normalize.py`, `parser.py`, `references.py`: Indian number grouping, currency symbols, Dr/Cr, many date formats, wrapped narrations stitched, footers and totals dropped, 12-digit reference and name hint extraction.",
        "- `coverage.py`: the period a statement covers, so late payments become \"Can't verify yet\" instead of \"Not found\".",
        "- `chain.py`, `report.py`, `pipeline.py`: balance-chain self-verification in both directions, debit/credit flip repair, parse report with confidence; the model proposes, the arithmetic decides.",
        "",
        "## Results on synthetic layouts",
        "",
        f"{clean} of {len(results)} layouts parsed with every date, amount, balance and reference matching ground truth.",
        "",
        "| Layout | Result | Rows parsed | Balance chain | Mapping used |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        md.append(f"| {r['name']} | {'ok' if not r['problems'] else 'FAIL'} | {r['rows']}/{r['truth']} "
                  f"| {r['chain']} ({r['checked']}) | {r['mapping']} |")
    md += ["", "## Failures", ""]
    failed = [r for r in results if r["problems"]]
    if failed:
        md += [f"- **{r['name']}**: {'; '.join(r['problems'])}" for r in failed]
    else:
        md.append("None on this run.")
    md += [
        "",
        "## Known limits",
        "",
        "- PDF, scanned and photo statements are not handled yet (clear message returned; Day 2).",
        "- Old `.xls` files ask the user to re-save as `.xlsx` or `.csv`.",
        "- A narration wrapped in the middle of a word gets a space inserted; references are unaffected, name hints can be.",
        "- The layouts are invented to imitate common export quirks; they do not claim to match any real bank.",
        "",
    ]
    out.write_text("\n".join(md), encoding="utf-8")
    return out


if __name__ == "__main__":
    results = run_all()
    print(f"{'layout':36s} {'result':6s} {'rows':>9s} {'chain':12s} problems")
    for r in results:
        print(f"{r['name']:36s} {'FAIL' if r['problems'] else 'ok':6s} {r['rows']:>4}/{r['truth']:<4} "
              f"{r['chain']:12s} {' | '.join(r['problems'])[:160]}")
    clean = sum(1 for r in results if not r["problems"])
    print(f"\n{clean}/{len(results)} layouts clean. Report written to {write_report(results)}")
    sys.exit(0 if clean == len(results) else 1)