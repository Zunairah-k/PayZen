# Secure email intake (Agentboxd): guide for the team

**Owner:** Zunairah  |  **Code:** `backend/app/intake/`  |  **Tests:** `tests/intake/`
**One line:** payment proofs can arrive by email at a secure inbox; Agentboxd checks them for tricks, we quarantine anything suspicious and send the clean ones through the same pipeline as a manual upload.

## 1. What each person needs to do

| Who | Task | Size |
|---|---|---|
| **Umaima** | Add 2 lines to `main.py` and a "Secure Email Intake" panel in the UI (see section 5) | small |
| **Alizah** | Register the screenshot extractor so email screenshots are verified (see section 6) | 3 lines |
| **Everyone** | Add `AGENTBOXD_API_KEY` to the deployed environment (see section 3) | 1 minute |

## 2. How it works
```
Email + attachment -> Agentboxd inbox (spoofing, injection, phishing checks, virus scan)
   |-- held by Agentboxd        -> never opened by us -> alert
   |-- claimed by our service   -> our policy
         |-- suspicious -> quarantined, attachments never downloaded, alert
         |-- clean      -> statements -> ingest_statement -> matcher
                           screenshots -> claim extractor -> matcher
```
Rule: **email text is never given to a model as instructions.** We read only labels, scores and file types.

## 3. Setup
1. Get a key: Agentboxd dashboard -> API keys -> Create key (whole workspace, full access, expires 30 days). Copy the `mr_...` key; it is shown once.
2. Put it in `.env` (never committed; `.env.example` lists the names):
```
   AGENTBOXD_API_KEY=mr_your_key
   GEMINI_API_KEY=your_gemini_key
```
3. Load it into your terminal each session:
```powershell
   Get-Content .env | Where-Object { $_ -match '^\s*[^#\s]\S*=' } | ForEach-Object { $k,$v = $_ -split '=',2; Set-Item "Env:$($k.Trim())" $v.Trim() }
```
4. On Render, add the same variables under Environment. The inbox is created automatically on first use: `payzen-proofs@homingbox.net`.

| Variable | Default | Meaning |
|---|---|---|
| `AGENTBOXD_API_KEY` | none (required) | Agentboxd API key |
| `AGENTBOXD_BASE_URL` | `https://api.agentboxd.com` | API address |
| `AGENTBOXD_INBOX_USERNAME` | `payzen-proofs` | name of the inbox |
| `INTAKE_LLM_POLICY` | `fallback` | model use for column mapping of emailed statements |
| `INTAKE_INJECTION_BLOCK` | `0.5` | quarantine at or above this injection score |
| `INTAKE_PHISHING_BLOCK` | `0.5` | quarantine at or above this phishing score |

## 4. API (mounted at `/intake`)
All JSON. If the key is missing: `503`. If Agentboxd is unreachable: `502`.

| Route | What it does |
|---|---|
| `GET /intake/status` | `{address, inbox_id, counts:{status:n}, alerts:n}` |
| `POST /intake/poll` | Fetch and process new mail now. Returns `{processed, accepted, quarantined, records:[...]}` |
| `GET /intake/messages` | `{data:[record,...]}` newest first |
| `GET /intake/alerts` | `{data:[{message_id, from, severity, reasons[], at}]}` newest first |

**Record**
```json
{
  "message_id": "…", "from": "name <addr>", "subject": "…", "received_at": "…", "processed_at": "…",
  "status": "accepted | quarantined | held_by_agentboxd | error",
  "assessment": {"decision": "accepted|quarantined", "severity": "none|medium|high",
                 "reasons": ["…"], "scores": {"injection": 0.01, "phishing": 0.02}, "labels": ["…"]},
  "attachments": [{"filename": "…", "kind": "statement|screenshot|other|skip", "size_bytes": 0, "outcome": {…}}]
}
```
**Attachment outcomes**
- Statement: `{ok, rows, chain, needs_confirmation, error_code, message, coverage_start, coverage_end}`
- Screenshot, no extractor yet: `{ok: null, note, bytes}`; with extractor: `{ok: true, result: <your summary>}`; on failure `{ok: false, error_code: "handler_error"}`
- Ignored file types: `{ignored: true}`
- Held mail has no attachments listed and the subject is shown as `(withheld)`.

## 5. For Umaima: the UI panel
Add to `main.py`:
```python
from .intake.router import router as intake_router
app.include_router(intake_router)
```
Panel "Secure Email Intake":
1. Show the address from `/intake/status` with a copy button and the text "Email payment proofs here".
2. A **Check inbox** button calling `POST /intake/poll`, then refresh the table.
3. A table from `/intake/messages`: sender, status chip (green accepted, red quarantined or held), reasons, attachments with their outcomes (for a statement: "80 rows, balance check passed").
4. A **Security alerts** list from `/intake/alerts`.
5. **Escape subject and sender before showing them.** They come from outside and must be treated as untrusted text.

## 6. For Alizah: the screenshot hook
```python
from backend.app.intake.router import get_service

def read_screenshot(image_bytes, filename, meta):
    # run your screenshot extractor; return a small JSON-friendly summary
    return {"claims": 1}

get_service().register_screenshot_handler(read_screenshot)
```
Call it once at startup (or lazily on the first poll). Until it is registered, email screenshots are received but not verified. Statement files from email are already verified: `get_service().get_statement_result(message_id, filename)` returns the full ingestion result, and `backend/app/ingestion/adapter.py::to_shared` converts it for the matcher.

## 7. Our policy (`assess` in `service.py`)
- **High severity, quarantine:** held by Agentboxd; labels `ai:phishing`, `ai:injection-risk`, `local:injection-risk`; injection or phishing score at or above the threshold; hidden instruction-like text.
- **Medium severity, quarantine:** sender failed SPF or DMARC; the security check did not complete.
- Otherwise accepted. Attachments of quarantined mail are **never downloaded**.
- After processing, each message is acknowledged and labelled `payzen:accepted` or `payzen:quarantined` in the Agentboxd inbox.

## 8. Testing and review
```powershell
python -m pytest tests -q                 # whole repo (577 passed at last run)
python -m pytest tests/intake -q          # intake only, no key or internet needed
python -m tests.intake.live_demo          # real inbox; needs AGENTBOXD_API_KEY
```
The five offline tests cover: clean email flowing into ingestion; injection email quarantined with its attachment not downloaded; spoofed sender quarantined (medium); held mail reported once without content; screenshot routed to the handler.

**Reviewer checklist:** key only in `.env` or environment, never in code; `.env` not in `git status`; subject and sender escaped in the UI; blocked mail never shows content; synthetic files only.

**Live demo script (about 60 seconds):** show the address; send the clean email (statement + screenshot) and click Check inbox: green row, "80 rows, balance check passed"; send the prompt-injection email: red row, reason shown, no attachment read; point at the alert list.

## 9. Live results so far
| Email | Result |
|---|---|
| Clean, statement CSV + screenshot | accepted; 80 rows, balance check passed (79/79); screenshot received |
| Prompt-injection text + CSV | held by Agentboxd (`injection_risk`) |
| Phishing-style text | held by Agentboxd (`phishing`) |

Both bad emails were stopped by Agentboxd before our policy saw them; our policy is verified by the offline tests.

## 10. Troubleshooting
| Symptom | Fix |
|---|---|
| `Set the AGENTBOXD_API_KEY environment variable` | load `.env` into the terminal (section 3) |
| `/intake/*` returns 503 | key missing in the server's environment |
| Nothing arrives | allow up to 1 to 2 minutes; mail sent before the first poll is still picked up by the next poll |
| `401 api_key_expired` | the key lasted 30 days; create a new one |
| Clean email quarantined | read `assessment.reasons`; if it is a score, raise `INTAKE_INJECTION_BLOCK` or `INTAKE_PHISHING_BLOCK` and note it in the write-up |
| Statement says `needs_confirmation` | same as manual upload: the user confirms the column mapping |

## 11. Limits
- Polling, not push; records live in memory and reset on restart.
- Thresholds are untuned; evaluated on 3 live emails (a bigger test is planned for Day 3).
- Attachments pass through Agentboxd (EU-hosted): synthetic files only.
- No replies are sent from the inbox yet.
- The Builder plan from the hackathon code lasts 60 days; the API key expires after 30.

## 12. How to describe it (README and Devpost)
> We added a secure email ingestion channel to our existing payment-proof verification system. Emails arrive at an Agentboxd inbox that scores every message for spoofing, prompt injection and phishing. Held messages are never opened by our code; clean messages are re-checked by our policy and their statement files and screenshots go through the same pipeline as a manual upload. The detection is Agentboxd's; the quarantine policy, routing and verification are ours.