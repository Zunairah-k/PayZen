import type { Claim, StatementMeta, StatementRow, Verdict } from "./types";

const esc = (s: unknown) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] as string));

const MEANING: Record<string, string> = {
  "Verified": "Matching credit found on the statement.",
  "Likely match": "Looks like a credit on the statement; confirm the reference.",
  "Contradicted": "Reference found, but a detail disagrees with the screenshot.",
  "Not found": "No matching credit in the period the statement covers.",
  "Duplicate": "Same proof submitted more than once.",
  "Can't verify yet": "Later than the statement; re-check with a newer one.",
};

export function printReport(
  claims: Claim[],
  verdicts: Verdict[],
  rows: StatementRow[],
  meta: StatementMeta | null,
  sourceOf: (id: string) => string,
) {
  const byId = new Map(claims.map((c) => [c.claim_id, c]));
  const rowById = new Map(rows.map((r) => [r.row_id, r]));
  const counts: Record<string, number> = {};

  const body = verdicts
    .map((v) => {
      counts[v.status] = (counts[v.status] ?? 0) + 1;
      const c = byId.get(v.claim_id);
      const r = v.matched_row_id ? rowById.get(v.matched_row_id) : undefined;
      return `<tr>
        <td>${esc(c?.payer_name ?? c?.source_file ?? v.claim_id)}</td>
        <td>${esc(sourceOf(v.claim_id))}</td>
        <td>${c?.amount != null ? "₹" + esc(c.amount) : "-"}</td>
        <td>${esc(c?.reference ?? "-")}</td>
        <td><strong>${esc(v.status)}</strong></td>
        <td>${esc(MEANING[v.status] ?? "")}</td>
        <td>${r ? esc(r.narration) : "-"}</td>
      </tr>`;
    })
    .join("");

  const summary = Object.entries(counts)
    .map(([k, n]) => `<span><strong>${esc(k)}</strong>: ${n}</span>`)
    .join("");

  const html = `<!doctype html><html><head><meta charset="utf-8"><title>PayZen reconciliation report</title>
<style>
body{font-family:Arial,sans-serif;color:#14112b;margin:32px}
h1{margin:0 0 4px}
.muted{color:#5b5775;font-size:12px}
.sum span{display:inline-block;margin:8px 16px 0 0;font-size:13px}
table{border-collapse:collapse;width:100%;margin-top:16px;font-size:12px}
th,td{border:1px solid #d8d3f0;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#f3efff}
footer{margin-top:24px;font-size:11px;color:#5b5775}
@media print{body{margin:12mm}}
</style></head><body>
<h1>PayZen reconciliation report</h1>
<div class="muted">Generated ${esc(new Date().toLocaleString("en-IN"))}. Statement coverage: ${esc(meta?.coverage_start ?? "?")} to ${esc(meta?.coverage_end ?? "?")}.</div>
<div class="sum">${summary}</div>
<table><thead><tr><th>Payer</th><th>Source</th><th>Amount</th><th>Reference</th><th>Verdict</th><th>What it means</th><th>Statement line</th></tr></thead><tbody>${body}</tbody></table>
<footer>Decision support. Confirm in your own bank app before acting on high-value payments. A verdict other than Verified is not proof of wrongdoing.</footer>
</body></html>`;

  const w = window.open("", "_blank");
  if (!w) {
    alert("Please allow pop-ups for this site to print the report.");
    return;
  }
  w.document.write(html);
  w.document.close();
  w.focus();
  setTimeout(() => w.print(), 300);
}