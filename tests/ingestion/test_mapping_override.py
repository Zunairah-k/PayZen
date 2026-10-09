from backend.app.ingestion.mapping import Mapping
from backend.app.ingestion.pipeline import ingest_statement
from tests.ingestion.layouts import CHAOS_FIXTURES


def test_ambiguous_dates_flagged_then_user_override():
    fx = CHAOS_FIXTURES[0]
    data = "\n".join(fx.data.decode().splitlines()[:13]).encode()  # header + 12 rows: every date is ambiguous
    auto = ingest_statement(data, fx.filename, llm_policy="never")
    assert auto.report.date_order_status == "assumed" and auto.rows[0].datetime.month == 10
    keys = ("date", "time", "narration", "reference", "debit", "credit", "amount", "direction_column",
            "balance", "swap_direction")
    chosen = {k: auto.meta.mapping_used[k] for k in keys}
    res = ingest_statement(data, fx.filename, llm_policy="never",
                           mapping_override=Mapping.from_dict({**chosen, "date_order": "mdy"}, auto.report.columns))
    assert res.ok and res.report.date_order == "mdy" and res.report.date_order_status == "certain"
    assert res.rows[0].datetime.month == 1