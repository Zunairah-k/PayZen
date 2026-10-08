from backend.app.ingestion.adapter import to_shared
from backend.app.ingestion.pipeline import ingest_statement
from tests.ingestion.layouts import CHAOS_FIXTURES


def test_adapter_roundtrip():
    fx = CHAOS_FIXTURES[0]
    res = ingest_statement(fx.data, fx.filename, llm_policy="never")
    rows, meta = to_shared(res)
    assert len(rows) == len(fx.truth) == meta.row_count
    assert isinstance(rows[0].credit, float) or isinstance(rows[0].debit, float)
    assert meta.coverage_start and meta.coverage_end and meta.balance_chain_result.startswith("pass")


def test_adapter_failure_gives_message_not_crash():
    rows, meta = to_shared(ingest_statement(b"  ", "empty.csv", llm_policy="never"))
    assert rows == [] and meta.warnings