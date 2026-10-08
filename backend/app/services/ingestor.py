"""API-facing wrapper around the real statement ingestion pipeline.

    ingest_statement(file_bytes, filename)        -> (rows, meta)            same signature as before
    ingest_statement_full(file_bytes, filename,
        password=None, allow_vision=False,
        mapping=None)                              -> (rows, meta, preview)

``rows`` / ``meta`` are the shared pydantic models (app.models).
``preview`` is the plain-language "ask once" card for the UI (see ingestion/messages.py):
it also carries the error code and what the screen must ask for (password / consent / columns).

Language-model use is set by the environment variable INGEST_LLM_POLICY:
    fallback (default)  deterministic first; the model is asked only if the numbers do not verify
    always              ask the model on every file (use this to show the model in the demo)
    never               fully offline
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from ..ingestion.adapter import to_shared
from ..ingestion.mapping import Mapping
from ..ingestion.messages import build_preview
from ..ingestion.pipeline import LLM_POLICIES, ingest_statement as _ingest
from ..models import StatementMeta, StatementRow


def _policy() -> str:
    value = os.getenv("INGEST_LLM_POLICY", "fallback").strip().lower()
    return value if value in LLM_POLICIES else "fallback"


def ingest_statement_full(
    file_bytes: bytes,
    filename: Optional[str],
    password: Optional[str] = None,
    allow_vision: bool = False,
    mapping: Optional[Dict[str, Any]] = None,
) -> Tuple[List[StatementRow], StatementMeta, Dict[str, Any]]:
    override = Mapping.from_dict(mapping, None) if mapping else None
    result = _ingest(
        file_bytes, filename, llm_policy=_policy(), password=password,
        allow_vision=allow_vision, mapping_override=override,
    )
    rows, meta = to_shared(result)
    return rows, meta, build_preview(result)


def ingest_statement(file_bytes: bytes, filename: Optional[str]) -> Tuple[List[StatementRow], StatementMeta]:
    rows, meta, _ = ingest_statement_full(file_bytes, filename)
    return rows, meta
