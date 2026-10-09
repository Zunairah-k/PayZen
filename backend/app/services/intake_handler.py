"""PayZen — Agentboxd screenshot handler (Alizah, Prompt 6).

Connects clean e-mailed screenshots to the EXISTING extractor:

    from <package>.services.intake_handler import register_screenshot_handler
    register_screenshot_handler()          # once, at startup (idempotent)

The intake service (Zunairah) calls ``read_screenshot(image_bytes, filename, meta)``
only for attachments of mail that passed its policy; held / quarantined mail is
never downloaded, so this module never sees it. It does NOT change that policy.

What the handler does
---------------------
* runs ``extract_claim_detailed`` from ``extractor.py`` (no second extractor),
* returns a small JSON-friendly summary that the service stores as
  ``{"ok": true, "result": <summary>}``,
* keeps the Claim in a bounded in-memory list (``get_email_claims``) so the API
  can later run the normal matcher against a statement,
* NEVER says a payment is verified: extraction only produces a claim.

Failure handling: every error is contained and reported with a fixed code and a
generic message. No exception text, image content, names or amounts are logged.
Untrusted inputs (filename, ``meta``) are never interpreted as instructions.
"""
from __future__ import annotations

import importlib
import json
import logging
import re
import threading
import unicodedata
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from .extractor import extract_claim_detailed

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 10 * 1024 * 1024   # refuse absurdly large attachments before decoding
MAX_STORED_CLAIMS = 200              # bounded in-memory store (resets on restart, like intake records)

VERIFICATION_NOTE = ("A claim was extracted from the screenshot. It has NOT been verified; "
                     "verification requires the matcher and a statement.")

_ERRORS = {
    "invalid_input": "The attachment could not be read as image data.",
    "empty_image": "The screenshot attachment was empty.",
    "image_too_large": "The screenshot attachment is too large to process.",
    "extraction_failed": "The screenshot could not be processed.",
}

_FIELDS = ("payer_name", "payer_upi_id", "payee_name", "payee_upi_id", "amount", "currency",
           "timestamp", "reference", "app_style_guess", "status_shown")
_PAYMENT_FIELDS = ("amount", "reference", "timestamp", "payer_name", "payer_upi_id")

_lock = threading.Lock()
_claims: "OrderedDict[str, Any]" = OrderedDict()
_registered: Dict[int, Any] = {}     # id(service) -> service (strong ref keeps ids unique)


# ---------------------------------------------------------------- helpers

def _safe_text(value: Any, limit: int = 100) -> str:
    s = unicodedata.normalize("NFKC", str(value))
    s = "".join(ch for ch in s if unicodedata.category(ch) not in ("Cc", "Cf"))
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


def _message_id(meta: Any) -> str:
    """Best-effort message id from untrusted ``meta`` (used only as a storage key)."""
    try:
        raw = meta.get("message_id") if isinstance(meta, dict) else getattr(meta, "message_id", None)
    except Exception:
        raw = None
    return _safe_text(raw) if raw else "unknown"


def _jsonable(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=str))


def _error(code: str) -> Dict[str, Any]:
    return {"extracted": False, "claims": 0, "error_code": code, "message": _ERRORS[code],
            "verification": "not_verified", "verification_note": VERIFICATION_NOTE}


def _claim_dict(claim: Any) -> Dict[str, Any]:
    if hasattr(claim, "model_dump"):
        return claim.model_dump()
    return claim.dict()


def _remember(key: str, claim: Any) -> None:
    with _lock:
        _claims[key] = claim
        _claims.move_to_end(key)
        while len(_claims) > MAX_STORED_CLAIMS:
            _claims.popitem(last=False)


# ---------------------------------------------------------------- handler

def read_screenshot(image_bytes: Any, filename: Any, meta: Any = None) -> Dict[str, Any]:
    """Handler registered with the intake service. Never raises."""
    try:
        if not isinstance(image_bytes, (bytes, bytearray)):
            return _error("invalid_input")
        if len(image_bytes) == 0:
            return _error("empty_image")
        if len(image_bytes) > MAX_IMAGE_BYTES:
            return _error("image_too_large")
        name = _safe_text(filename, 255) or "screenshot"
        details = extract_claim_detailed(bytes(image_bytes), name)   # existing Phase 1 extractor
        claim = details.claim
        data = _claim_dict(claim)
        extracted = any(data.get(f) not in (None, "") for f in _PAYMENT_FIELDS)
        _remember(f"{_message_id(meta)}:{_safe_text(name, 120)}:{data.get('claim_id')}", claim)
        notes = data.get("extraction_notes")
        summary: Dict[str, Any] = {
            "extracted": extracted,
            "claims": 1 if extracted else 0,
            "claim_id": data.get("claim_id"),
            "source_file": data.get("source_file"),
            "image_hash": data.get("image_hash"),
            "confidence": data.get("confidence") or {},
            "notes": notes if isinstance(notes, list) else ([notes] if notes else []),
            "provider": details.provider_name,
            "mock_provider": bool(details.is_mock),
            "verification": "not_verified",
            "verification_note": VERIFICATION_NOTE,
        }
        for f in _FIELDS:
            summary[f] = data.get(f)
        if details.partial_date:
            summary["partial_date"] = details.partial_date
        if details.partial_time:
            summary["partial_time"] = details.partial_time
        return _jsonable(summary)
    except Exception as exc:  # contained: one bad screenshot must not stop the inbox
        logger.warning("screenshot extraction failed (%s)", type(exc).__name__)  # type only: no content
        return _error("extraction_failed")


# ---------------------------------------------------------------- stored claims

def get_email_claims(message_id: Optional[str] = None) -> List[Any]:
    """Claims extracted from e-mailed screenshots (newest last). Feed them to ``match_claims``."""
    with _lock:
        items = list(_claims.items())
    if message_id is None:
        return [c for _, c in items]
    prefix = f"{_safe_text(message_id)}:"
    return [c for k, c in items if k.startswith(prefix)]


def clear_email_claims() -> None:
    with _lock:
        _claims.clear()


# ---------------------------------------------------------------- registration

def _resolve_service() -> Any:
    """Import the intake service from the same package root as this module
    (``backend.app`` or ``app``), so module identities stay consistent."""
    root = (__package__ or "").rsplit(".", 1)[0]          # "<root>.services" -> "<root>"
    module = importlib.import_module(f"{root}.intake.router")
    return module.get_service()


def register_screenshot_handler(service: Any = None) -> bool:
    """Register ``read_screenshot`` with the intake service, at most once per service.

    Returns True if it registered now, False if it was already registered or the
    intake service is unavailable (never raises, makes no network calls, does not
    run the extractor).
    """
    try:
        svc = service if service is not None else _resolve_service()
    except Exception as exc:
        logger.warning("intake service unavailable; screenshot handler not registered (%s)", type(exc).__name__)
        return False
    with _lock:
        if id(svc) in _registered:
            return False
        _registered[id(svc)] = svc
    try:
        svc.register_screenshot_handler(read_screenshot)
    except Exception as exc:
        with _lock:
            _registered.pop(id(svc), None)
        logger.warning("screenshot handler registration failed (%s)", type(exc).__name__)
        return False
    return True


def ensure_registered() -> bool:
    """Lazy variant for the first poll: same as ``register_screenshot_handler()``."""
    return register_screenshot_handler()


def _reset_registration_for_tests() -> None:
    with _lock:
        _registered.clear()
