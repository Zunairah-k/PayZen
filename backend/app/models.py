from typing import Dict, List, Literal, Optional
from pydantic import BaseModel

Status = Literal["Verified", "Likely match", "Contradicted", "Not found", "Duplicate", "Can't verify yet"]

class Claim(BaseModel):
    claim_id: str
    source_file: Optional[str] = None
    image_hash: Optional[str] = None
    payer_name: Optional[str] = None
    payer_upi_id: Optional[str] = None
    payee_name: Optional[str] = None
    payee_upi_id: Optional[str] = None
    amount: Optional[float] = None
    currency: str = "INR"
    timestamp: Optional[str] = None
    reference: Optional[str] = None
    app_style_guess: Optional[str] = None
    status_shown: Optional[str] = None
    confidence: Dict[str, float] = {}
    extraction_notes: Optional[str] = None

class StatementRow(BaseModel):
    row_id: str
    datetime: Optional[str] = None
    narration: Optional[str] = None
    debit: Optional[float] = None
    credit: Optional[float] = None
    balance: Optional[float] = None
    extracted_reference: Optional[str] = None
    name_hint: Optional[str] = None
    source_page_or_row: Optional[str] = None

class StatementMeta(BaseModel):
    coverage_start: Optional[str] = None
    coverage_end: Optional[str] = None
    mapping_used: Dict[str, str] = {}
    balance_chain_result: Optional[str] = None
    parse_confidence: float = 0.0
    row_count: int = 0
    warnings: List[str] = []

class Verdict(BaseModel):
    claim_id: str
    status: Status
    tier: Optional[int] = None
    matched_row_id: Optional[str] = None
    confidence: float = 0.0
    reasons: List[str] = []
    field_differences: Dict[str, str] = {}
    follow_up_after: Optional[str] = None
    suggested_reply: Optional[str] = None

class VerifyRequest(BaseModel):
    claims: List[Claim]
    rows: List[StatementRow]
    meta: StatementMeta