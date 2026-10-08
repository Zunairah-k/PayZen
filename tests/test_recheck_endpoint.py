"""POST /recheck must accept typed rows/meta and return verdicts."""
import os
import sys

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from fastapi.testclient import TestClient  # noqa: E402
import app.main as main  # noqa: E402


def test_recheck_resolves_a_pending_claim_with_a_newer_statement():
    client = TestClient(main.app)
    claim = {"claim_id": "c1", "payer_name": "Test User", "amount": 300.0, "reference": "123456789012",
             "timestamp": "2026-10-08T10:00:00",
             "confidence": {"reference": 1.0, "amount": 1.0, "timestamp": 1.0, "payer_name": 1.0}}
    row = {"row_id": "n1", "datetime": "2026-10-08T10:01:00", "narration": "UPI/CR/123456789012/TEST USER",
           "credit": 300.0, "extracted_reference": "123456789012", "name_hint": "TEST USER"}
    meta = {"coverage_start": "2026-10-08T00:00:00", "coverage_end": "2026-10-08T23:59:59",
            "parse_confidence": 0.97, "row_count": 1}
    previous = {"claim_id": "c1", "status": "Can't verify yet"}
    r = client.post("/recheck", json={"claims": [claim], "rows": [row], "meta": meta,
                                      "previous_verdicts": [previous]})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1 and body[0]["claim_id"] == "c1"
    assert body[0]["status"] in ("Verified", "Likely match")