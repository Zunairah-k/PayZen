# Privacy and security

PayZen is decision support: it reports evidence and confidence and never decides that anyone committed fraud. This document states what the system does today. It makes no security guarantee.

## What leaves your machine

| Data | Goes to | When |
|---|---|---|
| Payment screenshots | Google Gemini (to read the text) | Every screenshot; the app asks users to use synthetic or blurred images |
| Statement column names and **masked** sample rows (digits to 9, letters to x) | Google Gemini | Only for the optional column-mapping helper |
| A **picture** of a statement | Google Gemini | Only after the user ticks a consent box |
| Incoming email and attachments | Agentboxd (screening; hosted in the EU) | When the email channel is used; held mail is never opened and its attachments are never downloaded |
| Statement files (CSV, XLSX, text PDF) | Nowhere | Parsed locally by rules and arithmetic |

**Free-tier note:** on the Gemini free tier, Google may use requests to improve its products. That is why the app asks for synthetic or blurred images, and why real statements should never be sent through the model path (picture statements need explicit consent).

## What is stored

Nothing is written to disk. Uploads are processed in memory (email records are held in memory only and reset on restart); a PDF password is used once and not kept. The extractor, matcher, reply generator, re-check and edit hint write no files, databases or caches.

## Implemented safeguards

- **No fabricated data:** missing values stay empty with confidence 0.0.
- **Derived fingerprint, not an image copy:** `image_hash` cannot rebuild the image.
- **Filename hygiene:** only the base name is kept.
- **Safe decoding:** undecodable images fall back to a hash and a note; vision failures are contained and do not leak error text into claims.
- **Non-accusatory wording:** statuses are evidence-based; reply text avoids scam, fraud and fake for every status and tone (tested); duplicate and edit evidence is described as "not proof".
- **Sanitised replies:** control and bidirectional characters removed; echoed values capped at 80 characters.
- **Visible evidence:** every verdict carries confidence and reasons; contradictions list exact differences.
- **Edit hint cannot decide:** capped at 0.70, no path into a verdict.
- **Determinism:** same input, same output.
- **Untrusted email and file text is escaped in the interface** and never given to a model as instructions.
- **WhatsApp ZIP limits:** only real images (file signature), 25 pictures by default and 60 at most, size caps, nothing written to disk, chat text never read by a model.
- **Secrets:** API keys live in environment variables, never in the repo or the frontend bundle.

## Data used in the project

- The repo, tests, demo and video use **synthetic data only**.
- Real-data checks (a real bank PDF and a real payment) were run locally by the team on their own records. Nothing from them is committed or published, and the documentation screenshots of them are redacted.

## Caveats and next steps

- Verdict `reasons` and `field_differences` can contain names, amounts and references: treat them as sensitive and keep them out of logs. A vision-provider crash logs a stack trace through Python `logging`; make sure log shipping does not send it anywhere payment data should not go.
- Before real users: a data-retention and deletion statement, rate limiting and access control for a public demo, dependency scanning and pinned versions.
- **To verify before submitting:** the app enforces upload type and size limits and does not log request bodies. Confirm in `main.py`, or move the item to "next steps".