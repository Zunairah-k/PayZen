"""PayZen — screenshot -> Claim extraction foundation (Alizah, Phase 1).

Pipeline
--------
    image bytes
        -> VisionProvider.extract_fields()   (pluggable; returns RAW strings + confidence)
        -> normalizers                       (deterministic, conservative)
        -> Claim                             (shared contract from app.models)

Design rules
------------
* Nothing is invented. If a value cannot be established it stays ``None`` and
  its confidence is ``0.0``.
* Normalizers are pure, deterministic functions. They never guess: ambiguous
  input is rejected rather than "fixed" (e.g. no O->0 or l->1 OCR repairs).
* Real AI/vision is only the *source of raw text*. Everything after that is
  plain code, so it can be unit-tested.
* No real vision provider is wired in yet. The default provider extracts
  NOTHING (honest empty result). ``MockVisionProvider`` exists for tests/demos
  and labels itself as a mock in ``Claim.extraction_notes``.

Image hash
----------
``Claim.image_hash`` is a *perceptual* difference hash ("dhash256:<64 hex>")
when Pillow can decode the image. If it cannot, it falls back to an exact-bytes
``sha256:<hex>`` and a note says so. A dhash is a weak signal for
screenshots from the same app (they share a template) — see PHASE1_README.md.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import os
import re
import unicodedata
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from ..models import Claim

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

#: Fields the provider may return. Anything else is ignored.
RAW_FIELD_NAMES: Tuple[str, ...] = (
    "payer_name",
    "payer_upi_id",
    "payee_name",
    "payee_upi_id",
    "amount",
    "currency",
    "timestamp",
    "reference",
    "app_style_guess",
    "status_shown",
)

#: Keys always present in ``Claim.confidence``.
CONFIDENCE_KEYS: Tuple[str, ...] = (
    "reference",
    "amount",
    "currency",
    "timestamp",
    "payer_name",
    "payer_upi_id",
    "payee_name",
    "payee_upi_id",
    "status_shown",
    "app_style_guess",
)

#: Used when a provider returns a value but no confidence for it.
#: Deliberately middling: "extracted, but we don't know how sure it was".
DEFAULT_UNREPORTED_CONFIDENCE = 0.5

#: Confidence ceiling for masked UPI IDs (e.g. "ab****12@oksbi").
MASKED_UPI_CONFIDENCE_CAP = 0.5

MAX_NOTES = 12
MAX_NOTE_LEN = 160

DHASH_SIZE = 16  # 16x16 => 256-bit hash
DHASH_PREFIX = "dhash256:"
SHA256_PREFIX = "sha256:"


# --------------------------------------------------------------------------
# Provider abstraction
# --------------------------------------------------------------------------

@dataclass
class RawField:
    """One field as returned by a vision provider (before normalization)."""

    value: Any = None
    confidence: Optional[float] = None  # provider's own 0..1 confidence, if any


@dataclass
class RawExtraction:
    """Structured output a VisionProvider must return."""

    fields: Dict[str, RawField] = field(default_factory=dict)
    provider_name: str = "unknown"
    is_mock: bool = False
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        provider_name: str = "unknown",
        is_mock: bool = False,
        notes: Optional[List[str]] = None,
    ) -> "RawExtraction":
        """Build from ``{"amount": "₹300"}`` or ``{"amount": {"value": "₹300", "confidence": 0.9}}``."""
        fields: Dict[str, RawField] = {}
        for name, item in (data or {}).items():
            if name not in RAW_FIELD_NAMES:
                continue
            if isinstance(item, dict) and "value" in item:
                fields[name] = RawField(item.get("value"), item.get("confidence"))
            else:
                fields[name] = RawField(item, None)
        return cls(fields=fields, provider_name=provider_name, is_mock=is_mock, notes=list(notes or []))


class VisionProvider(ABC):
    """Interface a real vision model must implement to plug into PayZen.

    ``extract_fields`` should return the text exactly as read from the
    screenshot (strings like "₹ 1,500.00" or "1234 5678 9012"). Normalization
    is done by this module, not by the provider. Fields that are not visible
    must be omitted or ``None`` — never guessed.
    """

    name: str = "unnamed-provider"
    is_mock: bool = False

    @abstractmethod
    def extract_fields(self, image_bytes: bytes, filename: str) -> RawExtraction:
        raise NotImplementedError


class NoProviderConfigured(VisionProvider):
    """Default provider while no real vision model is plugged in.

    Returns NO fields. This is intentional: PayZen must not fabricate payment
    data when real extraction is unavailable.
    """

    name = "none-configured"
    is_mock = False

    def extract_fields(self, image_bytes: bytes, filename: str) -> RawExtraction:
        return RawExtraction(
            fields={},
            provider_name=self.name,
            is_mock=False,
            notes=["no vision provider configured; no fields were extracted"],
        )


class MockVisionProvider(VisionProvider):
    """TEST/DEMO ONLY. This is NOT AI extraction.

    Returns fixture values you hand it. If no fixture is given, it tries to
    read ``{"mock_fields": {...}}`` JSON out of the uploaded bytes, which lets
    you demo the pipeline by uploading a small .json file instead of an image.
    Otherwise it returns nothing.
    """

    name = "mock"
    is_mock = True

    def __init__(self, fields: Optional[Dict[str, Any]] = None):
        self._fields = fields

    def extract_fields(self, image_bytes: bytes, filename: str) -> RawExtraction:
        data = self._fields
        if data is None:
            data = _try_load_mock_fields(image_bytes)
        return RawExtraction.from_dict(
            data or {},
            provider_name=self.name,
            is_mock=True,
            notes=["MOCK provider used; values are test fixtures, not real extraction"],
        )


def _try_load_mock_fields(image_bytes: bytes) -> Optional[Dict[str, Any]]:
    try:
        parsed = json.loads(image_bytes.decode("utf-8"))
    except Exception:
        return None
    if isinstance(parsed, dict) and isinstance(parsed.get("mock_fields"), dict):
        return parsed["mock_fields"]
    return None


_default_provider: VisionProvider = NoProviderConfigured()


def set_default_provider(provider: VisionProvider) -> None:
    """Plug in a provider for all later ``extract_claim`` calls."""
    global _default_provider
    if not isinstance(provider, VisionProvider):
        raise TypeError("provider must subclass VisionProvider")
    _default_provider = provider


def get_default_provider() -> VisionProvider:
    return _default_provider


# --------------------------------------------------------------------------
# Normalizers (pure functions)
# --------------------------------------------------------------------------

@dataclass
class Norm:
    """Result of normalizing one field."""

    value: Any = None
    notes: List[str] = field(default_factory=list)
    penalty: float = 1.0       # multiplier applied to provider confidence
    masked: bool = False       # UPI IDs only
    currency: Optional[str] = None  # amounts only: currency evidenced by a marker


def _clean_text(raw: Any) -> str:
    """NFKC-normalize, drop control/zero-width chars, collapse whitespace."""
    s = unicodedata.normalize("NFKC", str(raw))
    s = "".join(
        ch for ch in s
        if ch in "\t\n " or (unicodedata.category(ch) not in ("Cc", "Cf"))
    )
    return re.sub(r"\s+", " ", s).strip()


# ---- reference -----------------------------------------------------------

_REF_STANDALONE = re.compile(r"(?<!\d)\d{12}(?!\d)")
_REF_GROUPED = re.compile(r"(?<!\d)\d{4}[ \-]\d{4}[ \-]\d{4}(?!\d)")


def normalize_reference(raw: Any) -> Norm:
    """Return a 12-digit reference string, or ``value=None`` if not certain.

    Accepts "123456789012", "1234 5678 9012", "1234-5678-9012" and a 12-digit
    number embedded in a label ("UPI Ref No: 123456789012"). Rejects: wrong
    length, several different candidates, OCR letters in digits (no repair
    attempted), and implausible all-same-digit values.
    """
    if raw is None or isinstance(raw, (bool, float)):
        return Norm()
    s = _clean_text(raw)
    if not s:
        return Norm()

    candidates = {m.group(0) for m in _REF_STANDALONE.finditer(s)}
    grouped = {re.sub(r"\D", "", m.group(0)) for m in _REF_GROUPED.finditer(s)}
    reformatted = bool(grouped - candidates)
    candidates |= grouped

    if len(candidates) > 1:
        return Norm(notes=["reference ambiguous (several 12-digit candidates); discarded"])
    if not candidates:
        return Norm(notes=["reference could not be confidently extracted (no valid 12-digit value)"])

    ref = next(iter(candidates))
    if len(set(ref)) == 1:
        return Norm(notes=["reference rejected (implausible repeated digit)"])
    if reformatted:
        return Norm(ref, ["reference normalized (spaces/hyphens removed)"], penalty=0.95)
    return Norm(ref)


# ---- amount / currency ---------------------------------------------------

# Western (1,234,567) or Indian (12,34,567) digit grouping, optional paise.
_NUM = r"(?:\d{1,2}(?:,\d{2})*,\d{3}|\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?"
_AMT_PURE = re.compile(rf"^({_NUM})$")
_AMT_PREFIX = re.compile(
    rf"(?:₹|(?<![a-z])rs\.?|(?<![a-z])inr|(?<![a-z])rupees?)\s*({_NUM})(?!\d|,\d|\.\d)",
    re.IGNORECASE,
)
_AMT_SUFFIX = re.compile(
    rf"(?<![\d.,])({_NUM})(?!\d|,\d)\s*(?:/-|(?:rs|inr|rupees?)(?![a-z]))",
    re.IGNORECASE,
)


def normalize_amount(raw: Any) -> Norm:
    """Return a positive float rounded to 2 decimals, or ``value=None``.

    A bare number is accepted (the provider already labelled it "amount").
    Text with a currency marker (₹, Rs, INR, rupees) yields the number tied to
    that marker. Free text with unmarked numbers ("Paid 300 to 9876...") is
    rejected, as are several different marked amounts.
    """
    if raw is None or isinstance(raw, bool):
        return Norm()
    if isinstance(raw, (int, float)):
        v = float(raw)
        if not math.isfinite(v) or v <= 0:
            return Norm(notes=["amount rejected (non-positive or not finite)"])
        return Norm(round(v, 2))

    s = _clean_text(raw)
    if not s:
        return Norm()

    marked = [m.group(1) for m in _AMT_PREFIX.finditer(s)] + [m.group(1) for m in _AMT_SUFFIX.finditer(s)]
    currency = None
    if marked:
        distinct = {float(x.replace(",", "")) for x in marked}
        if len(distinct) > 1:
            return Norm(notes=["amount ambiguous (several different amounts); discarded"])
        value = distinct.pop()
        currency = "INR"
        penalty = 1.0 if _AMT_PURE.match(re.sub(r"(?i)^(₹|rs\.?|inr)\s*", "", s)) else 0.9
    else:
        m = _AMT_PURE.match(s)
        if not m:
            return Norm(notes=["amount could not be confidently extracted"])
        value = float(m.group(1).replace(",", ""))
        penalty = 1.0

    if value <= 0:
        return Norm(notes=["amount rejected (non-positive)"])
    return Norm(round(value, 2), currency=currency, penalty=penalty)


def normalize_currency(raw: Any, marker_currency: Optional[str] = None) -> Norm:
    """Currency code from the provider and/or an amount marker.

    Returns "INR" only when something evidences it. If the two sources
    disagree the currency is left ``None``.
    """
    provided = None
    if raw is not None and not isinstance(raw, bool):
        s = _clean_text(raw)
        if s:
            up = s.upper().rstrip(".")
            if s == "₹" or up in ("RS", "INR", "RUPEE", "RUPEES"):
                provided = "INR"
            elif re.fullmatch(r"[A-Z]{3}", up):
                provided = up
    if provided and marker_currency and provided != marker_currency:
        return Norm(notes=["currency conflict between amount marker and provider; left unset"])
    value = provided or marker_currency
    if value and value != "INR":
        return Norm(value, [f"non-INR currency detected ({value})"])
    return Norm(value)


# ---- timestamp -----------------------------------------------------------

_DATE_FORMATS = (
    "%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y",
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%Y/%m/%d",
    "%d/%m/%y", "%d-%m-%y", "%d %b %y",
)
_TIME_RE = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?\s*(AM|PM)?(?![\d:])", re.IGNORECASE)


_TZ_AFTER_TIME = re.compile(r"\s*(?:Z\b|[+-]\d{2}:?\d{2}\b|(?:IST|UTC|GMT)\b)", re.IGNORECASE)


@dataclass
class TimestampResult:
    iso: Optional[str] = None        # full "YYYY-MM-DDTHH:MM:SS" only
    date: Optional[str] = None       # "YYYY-MM-DD" if a date was read
    time: Optional[str] = None       # "HH:MM:SS" if a time was read
    precision: Optional[str] = None  # "datetime" | "date" | "time" | None
    notes: List[str] = field(default_factory=list)


def normalize_timestamp(raw: Any) -> TimestampResult:
    """Parse a screenshot date/time. Day-first is assumed for numeric dates
    (Indian convention): "03/04/2026" is 3 April. Timezones are never
    invented; an explicit offset/"IST" is ignored with a note. Date-only or
    time-only input is reported as partial and never padded."""
    if raw is None or isinstance(raw, bool):
        return TimestampResult()
    if isinstance(raw, datetime):
        iso = raw.replace(microsecond=0).isoformat()
        return TimestampResult(iso=iso, date=iso[:10], time=iso[11:19], precision="datetime")

    s = _clean_text(raw)
    if not s:
        return TimestampResult()
    notes: List[str] = []

    s = re.sub(r"(?i)\b([ap])\.\s?m\b\.?", lambda m: m.group(1).upper() + "M", s)
    s = re.sub(r"(?<=\d)T(?=\d)", " ", s)
    s = re.sub(r"(?i)\bSept\b", "Sep", s)
    s = re.sub(r"(?i)(?<=\d)(st|nd|rd|th)\b", "", s)

    tm = _TIME_RE.search(s)
    hh = mm = ss = None
    if tm:
        h, m_, sec, ampm = int(tm.group(1)), int(tm.group(2)), int(tm.group(3) or 0), tm.group(4)
        ok = m_ < 60 and sec < 60
        if ampm:
            ok = ok and 1 <= h <= 12
            h = (h % 12) + (12 if ampm.upper() == "PM" else 0)
        else:
            ok = ok and h < 24
        if not ok:
            return TimestampResult(notes=["timestamp rejected (invalid time)"])
        hh, mm, ss = h, m_, sec
        tail = s[tm.end():]
        # An offset/zone is only recognised when it directly follows the time,
        # so a date like "07-10-2026" is never mistaken for "-2026".
        tz = _TZ_AFTER_TIME.match(tail)
        if tz:
            tail = tail[tz.end():]
            notes.append("timezone designator ignored (no timezone assumed)")
        s = s[: tm.start()] + " " + tail

    rest = s
    rest = re.sub(r"(?i)\b(at|on)\b", " ", rest)
    rest = re.sub(r"[,]", " ", rest)
    rest = re.sub(r"\s+", " ", rest).strip(" -/.")

    if _TIME_RE.search(rest):
        return TimestampResult(notes=["timestamp ambiguous (several times); discarded"])

    date_iso: Optional[str] = None
    if rest:
        for fmt in _DATE_FORMATS:
            try:
                d = datetime.strptime(rest, fmt)
            except ValueError:
                continue
            if 2000 <= d.year <= 2100:
                date_iso = d.strftime("%Y-%m-%d")
            break
        if date_iso is None:
            return TimestampResult(notes=["timestamp could not be confidently extracted"])

    time_iso = f"{hh:02d}:{mm:02d}:{ss:02d}" if hh is not None else None

    if date_iso and time_iso:
        return TimestampResult(f"{date_iso}T{time_iso}", date_iso, time_iso, "datetime", notes)
    if date_iso:
        notes.append(f"timestamp partially extracted (date only: {date_iso})")
        return TimestampResult(None, date_iso, None, "date", notes)
    if time_iso:
        notes.append(f"timestamp partially extracted (time only: {time_iso})")
        return TimestampResult(None, None, time_iso, "time", notes)
    return TimestampResult()


# ---- names / UPI IDs -----------------------------------------------------

def normalize_name(raw: Any) -> Norm:
    """Collapse whitespace; fix ALL-CAPS / all-lower casing; keep mixed case."""
    if raw is None or isinstance(raw, bool):
        return Norm()
    s = _clean_text(raw)
    if not s or not re.search(r"[^\W\d_]", s):  # needs at least one letter
        return Norm()
    out = s
    if s.isupper() or s.islower():
        out = " ".join(w[:1].upper() + w[1:].lower() for w in s.split(" "))
    notes = ["name casing/whitespace normalized"] if out != str(raw) else []
    return Norm(out, notes)


_UPI_RE = re.compile(r"^[a-z0-9][a-z0-9.\-_*•]{1,255}@[a-z][a-z0-9]{1,63}$")


def normalize_upi_id(raw: Any) -> Norm:
    """Lower-case, strip stray spaces, validate ``local@handle`` shape.

    Masked IDs ("ab****12@oksbi") are kept but flagged ``masked=True`` so the
    confidence is capped — they cannot be compared for exact equality later.
    """
    if raw is None or isinstance(raw, bool):
        return Norm()
    s = re.sub(r"\s+", "", _clean_text(raw)).lower()
    if not s:
        return Norm()
    if not _UPI_RE.match(s):
        return Norm(notes=["UPI ID rejected (invalid format)"])
    masked = "*" in s or "•" in s
    notes = ["UPI ID is masked in screenshot"] if masked else []
    return Norm(s, notes, masked=masked)


# ---- status / app --------------------------------------------------------

def normalize_status(raw: Any) -> Norm:
    """Map screenshot status text to ``success`` / ``failed`` / ``pending``."""
    if raw is None or isinstance(raw, bool):
        return Norm()
    s = _clean_text(raw).lower()
    if not s:
        return Norm()
    # Order matters: "unsuccessful" contains "successful".
    if re.search(r"fail|declin|unsuccess|not success|rejected|cancel|reversed", s):
        return Norm("failed")
    if re.search(r"pend|process|in progress|initiated|awaiting", s):
        return Norm("pending")
    if re.search(r"success|complet|paid|sent|done", s):
        return Norm("success")
    return Norm(notes=["status text not recognized"])


_APPS = (
    ("PhonePe", ("phonepe", "phone pe")),
    ("Google Pay", ("google pay", "gpay", "g pay", "tez")),
    ("Paytm", ("paytm",)),
    ("BHIM", ("bhim",)),
    ("Amazon Pay", ("amazon pay", "amazonpay")),
    ("CRED", ("cred",)),
)


def normalize_app_style(raw: Any) -> Norm:
    """Canonical app name if recognized, else ``None``. It is only a guess."""
    if raw is None or isinstance(raw, bool):
        return Norm()
    s = _clean_text(raw).lower()
    if not s:
        return Norm()
    for canon, keys in _APPS:
        if any(k == s or (len(k) > 4 and k in s) for k in keys):
            return Norm(canon)
    return Norm(notes=["app style not recognized"])


# --------------------------------------------------------------------------
# Image hashing
# --------------------------------------------------------------------------

def sha256_hex(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()


def compute_image_hash(image_bytes: bytes) -> Tuple[str, Optional[str]]:
    """Return ``(hash, note)``.

    Preferred: perceptual dHash ("dhash256:<64 hex>") computed on a
    grayscale 17x16 resize — stable under resizing / mild recompression.
    Fallback (Pillow missing or image undecodable): "sha256:<hex>" which only
    matches byte-identical files; ``note`` then explains this.
    """
    try:
        from PIL import Image  # lazy: Pillow is optional at import time

        resample = getattr(Image, "Resampling", Image).LANCZOS
        with Image.open(io.BytesIO(image_bytes)) as img:
            gray = img.convert("L").resize((DHASH_SIZE + 1, DHASH_SIZE), resample)
        px = gray.tobytes()
        bits = 0
        for row in range(DHASH_SIZE):
            base = row * (DHASH_SIZE + 1)
            for col in range(DHASH_SIZE):
                bits = (bits << 1) | (1 if px[base + col] > px[base + col + 1] else 0)
        return f"{DHASH_PREFIX}{bits:0{DHASH_SIZE * DHASH_SIZE // 4}x}", None
    except Exception as exc:  # ImportError, UnidentifiedImageError, bomb, ...
        logger.info("perceptual hash unavailable (%s); using sha256", type(exc).__name__)
        return (
            f"{SHA256_PREFIX}{sha256_hex(image_bytes)}",
            "image not decodable as an image; exact-bytes sha256 used instead of perceptual hash",
        )


def hamming_distance(hash_a: Optional[str], hash_b: Optional[str]) -> Optional[int]:
    """Bit distance between two dhash256 values; ``None`` if not comparable.

    Helper only. Deciding what distance means is a Phase 2 concern.
    """
    if not hash_a or not hash_b:
        return None
    if not (hash_a.startswith(DHASH_PREFIX) and hash_b.startswith(DHASH_PREFIX)):
        return None
    try:
        return bin(int(hash_a[len(DHASH_PREFIX):], 16) ^ int(hash_b[len(DHASH_PREFIX):], 16)).count("1")
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Raw -> Claim
# --------------------------------------------------------------------------

@dataclass
class ExtractionDetails:
    """Claim plus information that does not fit in the shared Claim contract."""

    claim: Claim
    partial_date: Optional[str] = None   # "YYYY-MM-DD" when only a date was read
    partial_time: Optional[str] = None   # "HH:MM:SS" when only a time was read
    provider_name: str = "unknown"
    is_mock: bool = False


def _confidence(raw_field: Optional[RawField], present: bool, penalty: float = 1.0, cap: float = 1.0) -> float:
    if not present:
        return 0.0
    c = raw_field.confidence if raw_field is not None else None
    if c is None:
        c = DEFAULT_UNREPORTED_CONFIDENCE
    else:
        try:
            c = float(c)
        except (TypeError, ValueError):
            return 0.0
        if math.isnan(c):
            return 0.0
        c = min(1.0, max(0.0, c))
    return round(min(c * penalty, cap), 4)


def _short(note: str) -> str:
    return note if len(note) <= MAX_NOTE_LEN else note[: MAX_NOTE_LEN - 1] + "…"


def _safe_source_name(filename: Any) -> str:
    name = os.path.basename(str(filename or "").replace("\\", "/")).strip()
    return name or "unknown"


def _build_claim(kwargs: Dict[str, Any], notes: List[str]) -> Claim:
    """Construct Claim, adapting to the exact types in models.py.

    models.py is a shared contract that this module does not edit, so we try
    the likely shapes in order: notes as list vs. string, None-valued fields
    passed vs. omitted (for fields that have defaults).
    """
    attempts = []
    for drop_none in (False, True):
        for notes_value in (list(notes), "; ".join(notes)):
            attempts.append((drop_none, notes_value))
    last_error: Optional[ValidationError] = None
    for drop_none, notes_value in attempts:
        data = dict(kwargs, extraction_notes=notes_value)
        if drop_none:
            data = {k: v for k, v in data.items() if v is not None}
        try:
            return Claim(**data)
        except ValidationError as exc:
            last_error = exc
    raise last_error  # type: ignore[misc]


def claim_from_raw(
    raw: RawExtraction,
    *,
    filename: str,
    image_hash: Optional[str],
    extra_notes: Optional[List[str]] = None,
) -> ExtractionDetails:
    """Normalize a provider's RawExtraction into a Claim (no I/O, deterministic
    apart from the random ``claim_id``)."""
    notes: List[str] = list(raw.notes) + list(extra_notes or [])
    rf = raw.fields
    got_any = any(f is not None and f.value not in (None, "") for f in rf.values())

    def raw_of(name: str) -> Optional[RawField]:
        return rf.get(name)

    def value_of(name: str) -> Any:
        f = rf.get(name)
        return None if f is None else f.value

    def supplied(name: str) -> bool:
        v = value_of(name)
        return v is not None and not (isinstance(v, str) and not v.strip())

    conf: Dict[str, float] = {k: 0.0 for k in CONFIDENCE_KEYS}

    # reference
    ref = normalize_reference(value_of("reference"))
    conf["reference"] = _confidence(raw_of("reference"), ref.value is not None, ref.penalty)
    notes += ref.notes

    # amount + currency
    amt = normalize_amount(value_of("amount"))
    conf["amount"] = _confidence(raw_of("amount"), amt.value is not None, amt.penalty)
    notes += amt.notes
    cur = normalize_currency(value_of("currency"), amt.currency)
    if cur.value is not None:
        # Currency is only as trustworthy as the amount it came with / the provider said.
        src = raw_of("currency") if supplied("currency") else raw_of("amount")
        conf["currency"] = _confidence(src, True)
    notes += cur.notes

    # timestamp
    ts = normalize_timestamp(value_of("timestamp"))
    conf["timestamp"] = _confidence(raw_of("timestamp"), ts.iso is not None)
    notes += ts.notes

    # names / UPI IDs
    payer_name = normalize_name(value_of("payer_name"))
    payee_name = normalize_name(value_of("payee_name"))
    payer_upi = normalize_upi_id(value_of("payer_upi_id"))
    payee_upi = normalize_upi_id(value_of("payee_upi_id"))
    for key, n in (("payer_name", payer_name), ("payee_name", payee_name)):
        conf[key] = _confidence(raw_of(key), n.value is not None)
        notes += [f"{key}: {x}" for x in n.notes]
    for key, n in (("payer_upi_id", payer_upi), ("payee_upi_id", payee_upi)):
        cap = MASKED_UPI_CONFIDENCE_CAP if n.masked else 1.0
        conf[key] = _confidence(raw_of(key), n.value is not None, cap=cap)
        notes += [f"{key}: {x}" for x in n.notes]

    # status / app
    status = normalize_status(value_of("status_shown"))
    conf["status_shown"] = _confidence(raw_of("status_shown"), status.value is not None)
    notes += status.notes
    app = normalize_app_style(value_of("app_style_guess"))
    conf["app_style_guess"] = _confidence(raw_of("app_style_guess"), app.value is not None)
    notes += app.notes

    # Only report "missing" for key fields when the provider actually read something.
    if got_any:
        if ref.value is None and not supplied("reference"):
            notes.append("reference not found in screenshot")
        if amt.value is None and not supplied("amount"):
            notes.append("amount not found in screenshot")
        if ts.precision is None and not supplied("timestamp"):
            notes.append("timestamp not found in screenshot")
        low = [k for k in ("reference", "amount", "timestamp") if 0.0 < conf[k] < 0.5]
        if low:
            notes.append("low extraction confidence: " + ", ".join(low))

    # De-duplicate, shorten, cap.
    seen, final_notes = set(), []
    for n in notes:
        n = _short(n)
        if n not in seen:
            seen.add(n)
            final_notes.append(n)
    if len(final_notes) > MAX_NOTES:
        final_notes = final_notes[: MAX_NOTES - 1] + [f"... {len(final_notes) - MAX_NOTES + 1} more notes omitted"]

    kwargs: Dict[str, Any] = dict(
        claim_id=f"claim_{uuid.uuid4().hex[:12]}",
        source_file=_safe_source_name(filename),
        image_hash=image_hash,
        payer_name=payer_name.value,
        payer_upi_id=payer_upi.value,
        payee_name=payee_name.value,
        payee_upi_id=payee_upi.value,
        amount=amt.value,
        currency=cur.value,
        timestamp=ts.iso,
        reference=ref.value,
        app_style_guess=app.value,
        status_shown=status.value,
        confidence=conf,
    )
    claim = _build_claim(kwargs, final_notes)
    return ExtractionDetails(
        claim=claim,
        partial_date=ts.date if ts.precision == "date" else None,
        partial_time=ts.time if ts.precision == "time" else None,
        provider_name=raw.provider_name,
        is_mock=raw.is_mock,
    )


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def extract_claim_detailed(
    image_bytes: bytes,
    filename: str,
    provider: Optional[VisionProvider] = None,
) -> ExtractionDetails:
    """Full pipeline; also returns partial date/time that Claim cannot hold."""
    if not isinstance(image_bytes, (bytes, bytearray)) or len(image_bytes) == 0:
        raise ValueError("image_bytes must be non-empty bytes")
    image_bytes = bytes(image_bytes)

    image_hash, hash_note = compute_image_hash(image_bytes)
    extra = [hash_note] if hash_note else []

    prov = provider or _default_provider
    try:
        raw = prov.extract_fields(image_bytes, filename)
    except Exception as exc:
        logger.exception("vision provider %r failed", getattr(prov, "name", prov))
        raw = RawExtraction(
            provider_name=getattr(prov, "name", "unknown"),
            is_mock=bool(getattr(prov, "is_mock", False)),
            notes=[f"vision provider failed ({type(exc).__name__}); no fields extracted"],
        )
    return claim_from_raw(raw, filename=filename, image_hash=image_hash, extra_notes=extra)


def extract_claim(image_bytes: bytes, filename: str) -> Claim:
    """Screenshot -> Claim. Signature unchanged from the scaffold.

    Uses the default provider (see ``set_default_provider``). With no provider
    configured this returns a Claim with all payment fields ``None``.
    """
    return extract_claim_detailed(image_bytes, filename).claim
