"""FastAPI router for the secure email intake channel."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from .client import AgentboxdError
from .service import IntakeService

router = APIRouter(prefix="/intake", tags=["secure email intake"])
_service: Optional[IntakeService] = None


def get_service() -> IntakeService:
    global _service
    if _service is None:
        try:
            _service = IntakeService.from_env()
        except AgentboxdError as exc:
            raise HTTPException(status_code=503, detail=f"Email intake is not available: {exc.message}")
    return _service


@router.get("/status")
def status():
    return get_service().status()


@router.post("/poll")
def poll():
    try:
        return get_service().poll()
    except AgentboxdError as exc:
        raise HTTPException(status_code=502, detail=f"Email service error: {exc.message}")


@router.get("/messages")
def messages():
    return {"data": get_service().records()}


@router.get("/alerts")
def alerts():
    return {"data": get_service().alerts()}