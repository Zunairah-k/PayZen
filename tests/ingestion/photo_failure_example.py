"""Shows which row the vision model missed in the 'photographed' condition (synthetic data only)."""

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
        got = {(r.datetime.date().isoformat(), str(r.balance)) for r in res.rows}
        exp = [(t.dt.date().isoformat(), str(t.balance)) for t in truth]
        missing = [m for m in exp if m not in got]
        print(f"sample {i}: read {len(res.rows)} of {len(truth)} | balance check {res.report.chain.get('status')} "
              f"| asked to confirm: {res.report.needs_confirmation}")
        print("   missing row(s) (date, balance):", missing, "| position(s):", [exp.index(m) + 1 for m in missing])
        print("   message shown to the user:", res.report.user_message)