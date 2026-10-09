"""Read a folder of YOUR OWN real payment screenshots with the real screenshot reader.

    python -m tests.ingestion.real_screenshot_check "C:\\realdata\\yourname\\shots"

Needs GEMINI_API_KEY loaded. The IMAGES ARE SENT TO GOOGLE, so first cover names, UPI IDs and phone numbers with
solid black boxes (keep the amount, the date and time, and the 12-digit UPI transaction ID visible).
Compare each printed line with the picture by eye and note which fields are right.
"""

import sys
from pathlib import Path

from backend.app.services.extractor import extract_claim_detailed
from backend.app.services.vision_gemini import register_gemini_provider

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    if not register_gemini_provider():
        print("No GEMINI_API_KEY is loaded, so nothing can be read. Load your keys and run again.")
        raise SystemExit(1)
    files = sorted(p for p in Path(sys.argv[1]).iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
    if not files:
        print("No .png / .jpg files found in that folder.")
        raise SystemExit(1)
    for f in files:
        c = extract_claim_detailed(f.read_bytes(), f.name).claim
        print(f"{f.name}: amount={c.amount} reference={c.reference} time={c.timestamp} "
              f"status={c.status_shown} confidence={c.confidence}")
