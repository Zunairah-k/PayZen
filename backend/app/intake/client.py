"""Thin REST client for the Agentboxd email API (https://agentboxd.com/docs/api). Uses httpx only."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

DEFAULT_BASE_URL = "https://api.agentboxd.com"


class AgentboxdError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code, self.message = status, code, message


class AgentboxdClient:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None,
                 transport: Optional[httpx.BaseTransport] = None, timeout: float = 30.0):
        self.api_key = api_key or os.getenv("AGENTBOXD_API_KEY", "")
        if not self.api_key:
            raise AgentboxdError(0, "no_api_key", "Set the AGENTBOXD_API_KEY environment variable.")
        self._http = httpx.Client(
            base_url=base_url or os.getenv("AGENTBOXD_BASE_URL") or DEFAULT_BASE_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=timeout, transport=transport,
        )

    def _request(self, method: str, path: str, **kw) -> httpx.Response:
        r = self._http.request(method, path, **kw)
        if r.status_code >= 400:
            try:
                err = r.json().get("error", {})
            except ValueError:
                err = {}
            raise AgentboxdError(r.status_code, err.get("code", "http_error"), err.get("message", r.text[:200]))
        return r

    def _json(self, method: str, path: str, **kw) -> Dict[str, Any]:
        r = self._request(method, path, **kw)
        return r.json() if r.content else {}

    def ensure_inbox(self, username: str, display_name: str, client_id: str) -> Dict[str, Any]:
        """Idempotent on client_id: running it twice returns the same inbox."""
        return self._json("POST", "/v1/inboxes",
                          json={"username": username, "display_name": display_name, "client_id": client_id})

    def claim(self, inbox_id: str, limit: int = 10, lease_seconds: int = 300) -> List[Dict[str, Any]]:
        """Lease new screened mail. Only mail whose injection/phishing check completed is requested."""
        body = {"limit": limit, "lease_seconds": lease_seconds, "wait": 0, "enriched": True,
                "consumer": "payzen-intake", "analysis": "completed"}
        try:
            data = self._json("POST", f"/v1/inboxes/{inbox_id}/messages/claim", json=body)
        except AgentboxdError as exc:
            if exc.code != "analysis_unavailable":
                raise
            body.pop("analysis")
            data = self._json("POST", f"/v1/inboxes/{inbox_id}/messages/claim", json=body)
        return data.get("data", [])

    def ack(self, message_id: str, lease_id: str) -> None:
        self._json("POST", f"/v1/messages/{message_id}/ack", json={"lease_id": lease_id})

    def nack(self, message_id: str, lease_id: str, delay_seconds: int = 60) -> None:
        self._json("POST", f"/v1/messages/{message_id}/nack", json={"lease_id": lease_id, "delay_seconds": delay_seconds})

    def list_held(self, inbox_id: str, limit: int = 25) -> List[Dict[str, Any]]:
        """Mail Agentboxd kept from agents. Metadata only: the content is never returned to an API key."""
        return self._json("GET", f"/v1/inboxes/{inbox_id}/messages",
                          params={"screening": "held", "limit": limit}).get("data", [])

    def label(self, message_id: str, labels: List[str]) -> None:
        self._json("PATCH", f"/v1/messages/{message_id}", json={"add_labels": labels})

    def download_attachment(self, attachment_id: str) -> bytes:
        return self._request("GET", f"/v1/attachments/{attachment_id}").content

    def close(self) -> None:
        self._http.close()