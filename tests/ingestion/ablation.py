"""Model OFF versus model ON, across every layout (plus a small stress set).

    python -m tests.ingestion.ablation

Always runs OFF (offline, deterministic mapper + arithmetic check only).
Runs ON only when a language-model client is available (set GEMINI_API_KEY).
If it is not available the report says "not run" - numbers are never invented.

Writes docs/ablation_results.md and docs/ablation_results.csv, and prints the two
summary lines you can copy into the results section.

What "ON" changes: with the model on, the pipeline also asks it which column is
which (it sees only column names and masked sample rows). Either way the balance
check decides which mapping is kept. So the honest question this answers is:
does the model add anything on top of header words + cell contents + arithmetic?
"""

from __future__ import annotations

import csv
import datetime as _dt
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

import backend.app.ingestion.pipeline as P
import tests.ingestion.test_layouts as TL
from backend.app.ingestion.mapping import default_llm_client
from tests.ingestion.layouts import ALL_FIXTURES, TRUTH, Fixture, _csv, f2, narration

ROOT = Path(__file__).resolve().parents[2]


# ---- stress set: unfamiliar headers (NOT part of the standard 17) ----------------------------


def _stress_fixtures() -> List[Fixture]:
    t = TRUTH
    hindi = [["Tarikh", "Vivaran", "Nikasi", "Jama", "Shesh"]]  # date, description, withdrawal, deposit, balance
    for x in t:
        hindi.append([x.dt.strftime("%d/%m/%Y"), narration(x), f2(x.debit), f2(x.credit), f2(x.balance)])
    odd = [["Posted", "Memo line", "Money in", "Money out", "Running total"]]  # credit BEFORE debit, unfamiliar words
    for x in t:
        odd.append([x.dt.strftime("%d-%b-%Y"), narration(x), f2(x.credit), f2(x.debit), f2(x.balance)])
    return [
        Fixture("S1_transliterated_headers", "s1.csv", _csv(hindi).encode(), t, has_time=False),
        Fixture("S2_unfamiliar_headers_credit_first", "s2.csv", _csv(odd).encode(), t, has_time=False),
    ]


# ---- running one mode -----------------------------------------------------------------------


@contextmanager
def _mode(policy: str, client: Any = None):
    old_policy, old_client = TL.POLICY, P.default_llm_client
    TL.POLICY = policy
    if client is not None:
        P.default_llm_client = lambda: client
    try:
        yield
    finally:
        TL.POLICY, P.default_llm_client = old_policy, old_client


def run_mode(policy: str, fixtures: List[Fixture], client: Any = None) -> List[Dict[str, Any]]:
    out = []
    with _mode(policy, client):
        for fx in fixtures:
            res, problems = TL.check(fx)
            rep = res.report
            llm = rep.llm or {}
            out.append({
                "layout": fx.name, "type": Path(fx.filename).suffix.lstrip(".").upper(),
                "clean": not problems, "problems": problems, "chain": (rep.chain or {}).get("status", "-"),
                "mapping": rep.mapping_source or "-", "confidence": rep.parse_confidence,
                "confirm": rep.needs_confirmation,
                "model_answered": bool(llm.get("used")) and not llm.get("error"),
                "model_error": llm.get("error"), "agrees": llm.get("agrees_with_deterministic"),
            })
    return out


def summarise(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    answered = [r for r in rows if r["model_answered"]]
    return {
        "n": n, "clean": sum(r["clean"] for r in rows), "chain_pass": sum(r["chain"] == "pass" for r in rows),
        "chain_unavailable": sum(r["chain"] == "unavailable" for r in rows),
        "confirm": sum(r["confirm"] for r in rows),
        "mean_conf": sum(r["confidence"] for r in rows) / n if n else 0.0,
        "answered": len(answered), "agrees": sum(1 for r in answered if r["agrees"]),
        "kept_llm": sum(1 for r in rows if str(r["mapping"]).startswith("llm")),
        "errors": Counter(r["model_error"] for r in rows if r["model_error"]),
    }


def summary_line(label: str, s: Optional[Dict[str, Any]], with_model: bool) -> str:
    if s is None:
        return f"{label}: not run (no language-model client available; set GEMINI_API_KEY)."
    line = (f"{label}: {s['clean']}/{s['n']} layouts match ground truth | balance check passed on "
            f"{s['chain_pass']}/{s['n']} ({s['chain_unavailable']} has no balance column) | "
            f"asks the user to confirm on {s['confirm']} | mean confidence {s['mean_conf']:.2f}")
    if with_model:
        line += (f" | model answered on {s['answered']}/{s['n']}, agreed with the deterministic mapper on "
                 f"{s['agrees']}/{s['answered']}, its mapping was the one kept on {s['kept_llm']}")
    return line


# ---- report ------------------------------------------------------------------------------


def _table(off, on) -> List[str]:
    md = ["| Layout | Type | OFF result | OFF mapping | ON result | ON mapping | Model agreed |", "|---|---|---|---|---|---|---|"]
    for i, a in enumerate(off):
        b = on[i] if on else None
        md.append(f"| {a['layout']} | {a['type']} | {'ok' if a['clean'] else 'FAIL'} | {a['mapping']} | "
                  f"{('ok' if b['clean'] else 'FAIL') if b else '-'} | {b['mapping'] if b else '-'} | "
                  f"{('yes' if b['agrees'] else 'no' if b['model_answered'] else 'model did not answer') if b else '-'} |")
    return md


def write_report(off_std, on_std, off_stress, on_stress) -> Path:
    s_off, s_on = summarise(off_std), (summarise(on_std) if on_std else None)
    t_off, t_on = summarise(off_stress), (summarise(on_stress) if on_stress else None)
    lines = [
        "# Ablation: language model off versus on", "",
        f"Generated {_dt.date.today().isoformat()} by `python -m tests.ingestion.ablation`.", "",
        "**What is compared.** OFF: columns are identified from header words and cell contents, and the balance check "
        "picks the mapping that adds up. ON: the model is also asked (it sees only column names and masked sample rows) "
        "and the balance check still decides which mapping is kept.", "",
        "## Summary (copy these two lines)", "",
        "```", summary_line("MODEL OFF", s_off, False), summary_line("MODEL ON ", s_on, True), "```", "",
        "## Standard layouts", "", *_table(off_std, on_std), "",
        "## Stress set: unfamiliar headers (not part of the standard layouts)", "",
        "```", summary_line("MODEL OFF", t_off, False), summary_line("MODEL ON ", t_on, True), "```", "",
        *_table(off_stress, on_stress), "",
        "## How to read this", "",
    ]
    if s_on is None:
        lines.append("The ON run did not happen, so nothing is claimed about the model's effect. Set `GEMINI_API_KEY` and run again.")
    else:
        same = (s_off["clean"], t_off["clean"]) == (s_on["clean"], t_on["clean"])
        if same:
            lines.append("Accuracy is the same with the model off and on. That is the honest finding: header words, cell "
                         "contents and the arithmetic check already identify these layouts, so the model is a safety net for "
                         "layouts we have not seen, not the source of the accuracy we report.")
        else:
            lines.append("Accuracy differs between the two runs; see the tables above for which layouts changed.")
        if s_on["errors"]:
            lines.append("")
            lines.append("Model problems during the ON run (those layouts fell back to the deterministic mapper): "
                         + "; ".join(f"{k} x{v}" for k, v in s_on["errors"].items()) + ".")
    lines += ["", "Layouts are invented to imitate common export quirks. Say \"tested on N layouts\"; do not claim every bank.", ""]
    out = ROOT / "docs" / "ablation_results.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def write_csv(off_std, on_std, off_stress, on_stress) -> Path:
    out = ROOT / "docs" / "ablation_results.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["set", "layout", "mode", "result", "chain", "mapping", "confidence", "asks_to_confirm", "model_answered", "model_agrees"])
        for name, off, on in (("standard", off_std, on_std), ("stress", off_stress, on_stress)):
            for mode, rows in (("off", off), ("on", on)):
                for r in rows or []:
                    w.writerow([name, r["layout"], mode, "ok" if r["clean"] else "FAIL", r["chain"], r["mapping"],
                                r["confidence"], r["confirm"], r["model_answered"], r["agrees"]])
    return out


def main(client: Any = None) -> int:
    client = client if client is not None else default_llm_client()
    stress = _stress_fixtures()
    off_std, off_stress = run_mode("never", ALL_FIXTURES), run_mode("never", stress)
    on_std = on_stress = None
    if client is not None:
        on_std, on_stress = run_mode("always", ALL_FIXTURES, client), run_mode("always", stress, client)
    print(summary_line("MODEL OFF", summarise(off_std), False))
    print(summary_line("MODEL ON ", summarise(on_std) if on_std else None, True))
    print(f"\nStress set (unfamiliar headers):\n{summary_line('MODEL OFF', summarise(off_stress), False)}")
    print(summary_line("MODEL ON ", summarise(on_stress) if on_stress else None, True))
    print(f"\nWrote {write_report(off_std, on_std, off_stress, on_stress)} and {write_csv(off_std, on_std, off_stress, on_stress)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
