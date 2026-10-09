import { useState } from "react";
import type { Claim, StatementMeta, StatementRow, Verdict } from "./types";
import EditClaim from "./EditClaim";

function fmtDate(iso?: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime())
    ? iso
    : d.toLocaleString("en-IN", {
        day: "numeric",
        month: "short",
        year: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
}

export default function ReasonCard({
  verdict,
  claim,
  row,
  meta,
  onEdit,
  onClose,
}: {
  verdict: Verdict;
  claim?: Claim;
  row?: StatementRow;
  meta?: StatementMeta | null;
  onEdit?: (c: Claim) => void;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const pct = Math.round((verdict.confidence ?? 0) * 100);
  const diffs = Object.entries(verdict.field_differences ?? {});

  async function copyReply() {
    try {
      await navigator.clipboard.writeText(verdict.suggested_reply ?? "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked: user can select the text manually */
    }
  }

  return (
    <aside className="reason-card">
      <button className="close" onClick={onClose} aria-label="Close">
        ×
      </button>
      <h3>{claim?.payer_name ?? verdict.claim_id}</h3>
      <p className="muted">
        {claim ? `₹${claim.amount} · ref ${claim.reference ?? "not visible"}` : ""}
        {verdict.tier ? ` · match tier ${verdict.tier}` : ""}
      </p>

      <div className="conf">
        <span>
          {verdict.status} · {pct}%{" "}
          {verdict.status === "Not found" ? "sure it's missing"
          : verdict.status === "Contradicted" ? "sure it conflicts"
          : verdict.status === "Can't verify yet" ? "" : "confidence"}
        </span>
        <div className="bar">
          <div className="fill" style={{ width: `${pct}%` }} />
        </div>
      </div>

      <h4>Why</h4>
      <ul>
        {(verdict.reasons ?? []).map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ul>

      {diffs.length > 0 && (
        <>
          <h4>What differs</h4>
          <ul className="diffs">
            {diffs.map(([k, v]) => (
              <li key={k}>
                <strong>{k}:</strong> {typeof v === "string" ? v : JSON.stringify(v)}
              </li>
            ))}
          </ul>
        </>
      )}

      {claim && (
        <>
        <h4>Screenshot says</h4>
        <p className="muted">
          {claim.reference ?? "no reference"} · ₹{claim.amount} · {fmtDate(claim.timestamp)}
        </p>
        </>
      )}
      <h4>Statement says</h4>
      {row ? (
        <p className="muted">{row.narration} · ₹{row.credit} · {fmtDate(row.datetime)}</p>
      ) : (
      <p className="muted">No matching credit on the statement.</p>
      )}

      {verdict.status === "Can't verify yet" && (
        <div className="followup">
          <strong>Can't verify yet</strong>
          {meta && <p>Your statement covers up to {fmtDate(meta.coverage_end)}.</p>}
          {verdict.follow_up_after && (
            <p>Upload a newer statement after {fmtDate(verdict.follow_up_after)}.</p>
          )}
        </div>
      )}

      {claim && onEdit && (
        <EditClaim key={claim.claim_id} claim={claim} onSave={onEdit} />
      )}

      {verdict.suggested_reply && (
        <>
          <h4>Suggested reply</h4>
          <p className="reply">{verdict.suggested_reply}</p>
          <button className="run" onClick={copyReply}>
            {copied ? "Copied ✓" : "Copy reply"}
          </button>
        </>
      )}
    </aside>
  );
}