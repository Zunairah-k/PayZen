"""Live check of the secure email intake (needs AGENTBOXD_API_KEY).  Run: python -m tests.intake.live_demo"""

import time

from backend.app.intake.service import IntakeService

if __name__ == "__main__":
    svc = IntakeService.from_env()
    print("Send test emails to:", svc.address)
    print("Polling every 10 s for 4 minutes. Ctrl+C to stop.\n")
    for _ in range(24):
        out = svc.poll()
        for r in out["records"]:
            a = r.get("assessment", {})
            print(f"[{r['status']:>17}] from {r['from']}  reasons: {a.get('reasons')}")
            for at in r["attachments"]:
                print("      attachment:", at["filename"], at["kind"], at.get("outcome"))
        time.sleep(10)