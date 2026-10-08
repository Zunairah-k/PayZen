"""PayZen — user-facing reply generator (Alizah, Phase 3).

    generate_reply(verdict, tone="professional", language="en") -> str
    attach_replies(verdicts, tone=..., language=..., overwrite=False) -> List[Verdict]

Replies are built ONLY from fields already on the Verdict (status, tier,
matched_row_id, confidence, reasons, field_differences, follow_up_after).
Nothing is invented. Output is deterministic: no clocks, no locale, no
randomness. The matcher is not touched; this module only reads Verdicts.

Language support: all sentence fragments live in ``_CATALOGS[lang]``. Adding
Hindi/Telugu later means adding one more catalog with the same keys.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

DEFAULT_LANGUAGE = "en"
DEFAULT_TONE = "professional"
SUPPORTED_TONES = ("professional", "friendly", "brief")

MAX_VALUE_LEN = 80  # user-supplied values echoed in a reply are truncated

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_EN: Dict[str, Any] = {
    "base": {
        "Verified": "The payment appears to be verified. The reference and amount match a transaction in the provided statement.",
        "Likely match": "The payment is likely to match a statement transaction based on the amount, timing and available supporting details.",
        "Contradicted": "We found a transaction with the same reference, but some payment details differ from the submitted claim.",
        "Not found": "We could not find a matching transaction within the available statement coverage.",
        "Duplicate": "This payment appears to duplicate another submitted payment claim.",
        "Can't verify yet": "This payment cannot be verified from the current statement coverage.",
    },
    "unknown_status": "We could not determine the verification result for this payment. Please review the evidence manually.",
    "greeting": "Thanks for sharing your payment details.",
    "matched_entry": "Matched statement entry: {row_id}.",
    "strength": "Evidence strength: {level}.",
    "levels": {"high": "high", "medium": "medium", "low": "low"},
    "tier2_note": "The payer name or UPI ID is also consistent with the statement.",
    "tier3_note": "The payer identity and payment reference could not be confirmed, so please treat this as a possible match only.",
    "likely_next": "Please confirm the transaction reference in your UPI/bank app to be sure.",
    "diff_intro": "Differences found:",
    "diff_item": "{label} (submitted: {claim}; statement: {statement})",
    "diff_item_raw": "{label}: {raw}",
    "labels": {
        "amount": "amount", "payer_name": "payer name", "timestamp": "transaction time",
        "status_shown": "payment status shown", "direction": "transaction direction",
        "reference": "reference", "payer_upi_id": "payer UPI ID",
    },
    "contradicted_next": "Please recheck your UPI/bank app and share the correct transaction details.",
    "not_found_next": "Please recheck your UPI/bank app and share the transaction details (reference number, amount and time).",
    "not_found_taken": "The only matching statement credit was already used for another claim.",
    "duplicate_names": "The same reference was submitted with different payer names, so it cannot be attributed to a single payer automatically.",
    "duplicate_primary": "Another submitted claim with the same payment evidence is being treated as the primary submission.",
    "duplicate_next": "Please confirm whether this payment was submitted more than once.",
    "cvy_followup": "Please provide a statement that covers at least {date}.",
    "cvy_newer": "Please provide a newer statement.",
    "cvy_earlier": "Please provide an earlier statement.",
    "cvy_amount": "Please share the payment amount.",
    "cvy_time": "Please share the payment date and time.",
    "cvy_currency": "Only INR payments can be checked against this statement.",
    "cvy_parse": "The statement could not be read reliably; please upload a clearer or different export.",
    "cvy_empty": "The statement appears to contain no readable transactions; please check the file.",
    "cvy_coverage": "The statement's coverage dates could not be determined; please check the statement file.",
    "tone_prefix": {"professional": "", "friendly": "", "brief": ""},
}

_CATALOGS: Dict[str, Dict[str, Any]] = {"en": _EN}


# ---------------------------------------------------------------- helpers

def _get(obj: Any, name: str, default: Any = None) -> Any:
    return getattr(obj, name, default)


def _clean(value: Any, limit: int = MAX_VALUE_LEN) -> str:
    """Make a user-supplied value safe to echo: no control chars/newlines, bounded length."""
    s = unicodedata.normalize("NFKC", str(value))
    s = "".join(ch for ch in s if unicodedata.category(ch) not in ("Cc", "Cf") or ch.isspace())
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _as_dt(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    if isinstance(v, str) and v.strip():
        try:
            return datetime.fromisoformat(v.strip().replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None
    return None


def _fmt_dt(d: datetime) -> str:
    return f"{d.day:02d} {_MONTHS[d.month - 1]} {d.year} {d.hour:02d}:{d.minute:02d}"


def _reasons(verdict: Any) -> List[str]:
    r = _get(verdict, "reasons")
    if r is None:
        return []
    if isinstance(r, str):
        return [r]
    try:
        return [str(x) for x in r]
    except TypeError:
        return []


def _has(reasons: Iterable[str], needle: str) -> bool:
    n = needle.lower()
    return any(n in r.lower() for r in reasons)


def _level(conf: Any) -> Optional[str]:
    try:
        c = float(conf)
    except (TypeError, ValueError):
        return None
    if c != c or not 0.0 <= c <= 1.0:
        return None
    return "high" if c >= 0.85 else "medium" if c >= 0.60 else "low"


_DIFF_RE = re.compile(r"^claim=(.*), statement=(.*)$", re.DOTALL)


def _diff_sentences(diffs: Any, cat: Dict[str, Any]) -> List[str]:
    if not diffs:
        return []
    try:
        items = sorted(dict(diffs).items(), key=lambda kv: str(kv[0]))
    except (TypeError, ValueError):
        return []
    parts = []
    for key, raw in items:
        label = cat["labels"].get(str(key), _clean(key).replace("_", " "))
        m = _DIFF_RE.match(str(raw))
        if m:
            parts.append(cat["diff_item"].format(label=label, claim=_clean(m.group(1)), statement=_clean(m.group(2))))
        else:
            parts.append(cat["diff_item_raw"].format(label=label, raw=_clean(raw)))
    return [cat["diff_intro"] + " " + "; ".join(parts) + "."] if parts else []


# ---------------------------------------------------------------- public API

def generate_reply(verdict: Any, tone: str = DEFAULT_TONE, language: str = DEFAULT_LANGUAGE) -> str:
    """Build a polite, evidence-based, non-accusatory reply for one Verdict.

    tone: "professional" (default) | "friendly" (adds a thank-you line) | "brief" (headline sentence only).
    language: "en" only for now; other values raise ValueError (no silent fallback).
    """
    if language not in _CATALOGS:
        raise ValueError(f"Unsupported language {language!r}; supported: {sorted(_CATALOGS)}")
    if tone not in SUPPORTED_TONES:
        raise ValueError(f"Unsupported tone {tone!r}; supported: {list(SUPPORTED_TONES)}")
    cat = _CATALOGS[language]

    status = _get(verdict, "status")
    base = cat["base"].get(str(status))
    if base is None:
        return cat["unknown_status"]
    if tone == "brief":
        return base

    reasons = _reasons(verdict)
    tier = _get(verdict, "tier")
    parts: List[str] = [base]

    if status in ("Verified", "Likely match"):
        row_id = _get(verdict, "matched_row_id")
        if row_id not in (None, ""):
            parts.append(cat["matched_entry"].format(row_id=_clean(row_id)))
        level = _level(_get(verdict, "confidence"))
        if level:
            parts.append(cat["strength"].format(level=cat["levels"][level]))
        if status == "Likely match":
            parts.append(cat["tier3_note"] if tier == 3 else cat["tier2_note"] if tier == 2 else "")
            parts.append(cat["likely_next"])
    elif status == "Contradicted":
        parts += _diff_sentences(_get(verdict, "field_differences"), cat)
        parts.append(cat["contradicted_next"])
    elif status == "Not found":
        if _has(reasons, "already assigned"):
            parts.append(cat["not_found_taken"])
        parts.append(cat["not_found_next"])
    elif status == "Duplicate":
        if _has(reasons, "different payer names"):
            parts.append(cat["duplicate_names"])
        elif _has(reasons, "primary submission"):
            parts.append(cat["duplicate_primary"])
        parts.append(cat["duplicate_next"])
    elif status == "Can't verify yet":
        follow = _as_dt(_get(verdict, "follow_up_after"))
        if follow is not None:
            parts.append(cat["cvy_followup"].format(date=_fmt_dt(follow)))
        elif _has(reasons, "earlier statement"):
            parts.append(cat["cvy_earlier"])
        elif _has(reasons, "no readable amount"):
            parts.append(cat["cvy_amount"])
        elif _has(reasons, "no readable timestamp"):
            parts.append(cat["cvy_time"])
        elif _has(reasons, "only INR"):
            parts.append(cat["cvy_currency"])
        elif _has(reasons, "parsed with low confidence"):
            parts.append(cat["cvy_parse"])
        elif _has(reasons, "no readable transactions"):
            parts.append(cat["cvy_empty"])
        elif _has(reasons, "coverage dates"):
            parts.append(cat["cvy_coverage"])
        else:
            parts.append(cat["cvy_newer"])

    if tone == "friendly":
        parts.insert(0, cat["greeting"])
    return " ".join(p for p in parts if p)


def _with_reply(verdict: Any, text: str) -> Any:
    if hasattr(verdict, "model_copy"):      # pydantic v2
        return verdict.model_copy(update={"suggested_reply": text})
    if hasattr(verdict, "copy"):            # pydantic v1
        return verdict.copy(update={"suggested_reply": text})
    raise TypeError("verdict must be a pydantic model")


def attach_replies(verdicts: Iterable[Any], tone: str = DEFAULT_TONE, language: str = DEFAULT_LANGUAGE,
                   overwrite: bool = False) -> List[Any]:
    """Return COPIES of the verdicts with ``suggested_reply`` filled in.

    Existing non-empty replies are kept unless ``overwrite=True``. Status, tier,
    confidence, reasons etc. are never changed.
    """
    out = []
    for v in verdicts or []:
        existing = _get(v, "suggested_reply")
        if existing and not overwrite:
            out.append(v)
        else:
            out.append(_with_reply(v, generate_reply(v, tone=tone, language=language)))
    return out
