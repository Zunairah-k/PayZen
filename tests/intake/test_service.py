import json

import httpx

from backend.app.intake.client import AgentboxdClient
from backend.app.intake.service import IntakeService
from tests.ingestion.layouts import CHAOS_FIXTURES

STATEMENT = CHAOS_FIXTURES[0]


def make_service(messages, attachments=None, held=None):
    attachments, state = attachments or {}, {"acked": [], "labels": {}}

    def handler(request: httpx.Request) -> httpx.Response:
        path, parts = request.url.path, request.url.path.split("/")
        if path.endswith("/messages/claim"):
            data = [{"lease_id": f"L{i}", "lease_until": "x", "delivery_count": 1, "message": m}
                    for i, m in enumerate(messages)]
            return httpx.Response(200, json={"data": data, "paused": False})
        if path.startswith("/v1/messages/") and path.endswith("/ack"):
            state["acked"].append(parts[3])
            return httpx.Response(200, json={"id": parts[3], "acked_at": "t"})
        if request.method == "PATCH" and path.startswith("/v1/messages/"):
            state["labels"][parts[3]] = json.loads(request.content)["add_labels"]
            return httpx.Response(200, json={})
        if path.startswith("/v1/attachments/"):
            return httpx.Response(200, content=attachments[parts[3]])  # KeyError = we downloaded something we shouldn't
        if request.method == "GET" and path.endswith("/messages"):
            return httpx.Response(200, json={"data": held or [], "next_cursor": None})
        return httpx.Response(404, json={"error": {"code": "not_found", "message": path}})

    client = AgentboxdClient(api_key="mr_test", base_url="https://api.test", transport=httpx.MockTransport(handler))
    return IntakeService(client, "inb1", "payzen@homingbox.net", llm_policy="never"), state


def msg(mid, labels=None, inj=0.01, phi=0.02, attachments=None):
    return {"id": mid, "from": "treasurer@example.com", "subject": "payment proof", "labels": labels or [],
            "ai": {"risk": {"injection": inj, "phishing": phi}},
            "analysis": {"state": "completed", "coverage": "full", "reason": None},
            "screening": {"state": "screened", "reason": None, "released_at": None},
            "attachments": attachments or [], "created_at": "2026-10-08T10:00:00Z"}


def att(aid, name, ctype):
    return {"id": aid, "filename": name, "content_type": ctype, "size_bytes": 1000, "available": True,
            "extraction": {"status": "done"}}


def test_clean_email_flows_into_ingestion():
    svc, state = make_service([msg("m1", attachments=[att("a1", "stmt1.csv", "text/csv")])], {"a1": STATEMENT.data})
    rec = svc.poll()["records"][0]
    out = rec["attachments"][0]["outcome"]
    assert rec["status"] == "accepted" and out["ok"] and out["rows"] == len(STATEMENT.truth) and out["chain"] == "pass"
    assert "m1" in state["acked"] and state["labels"]["m1"] == ["payzen:accepted"]
    assert svc.get_statement_result("m1", "stmt1.csv").ok


def test_prompt_injection_is_quarantined_and_attachments_never_downloaded():
    bad = msg("m2", labels=["ai:injection-risk"], inj=0.97, attachments=[att("a2", "stmt1.csv", "text/csv")])
    svc, state = make_service([bad])  # no attachment bytes registered: a download would crash the test
    rec = svc.poll()["records"][0]
    assert rec["status"] == "quarantined" and rec["attachments"] == []
    assert svc.alerts()[0]["severity"] == "high" and "m2" in state["acked"]
    assert state["labels"]["m2"] == ["payzen:quarantined"]


def test_spoofed_sender_is_quarantined_with_medium_severity():
    svc, _ = make_service([msg("m3", labels=["dmarc-fail"])])
    rec = svc.poll()["records"][0]
    assert rec["status"] == "quarantined" and rec["assessment"]["severity"] == "medium"


def test_mail_held_by_agentboxd_is_reported_without_content():
    held = {"id": "h1", "from": "x@evil.test", "subject": "[held: injection_risk]", "labels": ["ai:injection-risk"],
            "screening": {"state": "held", "reason": "injection_risk"},
            "withheld": {"state": "held", "reason": "injection_risk", "attachments": 1}}
    svc, _ = make_service([], held=[held])
    rec = svc.poll()["records"][0]
    assert rec["status"] == "held_by_agentboxd" and rec["subject"] == "(withheld)"
    assert svc.poll()["processed"] == 0  # not reported twice


def test_screenshot_goes_to_registered_handler():
    svc, _ = make_service([msg("m4", attachments=[att("a4", "proof.png", "image/png")])], {"a4": b"\x89PNG-bytes"})
    seen = {}
    svc.register_screenshot_handler(lambda data, name, meta: seen.update(n=len(data), f=name) or {"claims": 1})
    out = svc.poll()["records"][0]["attachments"][0]["outcome"]
    assert out == {"ok": True, "result": {"claims": 1}} and seen == {"n": 10, "f": "proof.png"}