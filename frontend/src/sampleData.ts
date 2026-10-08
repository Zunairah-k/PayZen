import type { Claim, StatementMeta, StatementRow, Verdict } from "./types";

export const sampleClaims: Claim[] = [
  { claim_id: "demo_1", source_file: "demo_1.png", payer_name: "Aarav Reddy", amount: 300, timestamp: "2026-10-03T10:12:00", reference: "718420365194", confidence: { reference: 0.97, amount: 0.98, timestamp: 0.95, payer_name: 0.92 } },
  { claim_id: "demo_2", source_file: "demo_2.png", payer_name: "Sana Nair", amount: 500, timestamp: "2026-10-04T20:42:00", reference: null, confidence: { reference: 0, amount: 0.95, timestamp: 0.9, payer_name: 0.9 } },
  { claim_id: "demo_3", source_file: "demo_3.png", payer_name: "Rohan Gupta", amount: 5000, timestamp: "2026-10-05T14:03:00", reference: "284751906233", confidence: { reference: 0.96, amount: 0.55, timestamp: 0.9, payer_name: 0.9 } },
  { claim_id: "demo_4", source_file: "demo_4.png", payer_name: "Meera Iyer", amount: 300, timestamp: "2026-10-05T18:30:00", reference: "530962187745", confidence: { reference: 0.94, amount: 0.97, timestamp: 0.9, payer_name: 0.88 } },
  { claim_id: "demo_5", source_file: "demo_5.png", payer_name: "Karthik Das", amount: 300, timestamp: "2026-10-03T10:12:00", reference: "718420365194", confidence: { reference: 0.95, amount: 0.97, timestamp: 0.9, payer_name: 0.9 } },
  { claim_id: "demo_6", source_file: "demo_6.png", payer_name: "Priya Sharma", amount: 600, timestamp: "2026-10-08T09:40:00", reference: "906315472810", confidence: { reference: 0.93, amount: 0.96, timestamp: 0.9, payer_name: 0.9 } },
];

export const sampleRows: StatementRow[] = [
  { row_id: "r1", datetime: "2026-10-03T10:13:00", narration: "UPI/CR/718420365194/AARAV REDDY/aarav21@examplebank", credit: 300, extracted_reference: "718420365194", name_hint: "AARAV REDDY" },
  { row_id: "r2", datetime: "2026-10-04T20:42:00", narration: "UPI CREDIT SANA NAIR", credit: 500, extracted_reference: null, name_hint: "SANA NAIR" },
  { row_id: "r3", datetime: "2026-10-05T14:05:00", narration: "UPI/CR/284751906233/ROHAN GUPTA", credit: 500, extracted_reference: "284751906233", name_hint: "ROHAN GUPTA" },
];

export const sampleMeta: StatementMeta = {
  coverage_start: "2026-10-01", coverage_end: "2026-10-07",
  mapping_used: {}, balance_chain_result: "passed (demo data)", parse_confidence: 1, row_count: 3, warnings: [],
};

export const sampleVerdicts: Verdict[] = [
  { claim_id: "demo_1", status: "Verified", tier: 1, matched_row_id: "r1", confidence: 0.98, reasons: ["Reference matched exactly", "Amount matched", "Time within window"], field_differences: {}, suggested_reply: "Thanks, we confirmed your payment of Rs. 300 (reference 718420365194)." },
  { claim_id: "demo_2", status: "Likely match", tier: 2, matched_row_id: "r2", confidence: 0.72, reasons: ["No reference in the statement narration", "Amount matched", "Name and time are close"], field_differences: {}, suggested_reply: "We found a payment that looks like yours (Rs. 500 near 8:42 pm). Please share the reference number from your bank app so we can finalise it." },
  { claim_id: "demo_3", status: "Contradicted", tier: 1, matched_row_id: "r3", confidence: 0.91, reasons: ["Reference matches a statement credit", "Amount differs"], field_differences: { amount: "Screenshot says Rs. 5000, statement says Rs. 500" }, suggested_reply: "Reference 284751906233 shows Rs. 500 in our account, but your screenshot shows Rs. 5000. Could you please check and share the correct details?" },
  { claim_id: "demo_4", status: "Not found", confidence: 0.6, reasons: ["Claim time is inside the statement period", "No matching credit found"], field_differences: {}, suggested_reply: "We could not find a credit for reference 530962187745 in our statement. Could you share the transaction details from your bank app?" },
  { claim_id: "demo_5", status: "Duplicate", confidence: 0.9, reasons: ["Same reference 718420365194 was already used by another claim (Aarav Reddy)"], field_differences: {}, suggested_reply: "This payment reference was also submitted for another registration. Please share your own transaction details." },
  { claim_id: "demo_6", status: "Can't verify yet", confidence: 0.5, reasons: ["Claim time is after the end of the statement period"], field_differences: {}, follow_up_after: "2026-10-08T09:40:00", suggested_reply: "Thanks, your details are received. Our statement does not yet cover that time, so we will confirm after the next update." },
];