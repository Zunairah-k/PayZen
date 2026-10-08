"""PayZen synthetic data generator. Everything here is fake and random."""
import csv
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from string import Template
import shutil

from playwright.sync_api import sync_playwright

rng = random.Random(42)
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "synthetic"
SHOTS = OUT / "screenshots"
STMTS = OUT / "statements"
for d in (SHOTS, STMTS):
    d.mkdir(parents=True, exist_ok=True)

FIRST = ["Aarav", "Vivaan", "Aditya", "Rohan", "Karthik", "Ishaan", "Arjun", "Sai", "Rahul", "Nikhil",
         "Ananya", "Diya", "Meera", "Priya", "Sneha", "Kavya", "Isha", "Pooja", "Neha", "Riya",
         "Fatima", "Ayesha", "Sana", "Imran", "Faizan", "Harsha", "Lakshmi", "Manoj", "Naveen", "Swathi"]
LAST = ["Reddy", "Sharma", "Khan", "Rao", "Patel", "Iyer", "Nair", "Gupta", "Verma", "Das"]
VENDORS = ["Sound Hire Co", "Print Shop", "Banner Works", "Catering Hub", "Stage Rentals",
           "Trophy Mart", "Stationery Point", "Photo Studio"]

PAYEE_NAME = "Technova Fest Fund"
PAYEE_UPI = "technovafest@examplebank"
OPENING = 90000.00

used_refs = set()


def new_ref():
    while True:
        r = str(rng.randint(2, 9)) + "".join(str(rng.randint(0, 9)) for _ in range(11))
        if r not in used_refs:
            used_refs.add(r)
            return r


def rand_ts():
    return datetime(2026, 10, 1 + rng.randint(0, 5), rng.randint(8, 22), rng.randint(0, 59), rng.randint(0, 59))


def indian(n):
    s = f"{abs(n):.2f}"
    whole, frac = s.split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return ("-" if n < 0 else "") + whole + "." + frac


# ---------------------------------------------------------------- master transactions
people, seen = [], set()
while len(people) < 60:
    p = (rng.choice(FIRST), rng.choice(LAST))
    if p not in seen:
        seen.add(p)
        people.append(p)

txns = []
for f, l in people:
    txns.append({
        "kind": "credit", "name": f"{f} {l}", "upi": f"{f.lower()}{rng.randint(10, 99)}@examplebank",
        "amount": float(rng.choices([300, 500, 150, 600], [70, 12, 10, 8])[0]),
        "ts": rand_ts(), "ref": new_ref(), "ref_in_narration": rng.random() < 0.75,
    })
for v in VENDORS:
    txns.append({
        "kind": "debit", "name": v, "upi": "", "amount": float(rng.randint(8, 60) * 100),
        "ts": rand_ts(), "ref": new_ref(), "ref_in_narration": True,
    })
txns.sort(key=lambda t: t["ts"])

bal = OPENING
for t in txns:
    bal += t["amount"] if t["kind"] == "credit" else -t["amount"]
    t["balance"] = round(bal, 2)
assert all(t["balance"] > 0 for t in txns)


def narr(layout, t):
    n, r, u = t["name"].upper(), t["ref"], t["upi"]
    if t["kind"] == "debit":
        return {1: f"UPI/DR/{r}/{n}", 2: f"UPI-{r}-{n}-PAID", 3: f"Paid to {n} Ref {r}",
                4: f"{r} UPI DEBIT {n}", 5: f"UPI/{n}/{r}/Payment to merchant"}[layout]
    if t["ref_in_narration"]:
        return {1: f"UPI/CR/{r}/{n}/{u}", 2: f"UPI-{r}-{n}-{u}", 3: f"Received from {n} ({u}) Ref {r}",
                4: f"{r} UPI CREDIT {n}", 5: f"UPI/{n}/{r}/Payment from app"}[layout]
    return {1: f"UPI/CR/{n}/{u}", 2: f"UPI-{n}-{u}", 3: f"Received from {n} ({u})",
            4: f"UPI CREDIT {n}", 5: f"UPI/{n}/Payment from app"}[layout]


def signed(t):
    return t["amount"] if t["kind"] == "credit" else -t["amount"]


def write_csv(name, rows):
    with open(STMTS / name, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)


# 1: standard columns, DD/MM/YY, date only
rows = [["Date", "Narration", "Chq/Ref No", "Value Date", "Withdrawal Amt", "Deposit Amt", "Closing Balance"]]
for i, t in enumerate(txns):
    d = t["ts"].strftime("%d/%m/%y")
    rows.append([d, narr(1, t), f"{100000 + i}", d,
                 f"{t['amount']:.2f}" if t["kind"] == "debit" else "",
                 f"{t['amount']:.2f}" if t["kind"] == "credit" else "", f"{t['balance']:.2f}"])
write_csv("statement_01_standard.csv", rows)

# 2: single amount column with Dr/Cr suffix, date only
rows = [["Date", "Description", "Amount", "Balance"]]
for t in txns:
    rows.append([t["ts"].strftime("%d-%m-%Y"), narr(2, t),
                 f"{t['amount']:.2f} {'Cr' if t['kind'] == 'credit' else 'Dr'}", f"{t['balance']:.2f}"])
write_csv("statement_02_drcr.csv", rows)

# 3: signed amount, ISO datetime
rows = [["Txn Date", "Details", "Amount", "Running Balance"]]
for t in txns:
    rows.append([t["ts"].strftime("%Y-%m-%d %H:%M:%S"), narr(3, t), f"{signed(t):.2f}", f"{t['balance']:.2f}"])
write_csv("statement_03_signed.csv", rows)

# 4: DD-Mon-YYYY with separate time column
rows = [["Date", "Time", "Particulars", "Debit", "Credit", "Balance"]]
for t in txns:
    rows.append([t["ts"].strftime("%d-%b-%Y"), t["ts"].strftime("%H:%M"), narr(4, t),
                 f"{t['amount']:.2f}" if t["kind"] == "debit" else "",
                 f"{t['amount']:.2f}" if t["kind"] == "credit" else "", f"{t['balance']:.2f}"])
write_csv("statement_04_datetime.csv", rows)

# 5: junk header block, Indian grouping, Rs. prefix, footer totals
tc = sum(t["amount"] for t in txns if t["kind"] == "credit")
td = sum(t["amount"] for t in txns if t["kind"] == "debit")
rows = [["ACCOUNT STATEMENT"], ["Account Holder: TECHNOVA FEST FUND"], ["Account No: XXXXXX4821"],
        ["Statement Period: 01-Oct-2026 to 06-Oct-2026"], [],
        ["Date", "Narration", "Debit", "Credit", "Balance"]]
for t in txns:
    rows.append([t["ts"].strftime("%d/%m/%Y"), narr(5, t),
                 f"Rs. {indian(t['amount'])}" if t["kind"] == "debit" else "",
                 f"Rs. {indian(t['amount'])}" if t["kind"] == "credit" else "", f"Rs. {indian(t['balance'])}"])
rows += [[], [f"Total Debits: Rs. {indian(td)}"], [f"Total Credits: Rs. {indian(tc)}"], ["*** End of statement ***"]]
write_csv("statement_05_indian_junk.csv", rows)

# ---------------------------------------------------------------- claims (genuine only, for Day 1)

CSS = ("body{margin:0;font-family:'Segoe UI',Arial,sans-serif}.rows{padding:0 22px}"
       ".r{display:flex;justify-content:space-between;gap:16px;padding:12px 0;"
       "border-bottom:1px solid rgba(128,128,128,.25);font-size:14px}.r span{color:#888}"
       ".r b{text-align:right;font-weight:600}.r small{font-weight:400;color:#888}"
       ".c{width:64px;height:64px;border-radius:50%;margin:0 auto 14px;color:#fff;font-size:38px;line-height:64px}")
ROWS = ('<div class="rows"><div class="r"><span>To</span><b>$payee<br><small>$payee_upi</small></b></div>'
        '<div class="r"><span>From</span><b>$payer<br><small>$payer_upi</small></b></div>'
        '<div class="r"><span>$ref_label</span><b>$ref</b></div>'
        '<div class="r"><span>$decoy_label</span><b>$decoy</b></div></div>')

VARIANTS = [
    # A: clean light
    '<div style="background:#fff;color:#222;min-height:780px"><div style="padding:40px 24px 20px;text-align:center">'
    '<div class="c" style="background:#1f9d55">&#10003;</div><div style="color:#1f9d55;font-weight:600">$status</div>'
    '<div style="font-size:40px;font-weight:700;margin:10px 0 4px">$amount</div>'
    '<div style="color:#777;font-size:13px">$when</div></div>' + ROWS + '</div>',
    # B: dark
    '<div style="background:#101418;color:#e8eef3;min-height:780px"><div style="padding:40px 24px 20px;text-align:center">'
    '<div class="c" style="background:#14b8a6">&#10003;</div><div style="color:#14b8a6;font-weight:600">$status</div>'
    '<div style="font-size:38px;font-weight:700;margin:10px 0 4px">$amount</div>'
    '<div style="color:#8a97a4;font-size:13px">$when</div></div>' + ROWS + '</div>',
    # C: blue header card
    '<div style="background:#eef2fa;color:#1c2540;min-height:780px"><div style="background:#2b5fd9;color:#fff;'
    'padding:36px 24px 70px;text-align:center"><div style="font-size:15px">$status</div>'
    '<div style="font-size:42px;font-weight:700;margin-top:8px">$amount</div></div>'
    '<div style="background:#fff;margin:-40px 14px 0;border-radius:14px;padding:14px 0;'
    'box-shadow:0 4px 14px rgba(0,0,0,.1)"><div style="text-align:center;color:#777;font-size:13px;padding-bottom:6px">'
    '$when</div>' + ROWS + '</div></div>',
    # D: receipt style
    '<div style="background:#e6e6e6;padding:24px 16px;min-height:780px;box-sizing:border-box">'
    '<div style="background:#fff;padding:22px 6px;font-family:Consolas,monospace;color:#111">'
    '<div style="text-align:center;font-weight:700;letter-spacing:2px">PAYMENT RECEIPT</div>'
    '<div style="text-align:center;margin:8px 0">$status</div>'
    '<div style="text-align:center;font-size:30px;font-weight:700;margin:6px 0">$amount</div>'
    '<div style="text-align:center;color:#555;font-size:12px;margin-bottom:8px">$when</div>' + ROWS + '</div></div>',
]
REF_LABELS = ["UPI Ref No.", "UTR", "Transaction ID", "Reference No."]
DECOY_LABELS = ["Order ID", "Txn Ref", "Payment ID"]
STATUSES = ["Payment Successful", "Paid", "Completed", "Transaction Successful"]


def when(ts, style):
    return [ts.strftime("%d %b %Y, %I:%M %p"), ts.strftime("%d/%m/%Y %H:%M"),
            ts.strftime("%b %d, %Y at %I:%M %p")][style]


# ---------------------------------------------------------------- v2: 100 claims
def new_person():
    while True:
        f, l = rng.choice(FIRST), rng.choice(LAST)
        if (f, l) not in seen:
            seen.add((f, l))
            return f"{f} {l}", f"{f.lower()}{rng.randint(10, 99)}@examplebank"


# 5 delayed payments: these credits exist ONLY in a later statement (7 Oct)
late = []
for k in range(5):
    name, upi = new_person()
    late.append({"kind": "credit", "name": name, "upi": upi, "amount": 300.0,
                 "ts": datetime(2026, 10, 7, rng.randint(9, 21), rng.randint(0, 59), 0),
                 "ref": new_ref(), "ref_in_narration": k != 4})
late.sort(key=lambda t: t["ts"])
for t in late:
    bal += t["amount"]
    t["balance"] = round(bal, 2)
rows = [["Txn Date", "Details", "Amount", "Running Balance"]]
for t in late:
    rows.append([t["ts"].strftime("%Y-%m-%d %H:%M:%S"), narr(3, t), f"{signed(t):.2f}", f"{t['balance']:.2f}"])
write_csv("statement_06_later.csv", rows)

credits = [t for t in txns if t["kind"] == "credit"]
rng.shuffle(credits)
edit_src = [t for t in credits if t["ref_in_narration"]][:10]
genuine = [t for t in credits if t not in edit_src]  # 50

claims = []


def add(cat, name, upi, amount, ts, ref, expected, reason, after="", original="",
        payee=PAYEE_NAME, payee_upi=PAYEE_UPI, rin="", reuse=""):
    claims.append({"id": f"claim_{len(claims) + 1:03d}", "cat": cat, "name": name, "upi": upi,
                   "amount": float(amount), "ts": ts, "ref": ref, "expected": expected, "after": after,
                   "reason": reason, "original": original, "payee": payee, "payee_upi": payee_upi,
                   "rin": rin, "reuse": reuse})


# genuine (55)
for t in genuine:
    add("genuine", t["name"], t["upi"], t["amount"], t["ts"], t["ref"],
        "Verified" if t["ref_in_narration"] else "Likely match",
        "Genuine; reference is in the narration" if t["ref_in_narration"]
        else "Genuine; no reference in narration, must match on amount, time and name",
        rin=t["ref_in_narration"])
for t in late:
    add("genuine_delayed", t["name"], t["upi"], t["amount"], t["ts"], t["ref"], "Can't verify yet",
        "Genuine payment dated after the first statement ends",
        after="Verified" if t["ref_in_narration"] else "Likely match", rin=t["ref_in_narration"])

# seeded fakes (45)
for t in edit_src:  # edited amount (10)
    add("edited_amount", t["name"], t["upi"], t["amount"] * 10, t["ts"], t["ref"], "Contradicted",
        f"Reference matches a credit of Rs. {t['amount']:.0f}; screenshot says Rs. {t['amount'] * 10:.0f}", rin=True)
for g in rng.sample(genuine, 10):  # invented reference (10)
    name, upi = new_person()
    add("invented_reference", name, upi, g["amount"], g["ts"] + timedelta(minutes=rng.randint(-20, 20)),
        new_ref(), "Not found", "Amount and time look right, but the reference is not in the statement")
src = [c for c in claims if c["cat"] == "genuine" and c["rin"]]
picks = rng.sample(src, 8)
for c in picks[:4]:  # same reference, different payer (4)
    name, upi = new_person()
    add("duplicate_reference", name, upi, c["amount"], c["ts"], c["ref"], "Duplicate",
        "Reference already belongs to another claim", original=c["id"])
for c in picks[4:]:  # identical screenshot reused (4)
    add("duplicate_image", c["name"], c["upi"], c["amount"], c["ts"], c["ref"], "Duplicate",
        "Same screenshot submitted twice", original=c["id"], reuse=c["id"], rin=True)
for _ in range(8):  # fake-app success screen, no matching credit at all (8)
    name, upi = new_person()
    add("fake_app", name, upi, rng.choice([250, 450, 800, 1000]), rand_ts(), new_ref(), "Not found",
        "Convincing success screen, no matching credit")
for _ in range(5):  # paid to a different account (5)
    name, upi = new_person()
    add("wrong_payee", name, upi, rng.choice([300, 500]), rand_ts(), new_ref(), "Not found",
        "Payment went to a different account", payee="Campus Club Collections", payee_upi="campusclub@examplebank")
for _ in range(4):  # old genuine screenshot reused, outside the period (4)
    name, upi = new_person()
    add("old_screenshot", name, upi, 300, datetime(2026, 9, rng.randint(10, 28), rng.randint(8, 22), 15, 0),
        new_ref(), "Can't verify yet", "Older payment, before the statement period (confirm expected label with Alizah)")

# ---------------------------------------------------------------- render screenshots
fnames = {}
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_context(viewport={"width": 390, "height": 780}, device_scale_factor=2).new_page()
    for i, c in enumerate(claims):
        if c["reuse"]:  # byte-identical copy of an earlier screenshot
            src_name = fnames[c["reuse"]]
            fname = f"{c['id']}{Path(src_name).suffix}"
            shutil.copyfile(SHOTS / src_name, SHOTS / fname)
            fnames[c["id"]] = fname
            continue
        use_jpeg = rng.random() < 0.6
        fname = f"{c['id']}.{'jpg' if use_jpeg else 'png'}"
        decoy = "T" + c["ts"].strftime("%y%m%d%H%M") + "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(4))
        body = Template(VARIANTS[i % 4]).substitute(
            status=rng.choice(STATUSES), amount="&#8377;" + indian(c["amount"]), when=when(c["ts"], rng.randint(0, 2)),
            payee=c["payee"], payee_upi=c["payee_upi"], payer=c["name"], payer_upi=c["upi"],
            ref_label=rng.choice(REF_LABELS), ref=c["ref"], decoy_label=rng.choice(DECOY_LABELS), decoy=decoy)
        page.set_content(f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>")
        if use_jpeg:
            page.screenshot(path=str(SHOTS / fname), type="jpeg", quality=rng.randint(55, 90))
        else:
            page.screenshot(path=str(SHOTS / fname), type="png")
        fnames[c["id"]] = fname
    browser.close()

# ---------------------------------------------------------------- ground truth + metadata
cols = ["claim_id", "file", "category", "payer_name", "payer_upi", "amount", "reference", "timestamp",
        "reference_in_narration", "expected_verdict", "expected_after_recheck", "original_claim", "reason"]
with open(OUT / "ground_truth.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(cols)
    for c in claims:
        w.writerow([c["id"], f"screenshots/{fnames[c['id']]}", c["cat"], c["name"], c["upi"], f"{c['amount']:.2f}",
                    c["ref"], c["ts"].strftime("%Y-%m-%d %H:%M:%S"), c["rin"], c["expected"], c["after"],
                    c["original"], c["reason"]])

with open(OUT / "master_payments.json", "w", encoding="utf-8") as fh:
    json.dump([{**t, "ts": t["ts"].isoformat()} for t in txns + late], fh, indent=2)

with open(OUT / "README.md", "w", encoding="utf-8") as fh:
    fh.write("# Synthetic data (EVALUATION USE ONLY)\n\nAll names, UPI IDs, references and screenshots here are "
             "randomly generated. No real person or account is represented.\n")

from collections import Counter
print(f"{len(txns)} transactions (+{len(late)} late), 6 statements, {len(claims)} screenshots written to {OUT}")
print(dict(Counter(c["cat"] for c in claims)))