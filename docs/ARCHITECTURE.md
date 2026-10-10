# Architecture

PayZen compares payment screenshots against the receiver's own statement and reports evidence-based verdicts. The statement is the stronger evidence. AI is used only to *read* (screenshots, unfamiliar statement layouts, photos of statements, email screening); every decision about a payment is deterministic code.

## 1. System overview

```mermaid
flowchart TB
  USER([Treasurer, seller or collector])

  subgraph FE["Frontend - React + Vite on Vercel"]
    direction TB
    UI["Landing, verify flow, results table<br/>ReasonCard drawer, follow-up list"]
    MSG["Payer messages EN / HI / TE<br/>replies.ts"]
    EXP["CSV export, printable report,<br/>claim editing, sample data"]
    API_TS["api.ts, intake.ts"]
  end

  subgraph BE["Backend - FastAPI on Render"]
    direction TB
    MAIN["main.py<br/>API routes + CORS"]

    subgraph INTAKE["intake/ - three doors"]
      UP["Upload<br/>/claims/upload, /statement/upload"]
      ZIP["WhatsApp ZIP<br/>zip_intake.py"]
      MAIL["Secure email<br/>client, service, router"]
    end

    subgraph ING["ingestion/ - statement reader"]
      LOAD["loader, pdf_loader,<br/>vision_loader"]
      MAP["mapping, normalize,<br/>parser, references"]
      CHAIN["chain: balance check<br/>coverage, pipeline"]
      ADAPT["messages, report, adapter"]
    end

    subgraph SVC["services/ - claims, decisions, replies"]
      EXTR["extractor + vision_gemini<br/>screenshot to Claim"]
      MATCH["matcher<br/>deterministic ladder"]
      REPLY["reply_generator,<br/>rechecker, edit_hint"]
      HANDLER["intake_handler<br/>email screenshots"]
    end

    MODELS[("models.py<br/>Claim, StatementRow,<br/>StatementMeta, Verdict")]
    LINKS["payment_links.py<br/>unique link + QR prototype"]
  end

  subgraph EXT["External services"]
    GEM["Google Gemini<br/>vision + column-mapping helper"]
    AGB["Agentboxd<br/>agent inbox: spoofing, injection,<br/>phishing screening"]
  end

  USER --> UI
  UI --> API_TS --> MAIN
  MSG --- UI
  EXP --- UI
  MAIN --> UP
  MAIN --> ZIP
  MAIN --> MAIL
  UP --> LOAD
  UP --> EXTR
  ZIP --> EXTR
  MAIL <--> AGB
  MAIL -->|clean mail only| LOAD
  MAIL -->|clean mail only| HANDLER --> EXTR
  LOAD --> MAP --> CHAIN --> ADAPT
  EXTR -.->|image| GEM
  MAP -.->|masked samples only| GEM
  LOAD -.->|photo, with consent| GEM
  EXTR --> MATCH
  ADAPT --> MATCH
  MATCH --> REPLY
  REPLY --> MAIN
  MODELS -.-> MATCH
  MAIN --> LINKS
```

Solid arrows are data flow; dotted arrows leave the server (Gemini) or are shared contracts.

## 2. Verification flow

```mermaid
sequenceDiagram
  autonumber
  actor U as User
  participant FE as Frontend
  participant API as main.py
  participant ING as Statement reader
  participant EX as Screenshot reader
  participant M as Matcher
  participant R as Replies

  U->>FE: Upload screenshots + own statement
  FE->>API: POST /statement/upload
  API->>ING: ingest_statement(file, password, allow_vision)
  ING-->>API: rows + meta, or an error code to act on
  Note over FE,API: password / consent / confirm-columns prompts appear here
  FE->>API: POST /claims/upload
  API->>EX: extract_claim(image) for each screenshot
  EX-->>API: Claims (empty fields, never guesses)
  FE->>API: POST /verify (claims, rows, meta)
  API->>M: match_claims(claims, rows, meta)
  M-->>API: Verdicts (status, tier, reasons, confidence)
  API->>R: attach_replies(verdicts)
  R-->>API: Verdicts with suggested_reply
  API-->>FE: verdicts
  FE-->>U: Totals, reasons, EN/HI/TE messages, export
  opt Statement ended before the payment
    U->>FE: Upload newer statement
    FE->>API: re-check
    API->>M: recheck_claims (same matcher)
  end
```

## 3. Statement reader: the model proposes, the arithmetic verifies

```mermaid
flowchart LR
  F["File or pasted text<br/>CSV, XLSX, PDF, text, photo"] --> L["loader.py<br/>decode, delimiter,<br/>find real header row"]
  L --> P1["mapping.py<br/>rule-based proposer"]
  L --> P2["mapping.py<br/>optional model proposer<br/>column names + masked rows only"]
  P1 --> PA["parser.py + normalize.py<br/>apply mapping to every row"]
  P2 --> PA
  PA --> CH{"chain.py<br/>balance = previous<br/>+ credit - debit ?"}
  CH -- holds --> OK["Mapping kept"]
  CH -- breaks --> RT["pipeline.py<br/>retry, flip debit/credit,<br/>then ask the user one question"]
  RT --> PA
  OK --> RF["references.py<br/>12-digit reference + confidence"]
  RF --> CV["coverage.py<br/>period the statement covers"]
  CV --> RP["report.py + adapter.py<br/>StatementRow + StatementMeta"]
```

## 4. Matcher decision ladder

```mermaid
flowchart TD
  C["Claim"] --> R{"High-confidence reference<br/>on a statement row?"}
  R -- yes --> A{"Amount equal and<br/>no field conflicts?"}
  A -- yes --> V["Tier 1: VERIFIED<br/>0.85 - 0.97"]
  A -- no --> X["Tier 4: CONTRADICTED<br/>exact differences listed"]
  R -- no --> S{"Equal amount credit<br/>within 30 min?"}
  S -- yes, name or UPI id fits --> L2["Tier 2: LIKELY MATCH"]
  S -- yes, identity weak --> L3["Tier 3: LIKELY MATCH, low"]
  S -- no --> COV{"Claim safely inside<br/>statement coverage?"}
  COV -- yes --> NF["Tier 5: NOT FOUND"]
  COV -- no --> CV["CAN'T VERIFY YET<br/>follow_up_after set"]
  C -.-> D["Shared reference, identical file,<br/>or corroborated fingerprint"] -.-> DUP["DUPLICATE"]
```

Global rules: one credit supports one claim (Hungarian assignment), only credits count as evidence, tiers 2 and 3 never verify, the same input always gives the same output. Details: [`technical-reference.md`](technical-reference.md).

## 5. Secure email intake

```mermaid
sequenceDiagram
  autonumber
  participant S as Sender
  participant AB as Agentboxd inbox
  participant SV as intake/service.py
  participant PL as Pipeline

  S->>AB: Email + attachment
  AB->>AB: Score spoofing, injection, phishing
  alt Held by Agentboxd
    AB-->>SV: held (content hidden)
    SV->>SV: Record security alert, never open
  else Passed to PayZen
    SV->>AB: Claim message
    SV->>SV: Own policy checks scores and labels
    alt Suspicious
      SV->>SV: Quarantine, attachments not downloaded
    else Clean
      SV->>AB: Download attachments
      SV->>PL: Statement to ingestion, screenshot to extractor
      PL-->>SV: Same pipeline as an upload
    end
  end
  Note over SV: Email text is never given to a model as instructions
```

Design: [`secure-intake.md`](secure-intake.md).

## 6. Deployment

```mermaid
flowchart LR
  B([Browser]) -->|HTTPS| V["Vercel<br/>React + Vite<br/>VITE_API_URL"]
  V -->|HTTPS, CORS allow-list| R["Render<br/>FastAPI + uvicorn<br/>CORS_ORIGINS"]
  R -->|GEMINI_API_KEY| G["Google Gemini"]
  R -->|AGENTBOXD_API_KEY| A["Agentboxd"]
```

Everything is processed in memory; nothing is stored. Setup: [`deployment.md`](deployment.md).

## Components and owners

| Component | Location | Built by |
|---|---|---|
| Claim extractor, normalizers, image fingerprint | `backend/app/services/extractor.py`, `vision_gemini.py` | Alizah |
| Matcher / verdict engine (ladder, one-to-one assignment, duplicates, coverage) | `backend/app/services/matcher.py` | Alizah |
| Reply generator (evidence text, English, 3 tones), re-check, edit hint | `reply_generator.py`, `rechecker.py`, `edit_hint.py` | Alizah |
| Email screenshot handler | `backend/app/services/intake_handler.py` | Alizah |
| Statement ingestion (loader, PDF, vision, mapping, parser, normalize, references, balance chain, coverage, messages, adapter, report) and `services/ingestor.py` | `backend/app/ingestion/` | Zunairah |
| Secure email intake (Agentboxd client, service, router) and WhatsApp ZIP intake | `backend/app/intake/` | Zunairah |
| Payment link and QR prototype | `backend/app/payment_links.py` | Zunairah |
| API and shared contracts (`Claim`, `StatementRow`, `StatementMeta`, `Verdict`) | `backend/app/main.py`, `models.py` | Umaima |
| Web interface (landing, verify flow, results, reason drawer, follow-up list, exports) | `frontend/src/` | Umaima |
| Payer messages in English, Hindi and Telugu | `frontend/src/replies.ts` | Umaima |
| Evaluation data and scripts | `eval/`, `data/synthetic/` | Umaima |
| Ingestion, photo and email evaluations | `tests/ingestion/`, `tests/intake/` | Zunairah |
| Matcher, reply and re-check test suites | `tests/` | Alizah |

## Boundaries

- The extractor is the only component that touches screenshot bytes. It returns a `Claim` and keeps no copy.
- The matcher consumes only structured claims, rows and metadata. No I/O, no clock, no randomness. Replies are not produced here.
- The reply generator reads `Verdict` fields only; `attach_replies` returns copies.
- Re-check is a thin wrapper over the same `match_claims`; there is no second rule set.
- The edit hint has no path into a `Verdict`.
- Ingestion never duplicates matching logic; the matcher never compensates for ingestion behaviour.
- Email text is never given to a model as instructions; held mail is never opened.

## Guiding rule

Never produce a stronger verdict than the evidence supports. A false Verified is worse than a cautious Not found or Can't verify yet.

Field-level contract: [`api-contract.md`](api-contract.md).