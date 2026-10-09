"""The screenshot evaluation script, tested with an oracle provider (no key needed)."""

import csv
import importlib.util
import json
import sys
from pathlib import Path

from backend.app.services.extractor import RawExtraction, VisionProvider

ROOT = Path(__file__).resolve().parents[1]


def _load():
    sys.path.insert(0, str(ROOT / "backend"))
    spec = importlib.util.spec_from_file_location("screenshot_eval", ROOT / "eval" / "screenshot_eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Oracle(VisionProvider):
    """Returns the ground truth for whichever claim the file name says (e.g. claim_007.png)."""
    name, is_mock = "oracle-test", True

    def __init__(self, truth):
        self.truth = truth

    def extract_fields(self, image_bytes, filename):
        t = self.truth[Path(filename).stem]
        return RawExtraction.from_dict({"amount": t["amount"], "reference": t["reference"], "timestamp": t["timestamp"],
                                        "payer_name": t["payer_name"]}, provider_name=self.name, is_mock=True)


def test_perfect_reader_gives_perfect_fields_and_no_false_verified(tmp_path, monkeypatch):
    mod = _load()
    monkeypatch.setattr(mod, "OUT", tmp_path)
    truth = {r["claim_id"]: r for r in csv.DictReader(open(mod.DATA / "ground_truth.csv", encoding="utf-8"))}
    assert mod.main(["--limit", "20", "--conditions", "clean"], provider=Oracle(truth)) == 0
    res = json.loads((tmp_path / "screenshot_eval.json").read_text(encoding="utf-8"))[0]
    assert 20 <= res["images"] <= 28 and res["empty_reads"] == 0
    assert res["amount_ok"] == res["reference_ok"] == res["timestamp_ok"] == res["images"]
    assert res["amount_wrong"] == 0 and res["reference_wrong"] == 0 and res["false_verified"] == []
    assert "False-Verified" in (tmp_path / "screenshot_eval.md").read_text(encoding="utf-8")


def test_no_key_and_no_provider_stops_politely(monkeypatch, capsys):
    mod = _load()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert mod.main(["--limit", "2"]) == 1
    assert "GEMINI_API_KEY" in capsys.readouterr().out
