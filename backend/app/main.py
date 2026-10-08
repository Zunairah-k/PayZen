from typing import List, Optional
from fastapi import FastAPI, File, Form, UploadFile
from starlette.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from app.models import Claim, Verdict, VerifyRequest
from app.services.extractor import extract_claim
from app.services.ingestor import ingest_statement_full
from app.services.matcher import match_claims
from app.services.reply_generator import attach_replies

app = FastAPI(title="PayZen API")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/claims/upload", response_model=List[Claim])
async def claims_upload(files: List[UploadFile] = File(...)):
    return [extract_claim(await f.read(), f.filename) for f in files]

@app.post("/statement/upload")
async def statement_upload(file: UploadFile = File(...), password: Optional[str] = Form(None),
                           allow_vision: bool = Form(False)):
    data = await file.read()
    rows, meta, preview = await run_in_threadpool(ingest_statement_full, data, file.filename, password, allow_vision)
    return {"rows": rows, "meta": meta, "preview": preview}

@app.post("/verify", response_model=List[Verdict])
def verify_endpoint(req: VerifyRequest):
    return attach_replies(match_claims(req.claims, req.rows, req.meta))