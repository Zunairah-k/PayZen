from app.models import Claim

def extract_claim(image_bytes: bytes, filename: str) -> Claim:
    return Claim(claim_id=filename, source_file=filename, payer_name="Test Payer",
                 amount=300.0, timestamp="2026-10-07T10:30:00",
                 reference="123456789012", status_shown="success",
                 confidence={"reference": 0.9, "amount": 0.95})