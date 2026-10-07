from typing import List, Tuple
from app.models import StatementRow, StatementMeta

def ingest_statement(file_bytes: bytes, filename: str) -> Tuple[List[StatementRow], StatementMeta]:
    rows = [StatementRow(row_id="r1", datetime="2026-10-07T10:31:00",
                         narration="UPI/123456789012/Test Payer", credit=300.0,
                         extracted_reference="123456789012")]
    meta = StatementMeta(coverage_start="2026-10-01", coverage_end="2026-10-07",
                         balance_chain_result="stub", parse_confidence=1.0, row_count=1)
    return rows, meta