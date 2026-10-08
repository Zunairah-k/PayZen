# PayZen — Privacy & Security Notes

PayZen is a decision-support tool. It reports evidence and confidence; it does not decide that anyone committed fraud. This document separates what the Alizah-owned code actually does from what still needs doing. It makes no security guarantee.

## IMPLEMENTED (in the Alizah-owned services)
- **No persistence by the services.** Extractor, matcher, reply generator, re-checker and edit hint do not write files, databases or caches. Image bytes are used in memory to compute a hash and read fields.
- **Derived hash, not an image copy.** `image_hash` is a 256-bit fingerprint (or a SHA-256); the image cannot be rebuilt from it.
- **Filename hygiene.** `Claim.source_file` keeps only the base name (no directories).
- **No fabricated data.** Missing values stay `None` with confidence 0.0; with no provider configured the extractor returns nothing; the mock provider labels itself in `extraction_notes`.
- **Safe decoding.** Images that cannot be decoded fall back to a SHA-256 and a note instead of raising; a vision-provider failure is contained and noted without the error message in the claim.
- **No secrets in code.** No API keys, no environment variables read, no network calls.
- **Evidence-based, non-accusatory wording.** Statuses are evidence-based; reply text never uses words such as scam/fraud/fake (tested for every status and tone); duplicate/edit evidence is described as "not proof".
- **Sanitized replies.** User-supplied values echoed into replies have control/bidirectional characters removed and are capped at 80 characters.
- **Visible evidence.** Every verdict carries confidence and reasons; contradictions list exact claim-vs-statement values.
- **Edit hint cannot decide.** It is a separate weak note (max confidence 0.70) with no path into a Verdict.
- **Determinism.** Same input → same output; no clock or randomness.

Caveats of the above: verdict `reasons` and `field_differences` can contain payer names, amounts, references and row ids — treat verdicts as sensitive data. On a vision-provider crash the extractor writes a log entry with a stack trace through Python `logging`; make sure the API layer's logging configuration does not ship these to places where payment data should not go.

## RECOMMENDED / TODO (not implemented by these services; belongs to API / deployment)
- Validate uploads: allow-list types by actually decoding the image, enforce a maximum file size and image count, reject others with a clear message.
- Handle uploads in memory or a temp file deleted after the request; never write them under a web-served directory; no permanent storage without a retention decision.
- Redact logs: no request bodies, names, UPI IDs, references or amounts; no verdict dumps.
- Keep secrets in platform environment variables; never in the repo or the frontend bundle; rotate if exposed.
- HTTPS only, explicit CORS allow-list, rate limiting and (if the demo is public) some form of access control.
- Use synthetic or consented data in demos; never real bank statements or real screenshots in the repo, fixtures or screenshots of the demo.
- Show confidence, reasons and field differences in the UI; never display an individual claim as "fraud" or "fake"; show the edit hint only as a weak note.
- Decide a data-retention and deletion statement before any real users.
- Dependency scanning and pinned versions before production.
