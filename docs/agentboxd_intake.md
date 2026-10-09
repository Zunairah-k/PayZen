# Secure Email Intake (Agentboxd): Team Guide

**Owner:** Zunairah
**Code:** `backend/app/intake/`
**Tests:** `tests/intake/`
**Screenshot integration:** Alizah

**One line:** Payment proofs can arrive by email at a secure inbox. Agentboxd checks messages for spoofing, prompt injection, and phishing; suspicious messages are quarantined, while accepted attachments enter PayZen's existing ingestion pipeline.

## 1. Ownership and implementation status

| Owner        | Responsibility                                                                                                                                   | Status                                         |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------- |
| **Umaima**   | API/frontend integration, secure email intake UI panel, and intake router wiring                                                                 | Coordinate against the existing implementation |
| **Zunairah** | Agentboxd secure inbox, email polling, attachment classification, policy checks, and statement ingestion integration                             | Implemented; see tests and live results below  |
| **Alizah**   | Register the screenshot extractor with Agentboxd intake, route email screenshots through the existing extraction pipeline, and add handler tests | **Implemented and live-tested**                |
| **Everyone** | Configure `AGENTBOXD_API_KEY` in local/deployed environments                                                                                     | Required per environment                       |

## 2. How it works

```text
Email + attachment -> Agentboxd inbox
   (spoofing, injection, phishing and security checks)
   |
   |-- held by Agentboxd
   |      -> never opened by our service -> alert/record
   |
   |-- claimed by our service -> local policy
          |
          |-- suspicious -> quarantined; attachments not downloaded
          |
          |-- accepted
                 |-- statement -> statement ingestion -> matcher
                 |-- screenshot -> registered screenshot handler
                                      -> existing claim extractor
                                      -> claim summary
                                      -> matcher/verification workflow
```

**Security rule:** Email body text is untrusted input, never model instructions. The service uses security assessments and attachment metadata to apply its policy. Accepted does not mean the payment has been verified.

## 3. Setup

1. Create an Agentboxd API key in the Agentboxd dashboard.
2. Store the required keys in `.env` locally. Never commit `.env` or paste its contents into logs or chat.

```dotenv
AGENTBOXD_API_KEY=mr_your_key
GEMINI_API_KEY=your_gemini_key
```

3. Load environment variables into the same PowerShell session used to start the API:

```powershell
Get-Content .env |
    Where-Object { $_ -match '^\s*[^#\s]\S*=' } |
    ForEach-Object {
        $k, $v = $_ -split '=', 2
        Set-Item "Env:$($k.Trim())" $v.Trim()
    }

$env:PYTHONPATH = (Join-Path (Get-Location) "backend")
python -m uvicorn app.main:app --reload
```

4. In Render, configure the required variables in the service's Environment settings.

The inbox used in the live test was `payzen-proofs@homingbox.net`.

| Variable                   | Default                     | Meaning                                               |
| -------------------------- | --------------------------- | ----------------------------------------------------- |
| `AGENTBOXD_API_KEY`        | Required                    | Agentboxd API key                                     |
| `AGENTBOXD_BASE_URL`       | `https://api.agentboxd.com` | Agentboxd API address                                 |
| `AGENTBOXD_INBOX_USERNAME` | `payzen-proofs`             | Inbox username                                        |
| `INTAKE_LLM_POLICY`        | `fallback`                  | Model-use policy for emailed statement column mapping |
| `INTAKE_INJECTION_BLOCK`   | `0.5`                       | Injection-score quarantine threshold                  |
| `INTAKE_PHISHING_BLOCK`    | `0.5`                       | Phishing-score quarantine threshold                   |

The `.env` file is ignored by Git and should remain untracked.

## 4. API (mounted at `/intake`)

All endpoints return JSON.

| Route                  | Purpose                                                         |
| ---------------------- | --------------------------------------------------------------- |
| `GET /intake/status`   | Returns inbox address, inbox ID, message counts and alert count |
| `POST /intake/poll`    | Polls and processes new messages                                |
| `GET /intake/messages` | Returns processed message records, newest first                 |
| `GET /intake/alerts`   | Returns security alerts, newest first                           |

Missing configuration can result in `503`; Agentboxd connectivity errors can result in `502`.

### Message records

A record includes message metadata, status, security assessment, and attachment outcomes.

Possible statuses include:

* `accepted`
* `quarantined`
* `held_by_agentboxd`
* `error`

Held messages do not expose their attachment contents to the service.

### Attachment outcomes

* **Statement:** ingestion status, row count, balance/chain information, mapping confirmation, error details and coverage.
* **Screenshot:** a JSON-friendly handler result when the screenshot handler is registered; an error outcome if processing fails.
* **Ignored file:** marked as ignored.
* **Held or quarantined email:** attachments are not downloaded or processed by our service.

## 5. UI integration

The intake router is mounted in `backend/app/main.py`. The secure intake UI should use the following endpoints:

1. Show the inbox address from `/intake/status` with a copy action and the text "Email payment proofs here".
2. Provide a **Check inbox** action that calls `POST /intake/poll`.
3. Display message records from `/intake/messages`, including sender, status, assessment reasons and attachment outcomes.
4. Display security alerts from `/intake/alerts`.
5. Escape sender and subject text before rendering because both originate outside the application.

Do not represent an accepted email as a verified payment. Payment verification requires the normal claim-matching and statement-verification process.

## 6. Alizah's implementation: screenshot handler

**Status: Implemented and integrated.**

Files changed:

* `backend/app/services/intake_handler.py` — screenshot processing and registration helper.
* `backend/app/main.py` — registers the handler during application startup.
* `tests/test_screenshot_handler.py` — tests for registration, processing, extraction outcomes and failure handling.

The handler uses the existing screenshot extractor rather than introducing a separate verification path. It returns a JSON-friendly claim summary, including extraction information and verification status. It does not mark a payment as verified simply because a screenshot was received or parsed.

The registration helper is:

```python
register_screenshot_handler(service=None)
```

It obtains the intake service when needed and registers `read_screenshot` once per service. Application startup invokes the registration helper, and a warning is logged if registration cannot be completed.

### Important limitation: vision provider configuration

The handler integration and live email routing work, but **a real vision provider is not yet configured in the screenshot extractor**. The live test returned:

* `provider: "none-configured"`
* `extracted: false`
* `claims: 0`
* all extraction confidence values at `0.0`

Therefore, the live test proves screenshot attachment routing and handler execution, **not successful extraction of payment fields from the image**. Configure and test a vision provider before claiming end-to-end screenshot field extraction is complete.

Email statement ingestion remains a separate path and uses the existing statement-ingestion implementation.

## 7. Security policy

The intake service applies policy to the Agentboxd assessment and message metadata.

* **High severity:** quarantine held messages, injection-risk labels, or scores meeting configured thresholds.
* **Medium severity:** quarantine relevant sender-authentication failures or incomplete security checks according to the policy.
* **Otherwise:** accept for the next processing stage.

Attachments from quarantined messages are not downloaded. After processing, messages are acknowledged and labelled according to the service's acceptance or quarantine decision.

An accepted message is not a verified payment. Verification still depends on extraction quality, statement coverage, reference/amount matching and the normal verdict rules.

## 8. Testing and validation

### Targeted tests

The following command was run successfully:

```powershell
python -m pytest tests/test_screenshot_handler.py tests/test_recheck_endpoint.py tests/intake -q
```

**Observed result:** `38 passed, 1 skipped, 3 warnings in 1.67s`.

The warnings included the existing FastAPI startup-event deprecation warning. This targeted run covered the screenshot handler, recheck endpoint and intake tests.

### Live inbox test

The live service was started with the required environment configuration. The following was verified:

* `GET /intake/status` returned `200` and the configured inbox details.
* `POST /intake/poll` successfully processed a synthetic email.
* The message was accepted by the intake policy.
* Its PNG attachment was classified as a screenshot and routed to the registered handler.
* The handler returned a claim summary without falsely marking the payment as verified.
* Actual image-field extraction did not occur because no vision provider was configured.

Earlier held messages were also observed; their attachments were not exposed for processing, consistent with the held-message behavior.

### Recommended commands before release

```powershell
python -m pytest tests/test_screenshot_handler.py tests/test_recheck_endpoint.py tests/intake -q
python -m pytest tests -q
```

Run the full suite before release and record its actual result. Do not reuse an older full-suite count as if it came from the latest run.

## 9. Live results

| Test                             | Observed result                                             |
| -------------------------------- | ----------------------------------------------------------- |
| Intake status                    | `200`; inbox details returned                               |
| Polling                          | Synthetic message processed successfully                    |
| Clean synthetic screenshot email | Accepted; screenshot attachment routed to handler           |
| Screenshot extraction            | No fields extracted; no vision provider configured          |
| Screenshot verification          | Remained `not_verified`                                     |
| Earlier suspicious/held emails   | Held by Agentboxd; attachments not processed by our service |

The live test confirms the email-to-screenshot-handler integration. It does not yet establish that a vision model can extract payment details accurately.

## 10. Troubleshooting

| Symptom                                          | What to check                                                                             |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------- |
| `Set the AGENTBOXD_API_KEY environment variable` | Load `.env` into the same PowerShell session that starts Uvicorn                          |
| `/intake/*` returns `503`                        | Check required environment variables and intake initialization                            |
| Agentboxd returns `401`                          | Check whether the API key is valid or expired; rotate it if necessary                     |
| Nothing arrives after sending mail               | Allow time for delivery and poll again                                                    |
| Screenshot outcome says `none-configured`        | Configure a supported vision provider in the screenshot extractor                         |
| Screenshot has zero extracted fields             | Check provider configuration and extraction logs; do not treat missing fields as verified |
| Statement needs confirmation                     | Confirm the column mapping, as with manual statement upload                               |
| A clean message is quarantined                   | Inspect the assessment reasons and configured thresholds before changing policy           |

## 11. Current limitations

* Intake uses polling rather than push notifications.
* Message records are held in memory and reset when the service restarts.
* Security thresholds require broader evaluation.
* Screenshot routing is integrated, but a vision provider still needs to be configured for real field extraction.
* Successful screenshot extraction does not itself prove a payment; matching and verification remain separate steps.
* Only synthetic payment proofs should be used for development and demos unless production-data handling has been explicitly approved.
* Email replies are not sent by the inbox integration.

## 12. README / Devpost description

> We integrated a secure email intake channel into PayZen using Agentboxd. Incoming payment-proof emails are assessed for spoofing, prompt injection and phishing. Held or quarantined messages are not processed by our service, while accepted statement attachments enter the existing statement-ingestion path and screenshot attachments are routed through the registered screenshot handler. The handler integration has been tested with a live synthetic email; vision-provider configuration is still required for actual screenshot field extraction. Email acceptance and screenshot extraction are not treated as payment verification: claims must go through PayZen's existing matching and verification workflow.
