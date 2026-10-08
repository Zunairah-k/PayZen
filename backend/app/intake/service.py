"""Secure email intake: screened mail from the Agentboxd inbox -> PayZen's existing ingestion.

Principles
  * Email is untrusted input. Nothing from a subject or body is ever given to a model as
    instructions; we read only metadata (labels, scores, attachment types) to decide.
  * Agentboxd screens first (spoofing, prompt-injection and phishing scores, virus scan);
    we add our own policy on top and quarantine anything doubtful.
  * Clean mail's attachments go to the SAME pipelines as a manual upload. Everything is in memory.
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..ingestion.pipeline import IngestResult, ingest_statement
from .client import AgentboxdClient, AgentboxdError

BLOCK_LABELS = {"ai:phishing", "ai:injection-risk", "local:injection-risk"}
AUTH_FAIL_LABELS = {"spf-fail", "dmarc-fail"}
INJECTION_BLOCK = float(os.getenv("INTAKE_INJECTION_BLOCK", "0.5"))
PHISHING_BLOCK = float(os.getenv("INTAKE_PHISHING_BLOCK", "0.5"))
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_RECORDS = 200
STATEMENT_EXT = {".csv", ".xlsx", ".txt", ".pdf"}
IMAGE_EXT = {".png", ".jpg", ".jpeg"}

ScreenshotHandler = Callable[[bytes, str, Dict[str, Any]], Any]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sender(msg: Dict[str, Any]) -> str:
    f = msg.get("from")
    if isinstance(f, list) and f:
        f = f[0]
    if isinstance(f, dict):
        return str(f.get("address") or f.get("email") or "")
    return str(f or "")


def assess(msg: Dict[str, Any]) -> Dict[str, Any]:
    """Our policy on top of Agentboxd's checks. Uses scores and labels only, never the message text."""
    labels = set(msg.get("labels") or [])
    ai = msg.get("ai") or {}
    risk = ai.get("risk") or {}
    inj, phi = float(risk.get("injection") or 0), float(risk.get("phishing") or 0)
    screening, analysis = msg.get("screening") or {}, msg.get("analysis") or {}

    high: List[str] = []
    medium: List[str] = []
    if screening.get("state") == "held":
        high.append(f"held by Agentboxd screening ({screening.get('reason')})")
    for label in sorted(labels & BLOCK_LABELS):
        high.append(f"flagged {label}")
    if inj >= INJECTION_BLOCK:
        high.append(f"prompt-injection score {inj:.2f}")
    if phi >= PHISHING_BLOCK:
        high.append(f"phishing score {phi:.2f}")
    if (ai.get("local_screen") or {}).get("flagged"):
        high.append("hidden or instruction-like text found in the message")
    spoof = sorted(labels & AUTH_FAIL_LABELS)
    if spoof:
        medium.append("sender failed authentication (" + ", ".join(spoof) + ")")
    if analysis and analysis.get("state") != "completed":
        medium.append("security check did not complete")

    reasons = high + medium
    return {
        "decision": "quarantined" if reasons else "accepted",
        "severity": "high" if high else ("medium" if medium else "none"),
        "reasons": reasons,
        "scores": {"injection": inj, "phishing": phi},
        "labels": sorted(labels),
    }


def classify_attachment(att: Dict[str, Any]) -> str:
    ext = os.path.splitext((att.get("filename") or "").lower())[1]
    if ((att.get("extraction") or {}).get("error") or {}).get("code") == "inline_image" or att.get("available") is False:
        return "skip"
    if ext in STATEMENT_EXT:
        return "statement"
    if ext in IMAGE_EXT:
        return "screenshot"
    return "other"


class IntakeService:
    def __init__(self, client: AgentboxdClient, inbox_id: str, address: str = "", llm_policy: Optional[str] = None):
        self.client, self.inbox_id, self.address = client, inbox_id, address
        self.llm_policy = llm_policy or os.getenv("INTAKE_LLM_POLICY", "fallback")
        self._records: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._alerts: List[Dict[str, Any]] = []
        self._results: Dict[Tuple[str, str], IngestResult] = {}
        self._screenshot_handler: Optional[ScreenshotHandler] = None
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "IntakeService":
        client = AgentboxdClient()
        inbox = client.ensure_inbox(username=os.getenv("AGENTBOXD_INBOX_USERNAME", "payzen-proofs"),
                                    display_name="PayZen payment proofs", client_id="payzen-intake")
        return cls(client, inbox["id"], inbox.get("address", ""))

    # ---- hooks for teammates ------------------------------------------------
    def register_screenshot_handler(self, fn: ScreenshotHandler) -> None:
        """fn(image_bytes, filename, meta) -> any JSON-friendly summary. Alizah's claim extractor plugs in here."""
        self._screenshot_handler = fn

    def get_statement_result(self, message_id: str, filename: str) -> Optional[IngestResult]:
        return self._results.get((message_id, filename))

    # ---- reads --------------------------------------------------------------
    def records(self) -> List[Dict[str, Any]]:
        return list(reversed(self._records.values()))

    def alerts(self) -> List[Dict[str, Any]]:
        return list(reversed(self._alerts))

    def status(self) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        for r in self._records.values():
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        return {"address": self.address, "inbox_id": self.inbox_id, "counts": counts, "alerts": len(self._alerts)}

    # ---- the work -----------------------------------------------------------
    def poll(self, limit: int = 10) -> Dict[str, Any]:
        with self._lock:
            new: List[Dict[str, Any]] = [self._process(item) for item in self.client.claim(self.inbox_id, limit=limit)]
            for held in self.client.list_held(self.inbox_id):
                if held.get("id") not in self._records:
                    new.append(self._record_held(held))
        return {
            "processed": len(new),
            "accepted": sum(1 for r in new if r["status"] == "accepted"),
            "quarantined": sum(1 for r in new if r["status"] in ("quarantined", "held_by_agentboxd")),
            "records": new,
        }

    def _store(self, rec: Dict[str, Any]) -> Dict[str, Any]:
        self._records[rec["message_id"]] = rec
        while len(self._records) > MAX_RECORDS:
            self._records.popitem(last=False)
        return rec

    def _alert(self, rec: Dict[str, Any], assessment: Dict[str, Any]) -> None:
        self._alerts.append({"message_id": rec["message_id"], "from": rec["from"], "severity": assessment["severity"],
                             "reasons": assessment["reasons"], "at": _now()})
        del self._alerts[:-MAX_RECORDS]

    def _process(self, item: Dict[str, Any]) -> Dict[str, Any]:
        msg, lease = item["message"], item.get("lease_id")
        mid = msg.get("id")
        rec: Dict[str, Any] = {
            "message_id": mid, "from": _sender(msg), "subject": msg.get("subject") or "",
            "received_at": msg.get("received_at") or msg.get("created_at") or "",
            "attachments": [], "processed_at": _now(),
        }
        try:
            a = assess(msg)
            rec["assessment"] = a
            if a["decision"] == "quarantined":
                rec["status"] = "quarantined"
                self._alert(rec, a)
            else:
                rec["status"] = "accepted"
                for att in msg.get("attachments") or []:
                    rec["attachments"].append(self._handle_attachment(mid, rec, att))
            self.client.ack(mid, lease)
            try:
                self.client.label(mid, ["payzen:accepted" if rec["status"] == "accepted" else "payzen:quarantined"])
            except AgentboxdError:
                pass
        except Exception as exc:  # never lose the loop over one bad message
            rec["status"], rec["error"] = "error", type(exc).__name__
            try:
                self.client.nack(mid, lease, 60)
            except AgentboxdError:
                pass
        return self._store(rec)

    def _record_held(self, held: Dict[str, Any]) -> Dict[str, Any]:
        w = held.get("withheld") or {}
        reason = w.get("reason") or (held.get("screening") or {}).get("reason") or "unknown"
        a = {"decision": "quarantined", "severity": "high", "reasons": [f"held by Agentboxd screening ({reason})"],
             "scores": {}, "labels": held.get("labels") or []}
        rec = {"message_id": held.get("id"), "from": _sender(held), "subject": "(withheld)",
               "received_at": held.get("received_at") or held.get("created_at") or "", "attachments": [],
               "processed_at": _now(), "status": "held_by_agentboxd", "assessment": a}
        self._alert(rec, a)
        return self._store(rec)

    def _handle_attachment(self, mid: str, rec: Dict[str, Any], att: Dict[str, Any]) -> Dict[str, Any]:
        name, kind = att.get("filename") or "attachment", classify_attachment(att)
        out: Dict[str, Any] = {"filename": name, "kind": kind, "size_bytes": att.get("size_bytes")}
        if kind in ("skip", "other"):
            out["outcome"] = {"ignored": True}
            return out
        if (att.get("size_bytes") or 0) > MAX_ATTACHMENT_BYTES:
            out["outcome"] = {"ok": False, "error_code": "too_large"}
            return out
        try:
            data = self.client.download_attachment(att["id"])
        except AgentboxdError as exc:
            out["outcome"] = {"ok": False, "error_code": exc.code}
            return out
        if kind == "statement":
            res = ingest_statement(data, name, llm_policy=self.llm_policy)
            self._results[(mid, name)] = res
            meta = res.meta
            out["outcome"] = {
                "ok": res.ok, "rows": len(res.rows), "chain": (res.report.chain or {}).get("status"),
                "needs_confirmation": res.report.needs_confirmation, "error_code": res.report.error_code,
                "message": res.report.user_message,
                "coverage_start": meta.coverage_start.isoformat() if meta and meta.coverage_start else None,
                "coverage_end": meta.coverage_end.isoformat() if meta and meta.coverage_end else None,
            }
        elif self._screenshot_handler is not None:
            try:
                out["outcome"] = {"ok": True, "result": self._screenshot_handler(data, name, {"message_id": mid, "from": rec["from"]})}
            except Exception as exc:
                out["outcome"] = {"ok": False, "error_code": "handler_error", "detail": type(exc).__name__}
        else:
            out["outcome"] = {"ok": None, "note": "payment screenshot received; no claim extractor registered yet",
                              "bytes": len(data)}
        return out