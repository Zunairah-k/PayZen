"""The API really uses the ingestion pipeline (not a stub), end to end over HTTP."""

import pathlib
import sys

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from tests.ingestion.layouts import ALL_FIXTURES, CHAOS_FIXTURES  # noqa: E402

BACKEND = str(pathlib.Path(__file__).resolve().parents[2] / "backend")


@pytest.fixture(scope="module")
def client():
    if BACKEND not in sys.path:
        sys.path.insert(0, BACKEND)
    from fastapi.testclient import TestClient
    import app.main as main  # the real application module

    return TestClient(main.app)


def _upload(client, fx, **form):
    return client.post("/statement/upload", files={"file": (fx.filename, fx.data)}, data=form)


def test_main_imports_and_health(client):
    assert client.get("/health").json() == {"ok": True}


def test_statement_upload_returns_real_rows_not_the_stub(client):
    fx = CHAOS_FIXTURES[3]
    body = _upload(client, fx).json()
    assert len(body["rows"]) == len(fx.truth)
    assert all(r["narration"] != "UPI/123456789012/Test Payer" for r in body["rows"])
    meta = body["meta"]
    assert meta["coverage_start"] and meta["coverage_end"] and meta["row_count"] == len(fx.truth)
    assert meta["balance_chain_result"].startswith("pass")
    assert body["preview"]["status"] == "ok"


def test_row_ids_are_unique_within_a_statement(client):
    for fx in CHAOS_FIXTURES:
        ids = [r["row_id"] for r in _upload(client, fx).json()["rows"]]
        assert len(ids) == len(set(ids)) == len(fx.truth), fx.name


def test_coverage_is_always_set_when_rows_are_returned(client):
    for fx in ALL_FIXTURES:
        if fx.password:
            continue
        body = _upload(client, fx).json()
        assert body["rows"], fx.name
        assert body["meta"]["coverage_start"] and body["meta"]["coverage_end"], fx.name
        assert body["meta"]["coverage_start"] <= body["meta"]["coverage_end"], fx.name


def test_unreadable_file_returns_a_message_and_no_rows(client):
    resp = client.post("/statement/upload", files={"file": ("empty.csv", b"   ")})
    assert resp.status_code == 200
    body = resp.json()
    assert body["rows"] == [] and body["meta"]["coverage_start"] is None
    assert body["preview"]["status"] == "failed" and body["preview"]["error_code"] == "empty"


def test_password_pdf_asks_for_password_then_reads(client):
    fx = next(f for f in ALL_FIXTURES if f.password)
    first = _upload(client, fx).json()
    assert first["preview"]["needs"] == "password" and first["rows"] == []
    second = _upload(client, fx, password=fx.password).json()
    assert len(second["rows"]) == len(fx.truth) and second["preview"]["status"] == "ok"


def test_upload_then_verify_gives_a_verified_verdict_with_a_reply(client):
    fx = CHAOS_FIXTURES[3]
    up = _upload(client, fx).json()
    row = next(r for r in up["rows"] if r["credit"] and r["extracted_reference"])
    claim = {"claim_id": "c1", "amount": row["credit"], "currency": "INR", "reference": row["extracted_reference"],
             "timestamp": row["datetime"], "payer_name": row["name_hint"], "status_shown": "success"}
    out = client.post("/verify", json={"claims": [claim], "rows": up["rows"], "meta": up["meta"]})
    assert out.status_code == 200, out.text
    verdict = out.json()[0]
    assert verdict["status"] == "Verified" and verdict["matched_row_id"] == row["row_id"]
    assert verdict["suggested_reply"]
