# PayZen — Deployment Preparation

Planned: **frontend → Vercel**, **backend → Render or Railway**. Nothing has been deployed or tested on those platforms; items that depend on files not reviewed here are marked **TO BE CONFIRMED DURING FINAL INTEGRATION**.

## What the Alizah-owned services need
- Python only; standard library + pydantic (already in the project). Pillow is used for the perceptual image hash (falls back to SHA-256 without it) — confirm it is in the backend requirements file (**TO BE CONFIRMED**; `requirements-alizah-phase1.txt` lists it).
- **No environment variables are read** by the extractor, matcher, reply generator, re-checker or edit hint. No API key is required while the mock / "no provider" extractor is used.
- A real vision provider, when chosen, will need its own secret — its name and variable are **TO BE CONFIRMED DURING FINAL INTEGRATION**; none is defined today and none should be invented.

## Environment variables
| Variable | Where | Status |
|---|---|---|
| Backend URL used by the frontend | Vercel project env | **TO BE CONFIRMED** (name depends on the frontend build tool) |
| Allowed frontend origin(s) for CORS | backend env/config | **TO BE CONFIRMED** (whether `main.py` configures CORS is unknown) |
| Vision provider API key | backend env (secret) | **TO BE CONFIRMED** — does not exist yet |
| Port / host | platform-provided | usually injected by Render/Railway (**TO BE CONFIRMED** against the start command) |

## Secrets
Store them only in the platform's environment-variable / secret settings (Vercel, Render or Railway dashboard), never in the repo or frontend bundle (anything in frontend code is public). Rotate a key immediately if it was ever committed.

**Never commit:** `.env` files, API keys/tokens, real bank/UPI statements, real payment screenshots, `.venv`, `__pycache__`, `node_modules`, uploaded files, logs containing payment data.

## Backend
- Entry point: `backend/app/main.py` exists in the scaffold; its framework and routes were not reviewed (**TO BE CONFIRMED**). *If* it exposes a FastAPI `app`, the typical start command is `uvicorn app.main:app --host 0.0.0.0 --port $PORT` run from `backend/`, with install command `pip install -r requirements.txt`. Verify before using.
- Pin the Python version in the platform settings (**TO BE CONFIRMED**: version used locally).
- Health check: whether a health route exists is **TO BE CONFIRMED**. If none exists, adding a trivial one is an API-layer task for final integration (not added here). Without one, use the platform's default port check.
- Free tiers may sleep when idle; expect a slow first request and test the demo just before presenting.

## Frontend ↔ backend
Frontend calls the deployed backend base URL from a Vercel environment variable (name **TO BE CONFIRMED**); backend must allow the Vercel origin(s) via CORS and be served over HTTPS. Do not hard-code `localhost` URLs in production builds.

## Uploads and privacy expectations
- The Alizah-owned services never write uploads to disk; the extractor works on in-memory bytes and returns a Claim.
- The API layer should keep uploads in memory or a temp file deleted after the request, and must not store screenshots or statements permanently unless a retention decision is made. Container disks on these platforms may be ephemeral, so persistence cannot be assumed anyway.
- Do not log request bodies, payer names, UPI IDs, references or amounts.
- Demo only with synthetic data.

## Local vs production
| | Local | Production |
|---|---|---|
| Vision | none / `MockVisionProvider` | provider TO BE CONFIRMED |
| Data | synthetic fixtures | synthetic demo data until privacy decisions are made |
| Backend URL | `http://localhost:<port>` | HTTPS URL from Render/Railway |
| CORS | permissive local origin | explicit allow-list |
| Debug / verbose logs | acceptable with synthetic data | off |
| Secrets | local `.env` (git-ignored) | platform secret store |
