import type { Claim, Verdict } from "./types";

const esc = (v: unknown) => {
  const s = v === null || v === undefined ? "" : String(v);
  // quote fields with commas, quotes or newlines; neutralise spreadsheet formulas
  const safe = /^[=+\-@]/.test(s) ? `'${s}` : s;
  return /[",\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
};

export function exportReconciliation(claims: Claim[], verdicts: Verdict[]) {
  const header = ["claim_id", "payer", "amount", "reference", "status", "confidence_pct",
                  "matched_row", "reasons", "differences", "follow_up_after", "suggested_reply"];
  const lines = verdicts.map(v => {
    const c = claims.find(x => x.claim_id === v.claim_id);
    return [
      v.claim_id, c?.payer_name, c?.amount, c?.reference, v.status,
      Math.round((v.confidence ?? 0) * 100), v.matched_row_id,
      (v.reasons ?? []).join(" | "),
      Object.entries(v.field_differences ?? {}).map(([k, x]) => `${k}: ${x}`).join(" | "),
      v.follow_up_after, v.suggested_reply,
    ].map(esc).join(",");
  });
  const blob = new Blob(["\ufeff" + [header.join(","), ...lines].join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "payzen_reconciliation.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}