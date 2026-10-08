"""Prints the key numbers from the result files, so README and Devpost text can be checked against them.
Run: python -m tests.numbers_sheet"""

import csv
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"


def read(name):
    p = DOCS / name
    if not p.exists():
        return None
    with p.open(encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh))


def show(title, name):
    print(f"\n== {title}  ({name}) ==")
    data = read(name)
    if data is None:
        print("  file not found: run the matching command first")
        return
    for row in data:
        print("  " + " | ".join(row))


if __name__ == "__main__":
    fr = read("format_results.csv")
    if fr:
        head, body = fr[0], fr[1:]
        res, chain = head.index("result"), head.index("chain_status")
        print(f"Layouts matching ground truth: {sum(1 for r in body if r[res] == 'ok')}/{len(body)}")
        print(f"Balance check passed: {sum(1 for r in body if r[chain] == 'pass')}/{len(body)}")
    show("Photo test", "photo_degradation_results.csv")
    show("Model off vs on", "ablation_results.csv")
    show("Email test", "email_eval_results.csv")
    print("\nAlso copy by hand: the 'passed' count from  python -m pytest tests -q")