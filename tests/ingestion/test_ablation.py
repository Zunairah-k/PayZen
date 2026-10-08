"""The ablation script itself: runs offline, never invents model numbers, survives a bad model."""

import json

import pytest

import tests.ingestion.ablation as AB
from backend.app.ingestion.mapping import _name_role
from tests.ingestion.layouts import ALL_FIXTURES


class FakeModel:
    default_model = "fake"

    def __init__(self, mode):
        self.mode, self.calls = mode, 0

    def complete(self, system, user, model):
        self.calls += 1
        if self.mode == "raise":
            raise TimeoutError("slow")
        if self.mode == "garbage":
            return "I cannot help with that"
        cols = json.loads(user.split("\n\n")[0])["columns"]  # retry text is appended after a blank line
        pick = {}
        for c in cols:
            role = _name_role(c["header"])
            if role in ("date", "debit", "credit", "amount", "balance", "reference") and role not in pick:
                pick[role] = c["index"]
        narr = [c["index"] for c in cols if _name_role(c["header"]) == "narration"]
        return json.dumps({"date": pick.get("date"), "narration": narr, "debit": pick.get("debit"),
                           "credit": pick.get("credit"), "amount": pick.get("amount"), "balance": pick.get("balance"),
                           "reference": pick.get("reference")})


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    from backend.app.ingestion import mapping
    mapping._LLM_CACHE.clear()  # a cached reply from one fake must not leak into the next test
    monkeypatch.setattr(AB, "ROOT", tmp_path)  # never overwrite the real docs/ files from a test


def test_off_run_needs_no_model():
    rows = AB.run_mode("never", ALL_FIXTURES)
    s = AB.summarise(rows)
    assert s["n"] == len(ALL_FIXTURES) and s["clean"] == s["n"] and s["answered"] == 0


def test_main_without_a_model_says_not_run_and_writes_files(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(AB, "default_llm_client", lambda: None)
    assert AB.main() == 0
    out = capsys.readouterr().out
    assert "MODEL ON : not run" in out
    md = (tmp_path / "docs" / "ablation_results.md").read_text(encoding="utf-8")
    assert "nothing is claimed about the model" in md
    assert (tmp_path / "docs" / "ablation_results.csv").exists()


@pytest.mark.parametrize("mode", ["garbage", "raise"])
def test_bad_model_changes_nothing_and_errors_are_reported(mode):
    off = AB.summarise(AB.run_mode("never", ALL_FIXTURES))
    on_rows = AB.run_mode("always", ALL_FIXTURES, FakeModel(mode))
    on = AB.summarise(on_rows)
    assert on["clean"] == off["clean"] and on["answered"] == 0 and sum(on["errors"].values()) > 0


def test_working_model_is_counted_and_the_report_is_written(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(AB, "default_llm_client", lambda: FakeModel("smart"))
    assert AB.main() == 0
    out = capsys.readouterr().out
    assert "MODEL ON : " in out and "model answered on" in out and "not run" not in out
    md = (tmp_path / "docs" / "ablation_results.md").read_text(encoding="utf-8")
    assert "Accuracy is the same" in md or "Accuracy differs" in md
