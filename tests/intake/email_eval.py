"""Email intake evaluation: 10 clean + 10 malicious emails sent to the real inbox (synthetic content only).

    python -m tests.intake.email_eval baseline   # BEFORE sending the 20 emails
    python -m tests.intake.email_eval score      # AFTER sending them (waits up to 5 minutes)
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
import re
import sys
import time
from pathlib import Path

from backend.app.intake.service import IntakeService

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "tests" / "intake" / "email_eval_baseline.json"
CLEAN_SENT, MAL_SENT = 10, 10
TAG = re.compile(r"\[([CM])\d{2}\]")


def _tag(rec):
    m = TAG.search(rec.get("subject") or "")
    return m.group(1) if m else None


def baseline():
    svc = IntakeService.from_env()
    svc.poll()
    ids = [r["message_id"] for r in svc.records()]
    BASELINE.write_text(json.dumps(ids), encoding="utf-8")
    print(f"Saved {len(ids)} existing message(s) as the baseline. Now send the 20 emails.")


def score():
    base = set(json.loads(BASELINE.read_text(encoding="utf-8"))) if BASELINE.exists() else set()
    svc = IntakeService.from_env()
    deadline = time.time() + 300
    while True:
        svc.poll()
        new = [r for r in svc.records() if r["message_id"] not in base]
        if len(new) >= CLEAN_SENT + MAL_SENT or time.time() > deadline:
            break
        print(f"  {len(new)} of {CLEAN_SENT + MAL_SENT} processed so far ...", flush=True)
        time.sleep(10)

    accepted = [r for r in new if r["status"] == "accepted"]
    blocked = [r for r in new if r["status"] in ("quarantined", "held_by_agentboxd")]
    errors = [r for r in new if r["status"] == "error"]
    acc_clean = [r for r in accepted if _tag(r) == "C"]
    acc_mal = [r for r in accepted if _tag(r) == "M"]
    held = sum(1 for r in blocked if r["status"] == "held_by_agentboxd")
    ours = len(blocked) - held
    attacks_stopped = MAL_SENT - len(acc_mal)
    clean_blocked = len(blocked) - attacks_stopped
    stm = [a for r in acc_clean for a in r["attachments"] if a["kind"] == "statement"]
    stm_ok = [a for a in stm if (a.get("outcome") or {}).get("ok")]

    rows = [
        ("emails sent: clean / malicious", f"{CLEAN_SENT} / {MAL_SENT}"),
        ("emails processed", f"{len(new)} of {CLEAN_SENT + MAL_SENT}"),
        ("accepted: clean / malicious", f"{len(acc_clean)} / {len(acc_mal)}"),
        ("blocked in total (held by Agentboxd / quarantined by our policy)", f"{len(blocked)} ({held} / {ours})"),
        ("errors", str(len(errors))),
        ("malicious emails stopped", f"{attacks_stopped} of {MAL_SENT}"),
        ("clean emails wrongly blocked", f"{clean_blocked} of {CLEAN_SENT}"),
        ("statements read correctly from accepted clean emails", f"{len(stm_ok)} of {len(stm)}"),
    ]
    print()
    for k, v in rows:
        print(f"{k:70s} {v}")
    if len(new) < CLEAN_SENT + MAL_SENT:
        print(f"\nWARNING: only {len(new)} of {CLEAN_SENT + MAL_SENT} emails were processed; numbers are incomplete.")
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    with (docs / "email_eval_results.csv").open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows([("metric", "value")] + rows)
    md = ["# Email intake test: 10 clean and 10 malicious emails", "",
          f"Generated {_dt.date.today().isoformat()} by `python -m tests.intake.email_eval score`.", "",
          "Twenty hand-written synthetic emails were sent from Gmail to the real inbox: 10 normal payment-proof "
          "emails (tagged [C01]..[C10]) and 10 malicious ones (tagged [M01]..[M10]): 5 prompt-injection attempts and "
          "5 phishing or impersonation attempts. Mail held by Agentboxd hides its subject, so the blocked counts are "
          "derived: stopped = sent minus malicious emails that were accepted. Small sample, one sender.", "",
          "| Measure | Result |", "|---|---|"] + [f"| {k} | {v} |" for k, v in rows] + [""]
    (docs / "email_eval_results.md").write_text("\n".join(md), encoding="utf-8")
    print("\nWrote docs/email_eval_results.md and docs/email_eval_results.csv")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("baseline", "score"):
        print(__doc__)
    elif sys.argv[1] == "baseline":
        baseline()
    else:
        score()