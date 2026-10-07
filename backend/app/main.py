from typing import List
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from app.models import Claim, Verdict, VerifyRequest
from app.services.extractor import extract_claim
from app.services.ingestor import ingest_statement
from app.services.matcher import verify

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
async def statement_upload(file: UploadFile = File(...)):
    rows, meta = ingest_statement(await file.read(), file.filename)
    return {"rows": rows, "meta": meta}

@app.post("/verify", response_model=List[Verdict])
def verify_endpoint(req: VerifyRequest):
    return verify(req.claims, req.rows, req.meta)