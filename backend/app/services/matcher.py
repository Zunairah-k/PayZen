from typing import List
from app.models import Claim, StatementRow, StatementMeta, Verdict

def verify(claims: List[Claim], rows: List[StatementRow], meta: StatementMeta) -> List[Verdict]:
    by_ref = {r.extracted_reference: r for r in rows if r.extracted_reference}
    out = []
    for c in claims:
        row = by_ref.get(c.reference)
        if row:
            out.append(Verdict(claim_id=c.claim_id, status="Verified", tier=1,
                               matched_row_id=row.row_id, confidence=0.95,
                               reasons=["Reference found in statement credit"]))
        else:
            out.append(Verdict(claim_id=c.claim_id, status="Not found", confidence=0.5,
                               reasons=["No matching credit in the covered period"]))
    return out