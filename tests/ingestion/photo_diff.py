"""Shows where the vision model's rows differ from the truth in the 'photographed' condition (synthetic data only)."""

import io

from PIL import Image

from backend.app.ingestion.pipeline import ingest_statement
from tests.ingestion.degradation_eval import SAMPLES, c_photographed
from tests.ingestion.vision_check import render

if __name__ == "__main__":
    for i, truth in enumerate(SAMPLES, start=1):
        img = Image.open(io.BytesIO(render(truth))).convert("RGB")
        data, name = c_photographed(img)
        res = ingest_statement(data, name, llm_policy="never", allow_vision=True)
        by_balance = {str(t.balance): (n, t) for n, t in enumerate(truth, start=1)}
        print(f"\nsample {i}: read {len(res.rows)} of {len(truth)}; rows the parser could not use: "
              f"{res.report.rows_lost} {res.report.lost_samples}")
        seen = set()
        for r in res.rows:
            hit = by_balance.get(str(r.balance))
            if hit is None:
                print(f"   a read row has a balance that is not in the truth: {r.balance} (line {r.source_page_or_row})")
                continue
            n, t = hit
            seen.add(n)
            if r.datetime.date() != t.dt.date():
                print(f"   row {n}: DATE misread -> read {r.datetime.date()}, expected {t.dt.date()}")
            elif (r.credit or 0) != (t.credit or 0) or (r.debit or 0) != (t.debit or 0):
                print(f"   row {n}: AMOUNT misread -> read debit {r.debit} credit {r.credit}, expected debit {t.debit} credit {t.credit}")
        for n, t in enumerate(truth, start=1):
            if n not in seen:
                print(f"   row {n} NOT READ (expected date {t.dt.date()}, balance {t.balance})")