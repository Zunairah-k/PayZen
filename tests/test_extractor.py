"""Tests for PayZen Phase 1 extraction + normalization (Alizah).

Run from the repo root:
    python -m pytest tests/test_extractor.py -v
"""
import io
import math
import random
import sys
from datetime import datetime
from pathlib import Path

import pytest

# Make `app` importable when running pytest from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.models import Claim  # noqa: E402
from app.services import extractor as ex  # noqa: E402
from app.services.extractor import (  # noqa: E402
    MockVisionProvider,
    NoProviderConfigured,
    RawExtraction,
    VisionProvider,
    claim_from_raw,
    compute_image_hash,
    extract_claim,
    extract_claim_detailed,
    hamming_distance,
    normalize_amount,
    normalize_currency,
    normalize_name,
    normalize_reference,
    normalize_status,
    normalize_timestamp,
    normalize_upi_id,
)

REQUIRED_CONF_KEYS = [
    "reference", "amount", "timestamp", "payer_name",
    "payer_upi_id", "payee_name", "payee_upi_id", "status_shown",
]


# ---------------------------------------------------------------- helpers

def make_png(seed: int = 1, size=(240, 480)) -> bytes:
    """Deterministic synthetic 'screenshot': gradient + seeded rectangles."""
    from PIL import Image, ImageDraw

    rng = random.Random(seed)
    img = Image.new("RGB", size, (250, 250, 250))
    d = ImageDraw.Draw(img)
    for y in range(size[1]):
        g = int(255 * y / size[1])
        d.line([(0, y), (size[0], y)], fill=(g, 255 - g, 128))
    for _ in range(14):
        x0, y0 = rng.randint(0, size[0] - 40), rng.randint(0, size[1] - 40)
        d.rectangle([x0, y0, x0 + rng.randint(20, 120), y0 + rng.randint(10, 80)],
                    fill=(rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255)))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def notes_text(claim) -> str:
    n = claim.extraction_notes
    return " | ".join(n) if isinstance(n, (list, tuple)) else str(n or "")


def ts_str(claim):
    t = claim.timestamp
    return t.isoformat() if isinstance(t, datetime) else t


FULL_FIELDS = {
    "payer_name": {"value": "  SYEDA   ALIZAH ", "confidence": 0.92},
    "payer_upi_id": {"value": "Alizah@OkSBI", "confidence": 0.9},
    "payee_name": {"value": "College Fest Treasurer", "confidence": 0.88},
    "payee_upi_id": {"value": "treasurer@ybl", "confidence": 0.85},
    "amount": {"value": "₹ 300", "confidence": 0.97},
    "timestamp": {"value": "07 Oct 2026, 10:30 AM", "confidence": 0.9},
    "reference": {"value": "1234 5678 9012", "confidence": 0.95},
    "app_style_guess": {"value": "Google Pay", "confidence": 0.6},
    "status_shown": {"value": "Payment Successful", "confidence": 0.9},
}


def mock_claim(fields=None, image=None, filename="shot.png"):
    return extract_claim_detailed(
        image or make_png(), filename, MockVisionProvider(FULL_FIELDS if fields is None else fields)
    ).claim


# ------------------------------------------------ 1. Claim created correctly

def test_claim_created_correctly():
    c = mock_claim()
    assert isinstance(c, Claim)
    assert c.claim_id
    assert c.source_file == "shot.png"
    assert c.payer_name == "Syeda Alizah"
    assert c.payer_upi_id == "alizah@oksbi"
    assert c.payee_name == "College Fest Treasurer"
    assert c.payee_upi_id == "treasurer@ybl"
    assert c.amount == 300.0
    assert c.reference == "123456789012"
    assert ts_str(c) == "2026-10-07T10:30:00"
    assert c.app_style_guess == "Google Pay"
    assert c.status_shown == "success"


def test_source_file_strips_path():
    assert mock_claim(filename=r"C:\Users\x\Downloads\proof 1.png").source_file == "proof 1.png"


def test_claim_ids_are_unique():
    assert mock_claim().claim_id != mock_claim().claim_id


# ------------------------------------------------------ 2. amount normalization

@pytest.mark.parametrize("raw", [
    "₹300", "₹ 300", "Rs 300", "Rs. 300", "INR 300", "inr300", "300.00", "300",
    "300 INR", "300/-", " ₹300.00 ", 300, 300.0, "Rupees 300",
])
def test_amount_normalizes_to_300(raw):
    assert normalize_amount(raw).value == 300.0


@pytest.mark.parametrize("raw,expected", [
    ("₹1,500", 1500.0), ("₹1,500.50", 1500.5), ("₹1,00,000", 100000.0),
    ("Rs 12,34,567.89", 1234567.89), ("₹ 0.50", 0.5),
])
def test_amount_with_grouping(raw, expected):
    assert normalize_amount(raw).value == expected


@pytest.mark.parametrize("raw", [
    "Paid 300 to 9876543210",      # unmarked number in free text
    "₹300 and ₹500",               # ambiguous
    "₹0", "0", "-300", "abc", "", "   ", "₹3,00", "300.000", "UTR 123456789012",
    None, True, float("nan"), float("inf"), -5,
])
def test_amount_rejects_unreliable_input(raw):
    assert normalize_amount(raw).value is None


def test_amount_marker_picks_marked_number_only():
    assert normalize_amount("Paid ₹300 to Ravi").value == 300.0


# ------------------------------------------------------ 3. currency handling

def test_currency_from_marker():
    assert normalize_amount("₹300").currency == "INR"
    assert normalize_amount("300").currency is None  # bare number: no evidence


@pytest.mark.parametrize("raw", ["INR", "inr", "₹", "Rs", "Rs.", "Rupees"])
def test_currency_provider_values_map_to_inr(raw):
    assert normalize_currency(raw).value == "INR"


def test_currency_conflict_left_unset():
    n = normalize_currency("USD", marker_currency="INR")
    assert n.value is None and n.notes


def test_currency_flows_into_claim_and_not_invented():
    assert mock_claim({"amount": "₹300"}).currency == "INR"
    # bare number, no currency evidence anywhere -> not invented as INR by us
    c = mock_claim({"amount": "300"})
    assert c.currency in (None, "INR")  # "INR" only if models.py defaults it
    assert c.confidence["currency"] == 0.0


# --------------------------------------------------- 4/5. reference normalization

@pytest.mark.parametrize("raw", [
    "123456789012", "1234 5678 9012", "1234-5678-9012", "  1234   5678  9012  ",
    "UPI Ref No: 123456789012", "Ref 1234 5678 9012", "１２３４５６７８９０１２",
])
def test_reference_valid_formats(raw):
    assert normalize_reference(raw).value == "123456789012"


def test_reference_int_input():
    assert normalize_reference(123456789012).value == "123456789012"


def test_reference_reformatting_is_noted_and_slightly_penalized():
    n = normalize_reference("1234 5678 9012")
    assert n.penalty < 1.0 and n.notes
    assert normalize_reference("123456789012").penalty == 1.0


# ------------------------------------------------ 6. invalid/uncertain reference

@pytest.mark.parametrize("raw", [
    "12345678901",            # 11 digits
    "1234567890123",          # 13 digits
    "1234 5678 901",          # incomplete
    "12345678901O",           # letter O in digits: no OCR repair
    "l23456789012",           # letter l: no OCR repair
    "123456789012 987654321098",  # two different candidates
    "000000000000", "111111111111",
    "T2610071030123456789",   # not a 12-digit UPI ref
    "", "   ", "no reference", None, 12.5, True,
    1234567890,               # int with lost leading zeros must not be padded
])
def test_reference_invalid_or_uncertain_is_none(raw):
    assert normalize_reference(raw).value is None


def test_uncertain_reference_gives_none_and_zero_confidence():
    c = mock_claim({"reference": {"value": "12345678901O", "confidence": 0.99}})
    assert c.reference is None
    assert c.confidence["reference"] == 0.0
    assert "reference" in notes_text(c).lower()


# -------------------------------------------------- 7/8. missing amount/reference

def test_missing_amount():
    f = {k: v for k, v in FULL_FIELDS.items() if k != "amount"}
    c = mock_claim(f)
    assert c.amount is None
    assert c.confidence["amount"] == 0.0
    assert "amount" in notes_text(c).lower()


def test_missing_reference():
    f = {k: v for k, v in FULL_FIELDS.items() if k != "reference"}
    c = mock_claim(f)
    assert c.reference is None
    assert c.confidence["reference"] == 0.0
    assert "reference" in notes_text(c).lower()


# ------------------------------------------------------- 9. timestamp normalization

@pytest.mark.parametrize("raw,expected", [
    ("2026-10-07T10:30:00", "2026-10-07T10:30:00"),
    ("2026-10-07 10:30", "2026-10-07T10:30:00"),
    ("07 Oct 2026, 10:30 AM", "2026-10-07T10:30:00"),
    ("7 Oct 2026 at 10:30 pm", "2026-10-07T22:30:00"),
    ("Oct 7, 2026, 10:30 PM", "2026-10-07T22:30:00"),
    ("October 7th 2026 10:30 am", "2026-10-07T10:30:00"),
    ("07/10/2026 22:30:15", "2026-10-07T22:30:15"),
    ("07-10-2026 22:30", "2026-10-07T22:30:00"),
    ("07/10/26 10:30 a.m.", "2026-10-07T10:30:00"),
    ("10:30 AM on 07 Oct 2026", "2026-10-07T10:30:00"),
    ("12:00 AM 07 Oct 2026", "2026-10-07T00:00:00"),
    ("12:15 PM 07 Oct 2026", "2026-10-07T12:15:00"),
    ("2026-10-07T10:30:00.123", "2026-10-07T10:30:00"),
])
def test_timestamp_full_datetime(raw, expected):
    r = normalize_timestamp(raw)
    assert r.iso == expected and r.precision == "datetime"


def test_timestamp_day_first_for_numeric_dates():
    assert normalize_timestamp("03/04/2026 09:00").iso == "2026-04-03T09:00:00"


def test_timestamp_timezone_never_invented_and_ignored_with_note():
    r = normalize_timestamp("2026-10-07T10:30:00+05:30")
    assert r.iso == "2026-10-07T10:30:00"
    assert any("timezone" in n for n in r.notes)
    assert "+" not in r.iso


def test_timestamp_date_only_is_partial_not_padded():
    r = normalize_timestamp("07 Oct 2026")
    assert r.iso is None and r.date == "2026-10-07" and r.time is None and r.precision == "date"
    assert any("partial" in n for n in r.notes)


def test_timestamp_time_only_is_partial_not_padded():
    r = normalize_timestamp("10:30 PM")
    assert r.iso is None and r.date is None and r.time == "22:30:00" and r.precision == "time"


@pytest.mark.parametrize("raw", [
    "", "   ", None, "yesterday", "32/13/2026 10:00", "07 Oct 2026 25:00",
    "13:00 PM 07 Oct 2026", "07 Oct 1850 10:00", "10:30 AM 11:45 PM 07 Oct 2026", True,
])
def test_timestamp_invalid_is_none(raw):
    r = normalize_timestamp(raw)
    assert r.iso is None and r.precision is None


def test_partial_timestamp_in_claim_is_none_but_details_keep_it():
    d = extract_claim_detailed(make_png(), "a.png", MockVisionProvider({"timestamp": "07 Oct 2026"}))
    assert d.claim.timestamp is None
    assert d.claim.confidence["timestamp"] == 0.0
    assert d.partial_date == "2026-10-07"
    assert "partially" in notes_text(d.claim)


# -------------------------------------------------------------- 10. names / UPI

@pytest.mark.parametrize("raw,expected", [
    ("  Syeda   Alizah  ", "Syeda Alizah"),
    ("SYEDA ALIZAH", "Syeda Alizah"),
    ("syeda alizah", "Syeda Alizah"),
    ("Syeda  \u200bAlizah", "Syeda Alizah"),
    ("McDonald Rao", "McDonald Rao"),       # mixed case preserved
    ("O'NEIL", "O'neil"),
])
def test_name_normalization(raw, expected):
    assert normalize_name(raw).value == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "12345", "---", True])
def test_name_rejects_non_names(raw):
    assert normalize_name(raw).value is None


@pytest.mark.parametrize("raw,expected", [
    ("Alizah@OkSBI", "alizah@oksbi"),
    ("  ali zah @ ybl ", "alizah@ybl"),
    ("9876543210@paytm", "9876543210@paytm"),
    ("first.last-1@okhdfcbank", "first.last-1@okhdfcbank"),
])
def test_upi_normalization(raw, expected):
    assert normalize_upi_id(raw).value == expected


@pytest.mark.parametrize("raw", [None, "", "no-at-sign", "@ybl", "a@", "a b@@ybl", "x@1", True])
def test_upi_invalid_is_none(raw):
    assert normalize_upi_id(raw).value is None


def test_masked_upi_is_kept_but_confidence_capped():
    c = mock_claim({"payee_upi_id": {"value": "ab****12@oksbi", "confidence": 0.99}})
    assert c.payee_upi_id == "ab****12@oksbi"
    assert c.confidence["payee_upi_id"] <= ex.MASKED_UPI_CONFIDENCE_CAP


@pytest.mark.parametrize("raw,expected", [
    ("Payment Successful", "success"), ("SUCCESS", "success"), ("Completed", "success"),
    ("Payment Failed", "failed"), ("Unsuccessful", "failed"), ("Declined", "failed"),
    ("Pending", "pending"), ("Processing", "pending"),
])
def test_status_normalization(raw, expected):
    assert normalize_status(raw).value == expected


def test_status_unknown_is_none():
    assert normalize_status("hello").value is None
    assert normalize_status(None).value is None


# ------------------------------------------------------- 11/12. confidence

def test_confidence_keys_exist():
    c = mock_claim()
    for k in REQUIRED_CONF_KEYS:
        assert k in c.confidence, k


def test_confidence_values_in_range_even_with_bad_provider_values():
    raw = RawExtraction.from_dict({
        "amount": {"value": "₹300", "confidence": 7.5},          # too high -> clamp
        "reference": {"value": "123456789012", "confidence": -2},  # too low -> clamp
        "timestamp": {"value": "07 Oct 2026 10:30", "confidence": float("nan")},
        "payer_name": {"value": "Ravi", "confidence": "high"},     # garbage -> 0
        "status_shown": {"value": "success"},                       # unreported
    })
    c = claim_from_raw(raw, filename="a.png", image_hash="x").claim
    for k, v in c.confidence.items():
        assert isinstance(v, float) and 0.0 <= v <= 1.0 and not math.isnan(v), (k, v)
    assert c.confidence["amount"] == 1.0
    assert c.confidence["reference"] == 0.0
    assert c.confidence["timestamp"] == 0.0
    assert c.confidence["payer_name"] == 0.0
    assert c.confidence["status_shown"] == ex.DEFAULT_UNREPORTED_CONFIDENCE


def test_no_confidence_for_fields_not_extracted():
    c = mock_claim({"amount": {"value": "₹300", "confidence": 0.9}})
    assert c.confidence["amount"] > 0
    for k in REQUIRED_CONF_KEYS:
        if k != "amount":
            assert c.confidence[k] == 0.0, k


def test_provider_confidence_is_reflected():
    c = mock_claim({"amount": {"value": "₹300", "confidence": 0.42}})
    assert c.confidence["amount"] == pytest.approx(0.42)
    assert "low extraction confidence" in notes_text(c)


# ------------------------------------------------------------ 13. image hash

def test_image_hash_generated_and_perceptual():
    h, note = compute_image_hash(make_png(1))
    assert h.startswith(ex.DHASH_PREFIX) and len(h) == len(ex.DHASH_PREFIX) + 64
    assert note is None
    assert mock_claim().image_hash.startswith(ex.DHASH_PREFIX)


def test_image_hash_deterministic():
    img = make_png(1)
    assert compute_image_hash(img)[0] == compute_image_hash(img)[0]


def test_image_hash_survives_resize_and_jpeg_more_than_a_different_image():
    from PIL import Image

    base = make_png(1)
    img = Image.open(io.BytesIO(base))
    small = io.BytesIO()
    img.resize((120, 240)).save(small, "PNG")
    jpg = io.BytesIO()
    img.save(jpg, "JPEG", quality=60)

    h0 = compute_image_hash(base)[0]
    d_resize = hamming_distance(h0, compute_image_hash(small.getvalue())[0])
    d_jpeg = hamming_distance(h0, compute_image_hash(jpg.getvalue())[0])
    d_other = hamming_distance(h0, compute_image_hash(make_png(2))[0])
    assert d_resize < d_other and d_jpeg < d_other
    assert d_resize <= 40 and d_jpeg <= 40  # of 256 bits


def test_image_hash_fallback_is_labelled_sha256():
    h, note = compute_image_hash(b"not an image")
    assert h.startswith(ex.SHA256_PREFIX) and not h.startswith(ex.DHASH_PREFIX)
    assert note and "sha256" in note
    assert hamming_distance(h, h) is None  # sha256 is not perceptually comparable


def test_hamming_distance_basics():
    h = compute_image_hash(make_png(1))[0]
    assert hamming_distance(h, h) == 0
    assert hamming_distance(None, h) is None


# ------------------------------------------------- 14. no fabrication

def test_default_provider_extracts_nothing_and_fabricates_nothing():
    assert isinstance(ex.get_default_provider(), NoProviderConfigured)
    c = extract_claim(make_png(), "x.png")
    for f in ("payer_name", "payer_upi_id", "payee_name", "payee_upi_id",
              "amount", "timestamp", "reference", "app_style_guess", "status_shown"):
        assert getattr(c, f) is None, f
    assert all(v == 0.0 for v in c.confidence.values())
    assert "no vision provider" in notes_text(c)
    # the old stub's fake values must be gone
    assert c.reference != "123456789012" and c.payer_name != "Test Payer" and c.amount != 300.0


def test_empty_provider_result_is_all_none():
    c = mock_claim({})
    assert c.amount is None and c.reference is None and c.timestamp is None


def test_unknown_provider_fields_are_ignored():
    raw = RawExtraction.from_dict({"amount": "₹10", "bank_balance": "₹999999", "note": "hi"})
    assert set(raw.fields) == {"amount"}


def test_notes_are_short_and_bounded():
    c = mock_claim({k: "###" for k in ex.RAW_FIELD_NAMES})
    n = c.extraction_notes
    items = n if isinstance(n, list) else [n]
    assert len(items) <= ex.MAX_NOTES
    if isinstance(n, list):
        assert all(len(x) <= ex.MAX_NOTE_LEN for x in n)


def test_provider_failure_is_contained():
    class Boom(VisionProvider):
        name = "boom"

        def extract_fields(self, image_bytes, filename):
            raise RuntimeError("secret internal detail")

    c = extract_claim_detailed(make_png(), "x.png", Boom()).claim
    assert c.amount is None and c.reference is None
    assert "vision provider failed" in notes_text(c)
    assert "secret internal detail" not in notes_text(c)


@pytest.mark.parametrize("bad", [b"", None, "text", 123])
def test_empty_or_non_bytes_input_rejected(bad):
    with pytest.raises(ValueError):
        extract_claim(bad, "x.png")


# ----------------------------------------------------- 15. mock extraction

def test_mock_extraction_produces_valid_claim_and_labels_itself():
    d = extract_claim_detailed(make_png(), "mock.png", MockVisionProvider(FULL_FIELDS))
    assert isinstance(d.claim, Claim)
    assert d.is_mock is True and d.provider_name == "mock"
    assert "MOCK" in notes_text(d.claim)
    assert d.claim.amount == 300.0 and d.claim.reference == "123456789012"


def test_mock_reads_json_fixture_from_bytes():
    payload = b'{"mock_fields": {"amount": "Rs 250", "reference": "9876 5432 1098"}}'
    c = extract_claim_detailed(payload, "demo.json", MockVisionProvider()).claim
    assert c.amount == 250.0 and c.reference == "987654321098"


def test_mock_without_fixture_returns_nothing():
    c = extract_claim_detailed(make_png(), "x.png", MockVisionProvider()).claim
    assert c.amount is None and c.reference is None


def test_set_default_provider_is_used_by_extract_claim():
    old = ex.get_default_provider()
    try:
        ex.set_default_provider(MockVisionProvider({"amount": "₹75"}))
        assert extract_claim(make_png(), "x.png").amount == 75.0
        with pytest.raises(TypeError):
            ex.set_default_provider(object())  # type: ignore[arg-type]
    finally:
        ex.set_default_provider(old)
