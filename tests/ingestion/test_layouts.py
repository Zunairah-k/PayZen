"""Parse every synthetic layout and compare with ground truth.

pytest:        python -m pytest tests/ingestion -q
table+reports: python -m tests.ingestion.test_layouts      (writes docs/ingestion_test_report.md and docs/format_results.csv)
with the model (needs GEMINI_API_KEY):
               $env:INGEST_TEST_POLICY="always"; python -m tests.ingestion.test_layouts
"""

from __future__ import annotations

import csv
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
ROOT = Path(__file__).resolve().parents[2]


def check(fx: Fixture):
    res = ingest_statement(fx.data, fx.filename, llm_policy=POLICY, password=fx.password)
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


def input_checks():
    """Behaviour on files that are not ordinary statements: every one must give a clear, specific outcome."""
    pdf = next((f for f in ALL_FIXTURES if f.password), None)
    cases = [
        ("Empty file", {"empty"}, dict(data=b"   ", filename="empty.csv")),
        ("Old .xls file", {"xls_unsupported"}, dict(data=b"\xd0\xcf\x11\xe0" + b"\x00" * 64, filename="old.xls")),
        ("Picture of a statement, no consent given", {"image_unsupported", "vision_consent_required"},
         dict(data=b"\x89PNG\r\n\x1a\n" + b"\x00" * 32, filename="photo.png")),
        ("Text that is not a statement", {"no_transactions"},
         dict(data=b"hello there\nthis is not a table\n", filename="notes.txt")),
    ]
    if pdf:
        cases += [
            ("Encrypted PDF, no password", {"pdf_password_required"}, dict(data=pdf.data, filename=pdf.filename)),
            ("Encrypted PDF, wrong password", {"pdf_password_incorrect"},
             dict(data=pdf.data, filename=pdf.filename, password="wrong")),
            ("Encrypted PDF, right password", {"ok"},
             dict(data=pdf.data, filename=pdf.filename, password=pdf.password)),
        ]
    out = []
    for label, expected, kw in cases:
        r = ingest_statement(kw["data"], kw["filename"], llm_policy="never", password=kw.get("password"))
        got = "ok" if r.ok else (r.report.error_code or "error")
        out.append({"case": label, "expected": " or ".join(sorted(expected)), "got": got, "ok": got in expected})
    return out


@pytest.mark.parametrize("fx", ALL_FIXTURES, ids=lambda f: f.name)
def test_layout(fx):
    _, problems = check(fx)
    assert not problems, "; ".join(problems)


def test_input_handling():
    bad = [c for c in input_checks() if not c["ok"]]
    assert not bad, str(bad)


def run_all():
    results = []
    for fx in ALL_FIXTURES:
        res, problems = check(fx)
        rep = res.report
        ch = rep.chain or {}
        llm = rep.llm or {}
        results.append({
            "name": fx.name, "type": Path(fx.filename).suffix.lstrip(".").upper(), "problems": problems,
            "rows": rep.rows_parsed, "truth": len(fx.truth),
            "chain": ch.get("status", "-"),
            "checked": f"{ch.get('passed', 0)}/{ch.get('checked', 0)}" if ch else "-",
            "mapping": rep.mapping_source or "-",
            "confidence": rep.parse_confidence,
            "needs_confirmation": rep.needs_confirmation,
            "llm_used": bool(llm.get("used")) and not llm.get("error"),
        })
    return results


def write_csv(results) -> Path:
    out = ROOT / "docs" / "format_results.csv"
    out.parent.mkdir(exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["layout", "file_type", "result", "rows_parsed", "rows_expected", "chain_status",
                    "chain_checked", "mapping_used", "parse_confidence", "needs_confirmation", "problems"])
        for r in results:
            w.writerow([r["name"], r["type"], "ok" if not r["problems"] else "FAIL", r["rows"], r["truth"],
                        r["chain"], r["checked"], r["mapping"], r["confidence"], r["needs_confirmation"],
                        " | ".join(r["problems"])])
    return out


def write_report(results, checks) -> Path:
    out = ROOT / "docs" / "ingestion_test_report.md"
    out.parent.mkdir(exist_ok=True)
    clean = sum(1 for r in results if not r["problems"])
    llm_used = sum(1 for r in results if r["llm_used"])
    ok_checks = sum(1 for c in checks if c["ok"])
    md = [
        "# Statement ingestion: test report (auto-generated)",
        "",
        f"Generated {_dt.date.today().isoformat()} by `python -m tests.ingestion.test_layouts` "
        f"(language-model policy: `{POLICY}`; model consulted successfully on {llm_used} of {len(results)} layouts).",
        "",
        "## What is covered",
        "",
        "- **Input types:** CSV (any delimiter or encoding), XLSX, pasted text, text PDF (multi-page, repeated headers, password-protected).",
        "- **Layout mess:** junk header and footer blocks, opening-balance rows, wrapped narrations (including splits inside a 12-digit reference), "
        "Indian and European number formats, currency symbols, Dr/Cr suffixes, signed amounts, inverted sign convention, separate time column, "
        "newest-first order, no header row, no balance column.",
        "- **Ground truth:** every parsed row is compared with the invented transaction it was rendered from: date (and time where present), debit, credit, balance and the 12-digit reference.",
        "- **Self-check:** the balance chain must hold on every checked row (expected `unavailable` only for the layout with no balance column).",
        "",
        "## Layout results",
        "",
        f"**{clean} of {len(results)} layouts** matched ground truth on every date, amount, balance and reference.",
        "",
        "| Layout | Type | Result | Rows parsed | Balance chain | Mapping used | Confidence | Asks user to confirm |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        md.append(f"| {r['name']} | {r['type']} | {'ok' if not r['problems'] else 'FAIL'} | {r['rows']}/{r['truth']} "
                  f"| {r['chain']} ({r['checked']}) | {r['mapping']} | {r['confidence']} | {'yes' if r['needs_confirmation'] else 'no'} |")
    md += [
        "",
        "## Input-handling checks",
        "",
        f"{ok_checks} of {len(checks)} cases gave the expected clear outcome (a specific error code the interface can act on, never a crash).",
        "",
        "| Case | Expected | Got | Result |",
        "|---|---|---|---|",
    ]
    for c in checks:
        md.append(f"| {c['case']} | {c['expected']} | {c['got']} | {'ok' if c['ok'] else 'FAIL'} |")
    md += ["", "## Failures", ""]
    failed = [r for r in results if r["problems"]] 
    bad_checks = [c for c in checks if not c["ok"]]
    if failed or bad_checks:
        md += [f"- **{r['name']}**: {'; '.join(r['problems'])}" for r in failed]
        md += [f"- **{c['case']}**: expected {c['expected']}, got {c['got']}" for c in bad_checks]
    else:
        md.append("None on this run.")
    md += [
        "",
        "## Known limits",
        "",
        "- Layouts are invented to imitate common export quirks; they do not claim to match any real bank. Say \"tested on N layouts\".",
        "- Scanned PDFs and photos of statements are handled by the vision path only when the user consents (see the Day 2 report).",
        "- Old `.xls` files ask the user to re-save as `.xlsx` or `.csv`.",
        "- A narration wrapped in the middle of a word gets a space inserted; references are unaffected, name hints can be.",
        "- Rows are assumed to be in monotonic file order (oldest-first or newest-first).",
        "",
    ]
    out.write_text("\n".join(md), encoding="utf-8")
    return out


if __name__ == "__main__":
    results = run_all()
    checks = input_checks()
    print(f"{'layout':36s} {'result':6s} {'rows':>9s} {'chain':12s} problems")
    for r in results:
        print(f"{r['name']:36s} {'FAIL' if r['problems'] else 'ok':6s} {r['rows']:>4}/{r['truth']:<4} "
              f"{r['chain']:12s} {' | '.join(r['problems'])[:160]}")
    print()
    for c in checks:
        print(f"{c['case']:44s} expected {c['expected']:38s} got {c['got']:24s} {'ok' if c['ok'] else 'FAIL'}")
    clean = sum(1 for r in results if not r["problems"])
    ok_checks = sum(1 for c in checks if c["ok"])
    print(f"\n{clean}/{len(results)} layouts clean, {ok_checks}/{len(checks)} input checks ok.")
    print(f"Wrote {write_report(results, checks)} and {write_csv(results)}")
    sys.exit(0 if clean == len(results) and ok_checks == len(checks) else 1)