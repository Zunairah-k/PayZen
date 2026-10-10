# Deployment

Frontend on **Vercel**, backend on **Render** (free tier).

- App: https://payzenn.vercel.app/
- API docs: https://payzen-z43b.onrender.com/docs

## Environment variables

| Variable | Where | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | backend (secret) | Screenshot reading, statement photos, column-mapping helper |
| `GEMINI_MODEL` | backend (optional) | Overrides the default model (`gemini-3.1-flash-lite`) |
| `AGENTBOXD_API_KEY` | backend (secret) | Secure email inbox |
| `AGENTBOXD_BASE_URL` | backend (optional) | Agentboxd API address (default `https://api.agentboxd.com`) |
| `AGENTBOXD_INBOX_USERNAME` | backend (optional) | Inbox username (default `payzen-proofs`) |
| `INTAKE_LLM_POLICY` | backend (optional) | Model use for emailed-statement column mapping (default `fallback`) |
| `INTAKE_INJECTION_BLOCK`, `INTAKE_PHISHING_BLOCK` | backend (optional) | Quarantine score thresholds (default 0.5 each) |
| `CORS_ORIGINS` | backend | Frontend URL(s), no trailing slash |
| `VITE_API_URL` | frontend (Vercel) | Backend URL, no trailing slash |

Without any key the statement reader still works (rules only) and "Try sample data" works.

## Backend (Render)

- Install: `pip install -r backend/requirements.txt`
- Start (from `backend/`): `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Python 3.10+ (confirm the exact version set on Render and pin it)
- The free tier sleeps when idle: the first request can take about a minute, so open the app before a demo.

## Frontend (Vercel)

- Build from `frontend/` (`npm install`, `npm run build`); set `VITE_API_URL` to the Render URL. Never hard-code localhost in production builds.

## Secrets

Store them only in the Vercel and Render dashboards. Anything in frontend code is public. Never commit `.env`, API keys, real bank statements, real screenshots, `.venv`, `__pycache__`, `node_modules`, uploads or logs containing payment data. Rotate a key immediately if it was ever committed.

## Uploads and logging

Uploads stay in memory and are not stored. Do not log request bodies, names, UPI IDs, references or amounts. Production serves over HTTPS with an explicit CORS allow-list.

## Pre-demo smoke test

1. Open the frontend and click **Try sample data** (all six verdicts appear).
2. Upload a synthetic screenshot and statement from `data/synthetic/` and confirm verdicts.
3. Confirm the backend `/docs` page loads and CORS allows the frontend.
4. Run `python -m pytest tests -q` and record the count.

*To verify:* whether a health-check route exists (if not, Render's default port check is used).