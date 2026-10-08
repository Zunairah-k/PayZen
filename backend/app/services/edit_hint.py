"""PayZen — weak "possible image modification" hint (Alizah, Phase 3).

    compute_edit_hint(claim, peers=None, image_bytes=None) -> {"signal", "reason", "confidence"}

This is a SUPPORTING signal only. It returns a plain dict, never touches a
Verdict, and has no way to produce Verified / Contradicted / fraud verdicts.
It is not image forensics. Two cheap, deterministic signals only:

1. Peer comparison (uses Phase 1 image hashes): a screenshot that is visually
   near-identical to another claim's but whose payment fields differ.
   - same reference AND amount/payer name/time differ  -> "medium"
   - differing amount/reference only                    -> "low"
   (Same-app screenshots look alike, hence the weak ratings.)
2. File metadata (needs Pillow, optional): metadata that names a known image
   editor -> "medium". Metadata is trivially stripped; absence proves nothing.

No evidence -> "none" (never an invented signal).
"""
from __future__ import annotations

import io
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .extractor import hamming_distance
from .matcher import name_similarity

NEAR_HASH_BITS = 6  # same threshold as the matcher's duplicate rule (of 256 bits)

_EDITORS = ("photoshop", "gimp", "canva", "snapseed", "pixlr", "lightroom", "paint.net", "picsart",
            "photopea", "illustrator", "affinity", "fotor", "inkscape", "figma", "mspaint")
_RANK = {"none": 0, "low": 1, "medium": 2}


def _g(obj: Any, name: str) -> Any:
    return getattr(obj, name, None)


def _amount(v: Any) -> Optional[float]:
    try:
        return round(float(v), 2) if v is not None and not isinstance(v, bool) else None
    except (TypeError, ValueError):
        return None


def _safe(text: Any, limit: int = 60) -> str:
    s = unicodedata.normalize("NFKC", str(text))
    s = "".join(ch for ch in s if unicodedata.category(ch) not in ("Cc", "Cf"))
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _peer_signals(claim: Any, peers: Iterable[Any], near_bits: int) -> List[Tuple[int, float, str]]:
    found: List[Tuple[int, float, str]] = []
    cid = str(_g(claim, "claim_id"))
    for p in sorted((p for p in peers or [] if str(_g(p, "claim_id")) != cid), key=lambda p: str(_g(p, "claim_id"))):
        d = hamming_distance(_g(claim, "image_hash"), _g(p, "image_hash"))
        if d is None or d > near_bits:
            continue
        ra, rb = _g(claim, "reference"), _g(p, "reference")
        same_ref = bool(ra and rb and ra == rb)
        diff: List[str] = []
        aa, ab = _amount(_g(claim, "amount")), _amount(_g(p, "amount"))
        if aa is not None and ab is not None and aa != ab:
            diff.append("amount")
        na, nb = _g(claim, "payer_name"), _g(p, "payer_name")
        if na and nb:
            s = name_similarity(na, nb)
            if s is not None and s < 0.5:
                diff.append("payer name")
        ta, tb = _g(claim, "timestamp"), _g(p, "timestamp")
        if ta and tb and str(ta) != str(tb):
            diff.append("time")
        ref_differs = bool(ra and rb and ra != rb)
        if same_ref and diff:
            rank, conf = 2, 0.55
        elif ("amount" in diff) or ref_differs:
            rank, conf = 1, 0.25
            if ref_differs and "reference" not in diff:
                diff.append("reference")
        else:
            continue  # same payment fields: that is duplicate evidence (matcher's job), not an edit hint
        pid = _safe(_g(p, "claim_id"))
        fields = ", ".join(sorted(set(diff)))
        found.append((rank, conf,
                      f"Screenshot is visually near-identical to claim {pid}'s (fingerprint distance {d}) but its "
                      f"{fields} differ{'s' if len(set(diff)) == 1 else ''}"
                      f"{' for the same reference' if same_ref else ''}. Weak signal: screenshots from the same app look alike."))
    return found


def _metadata_signal(image_bytes: bytes) -> Optional[Tuple[int, float, str]]:
    try:
        from PIL import Image  # optional dependency, already used by Phase 1
        with Image.open(io.BytesIO(image_bytes)) as img:
            values = [img.info.get("Software"), img.info.get("software")]
            try:
                values.append(img.getexif().get(305))
            except Exception:
                pass
    except Exception:
        return None
    for v in values:
        if v is None:
            continue
        text = v.decode("latin-1", "ignore") if isinstance(v, bytes) else str(v)
        low = text.lower()
        if any(e in low for e in _EDITORS):
            return (2, 0.50, f"Image metadata names an editing application ('{_safe(text)}'). "
                             "Metadata is easily removed or changed, so this is a weak signal.")
    return None


def compute_edit_hint(claim: Any, peers: Optional[Iterable[Any]] = None, image_bytes: Optional[bytes] = None,
                      near_hash_bits: int = NEAR_HASH_BITS) -> Dict[str, Any]:
    """Weak, deterministic modification hint. See module docstring."""
    signals: List[Tuple[int, float, str]] = []
    has_info = bool(_g(claim, "image_hash")) or bool(image_bytes)
    if _g(claim, "image_hash") and peers:
        signals += _peer_signals(claim, peers, near_hash_bits)
    if image_bytes:
        m = _metadata_signal(bytes(image_bytes))
        if m:
            signals.append(m)
    if not has_info:
        return {"signal": "none", "reason": "No image information is available for this claim.", "confidence": 0.0}
    if not signals:
        return {"signal": "none",
                "reason": "No image-based indication of modification was found; this does not prove the screenshot is unmodified.",
                "confidence": 0.0}
    signals.sort(key=lambda s: (-s[0], -s[1], s[2]))
    top = signals[0]
    conf = top[1] + (0.05 if len(signals) > 1 and signals[1][0] == top[0] else 0.0)
    reason = " ".join(s[2] for s in signals[:2])
    return {"signal": "medium" if top[0] == 2 else "low", "reason": reason, "confidence": round(min(conf, 0.7), 4)}


def edit_hints_for_claims(claims: Iterable[Any], image_bytes_by_claim_id: Optional[Dict[str, bytes]] = None) -> Dict[str, Dict[str, Any]]:
    """{claim_id: hint} for every claim, comparing each against all the others."""
    cl = list(claims or [])
    imgs = image_bytes_by_claim_id or {}
    return {str(_g(c, "claim_id")): compute_edit_hint(c, peers=cl, image_bytes=imgs.get(str(_g(c, "claim_id")))) for c in cl}
