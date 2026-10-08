import pytest

from backend.app.ingestion.pipeline import ingest_statement
from tests.ingestion.layouts import ALL_FIXTURES

PDFS = {f.name: f for f in ALL_FIXTURES if f.filename.endswith(".pdf")}


@pytest.mark.skipif(not PDFS, reason="reportlab not installed")
def test_password_flow():
    fx = PDFS["13_text_pdf_password"]
    r = ingest_statement(fx.data, fx.filename, llm_policy="never")
    assert not r.ok and r.report.error_code == "pdf_password_required"
    r = ingest_statement(fx.data, fx.filename, llm_policy="never", password="wrong")
    assert not r.ok and r.report.error_code == "pdf_password_incorrect"
    r = ingest_statement(fx.data, fx.filename, llm_policy="never", password=fx.password)
    assert r.ok and len(r.rows) == len(fx.truth)