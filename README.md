# PayZen

The key insight
Matching a receipt to a payment record is already a standard feature of enterprise expense tools like Fyle/Sage, which match receipts to transactions using real-time card feeds. But in reimbursement fraud, the claimant supplies the statement, so they could forge that too. The trust model is weak. 
intacct

It's much stronger on the receiving side, where the verifier holds the ground truth: their own bank or UPI statement.

The idea: a payment-proof verifier for people who collect money via screenshots
Think college fest treasurers, society maintenance collectors, donation drives, WhatsApp and Instagram sellers, and tuition collectors. Small sellers often get paid through UPI apps and ask the payer for a screenshot to reconcile. 
thejeshgn

Upload a batch of payment screenshots plus your own bank statement (CSV or XLSX first).
A vision model extracts the UPI reference (the 12-digit ID that works as the universal key for matching against bank statements), amount, time, and payee. 
imagetotable
A deterministic matcher compares each claim to your statement and labels it:
Verified: matching credit found.
Contradicted: reference found but amount, date, or payee differs.
Not found: statement covers that time but no such credit exists.
Duplicate: the same reference claimed twice.
Can't verify: statement doesn't cover it, or extraction failed.
Output: a reconciliation sheet, per-claim reasons, ₹ verified versus ₹ at risk, and ready-to-send replies in English, Hindi, or Telugu ("We couldn't find reference X, please share…").
Edit-detection on screenshots stays a low-weight hint, never proof.

Cross-verification

Problem: Real. Police arrested a man for allegedly using doctored UPI screenshots to cheat shopkeepers. Fraudsters also use modified APKs and fake apps that produce fake payment screens. The standard advice is that a screenshot never constitutes proof of payment. 
Fraud Alert: UPI Is Fast & Convenient — but One Careless Tap Can Cost You Dearly +2

Prompt fit: Strong. It's fraud enabled by modern technology (photo editors, fake apps). It recognizes, verifies, and responds. I didn't find evidence that AI specifically is driving UPI screenshot fraud, so don't claim that.
