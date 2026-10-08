# Email intake test: 10 clean and 10 malicious emails

Generated 2026-10-08 by `python -m tests.intake.email_eval score`.

Twenty hand-written synthetic emails were sent from Gmail to the real inbox: 10 normal payment-proof emails (tagged [C01]..[C10]) and 10 malicious ones (tagged [M01]..[M10]): 5 prompt-injection attempts and 5 phishing or impersonation attempts. Mail held by Agentboxd hides its subject, so the blocked counts are derived: stopped = sent minus malicious emails that were accepted. Small sample, one sender.

| Measure | Result |
|---|---|
| emails sent: clean / malicious | 10 / 10 |
| emails processed | 20 of 20 |
| accepted: clean / malicious | 10 / 0 |
| blocked in total (held by Agentboxd / quarantined by our policy) | 10 (10 / 0) |
| errors | 0 |
| malicious emails stopped | 10 of 10 |
| clean emails wrongly blocked | 0 of 10 |
| statements read correctly from accepted clean emails | 3 of 3 |
