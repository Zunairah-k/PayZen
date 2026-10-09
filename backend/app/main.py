import asyncio
import os
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.intake.router import router as intake_router
from app.models import Claim, StatementMeta, StatementRow, Verdict, VerifyRequest
from app.payment_links import router as links_router
from app.services.extractor import extract_claim
from app.services.ingestor import ingest_statement_full
from app.services.matcher import match_claims
from app.services.rechecker import recheck_claims
from app.services.reply_generator import attach_replies

MAX_CLAIM_FILES = int(os.getenv("MAX_CLAIM_FILES", "25"))
CONCURRENCY = 4  # parallel screenshot extractions (keeps vision-model rate limits happy)


class RecheckRequest(BaseModel):
    claims: List[Claim]
    rows: List[StatementRow]
    meta: StatementMeta
    previous_verdicts: List[Verdict]


app = FastAPI(title="PayZen API")
origins = ["http://localhost:5173"] + [
    o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()
]  # on Render set CORS_ORIGINS=https://your-app.vercel.app
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])
app.include_router(intake_router)
app.include_router(links_router)


@app.on_event("startup")
def _register_agentboxd_screenshot_handler():
    """Register PayZen's screenshot handlers at application startup."""
    import logging
    from app.services.intake_handler import register_screenshot_handler
    from app.services.vision_gemini import register_gemini_provider

    if not register_screenshot_handler():
        logging.getLogger(__name__).warning(
            "Agentboxd screenshot handler not registered; check intake configuration."
        )

    register_gemini_provider()


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/claims/upload", response_model=List[Claim])
async def claims_upload(files: List[UploadFile] = File(...)):
    if len(files) > MAX_CLAIM_FILES:
        raise HTTPException(status_code=413, detail=f"Please upload at most {MAX_CLAIM_FILES} screenshots at a time.")
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(f: UploadFile) -> Claim:
        data = await f.read()
        async with sem:
            return await run_in_threadpool(extract_claim, data, f.filename)

    return list(await asyncio.gather(*[one(f) for f in files]))  # order is preserved


@app.post("/statement/upload")
async def statement_upload(file: UploadFile = File(...), password: Optional[str] = Form(None),
                           allow_vision: bool = Form(False)):
    data = await file.read()
    rows, meta, preview = await run_in_threadpool(ingest_statement_full, data, file.filename, password, allow_vision)
    return {"rows": rows, "meta": meta, "preview": preview}


@app.post("/verify", response_model=List[Verdict])
def verify_endpoint(req: VerifyRequest):
    return attach_replies(match_claims(req.claims, req.rows, req.meta))


@app.post("/recheck", response_model=List[Verdict])
def recheck_endpoint(req: RecheckRequest):
    return recheck_claims(req.claims, req.rows, req.meta, previous_verdicts=req.previous_verdicts)