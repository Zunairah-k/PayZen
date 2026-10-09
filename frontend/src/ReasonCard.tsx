import { useEffect, useRef, useState } from "react";
import type { Claim, StatementMeta, StatementRow, Verdict } from "./types";
import EditClaim from "./EditClaim";

function fmtDate(iso?: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime())
    ? iso
    : d.toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
}

const isDateOnly = (iso?: string | null) => !!iso && /T00:00(:00)?$/.test(iso);

function fmtRow(iso?: string | null) {
  if (!iso) return "";
  if (isDateOnly(iso)) {
    const d = new Date(iso);
    return isNaN(d.getTime())
      ? iso
      : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) + " (date only)";
  }
  return fmtDate(iso);
}

type Signal = { mark: "ok" | "warn" | "info"; label: string; detail: string };

const words = (s?: string | null) =>
  (s ?? "").toLowerCase().split(/[^a-z0-9]+/).filter((w) => w.length >= 3);

// Computed in the browser from the two records shown; display only, it never changes a verdict.
function buildSignals(status: string, meta?: StatementMeta | null, claim?: Claim, row?: StatementRow): Signal[] {
  if (!claim) return [];
  if (status === "Can't verify yet" && !row) {
    return [{
      mark: "info",
      label: "Coverage",
      detail: `This payment is later than your statement (it ends ${fmtDate(meta?.coverage_end)}). Nothing is wrong; it just can't be checked yet.`,
    }];
  }
  const out: Signal[] = [];
  const narration = String(row?.narration ?? "");

  if (!claim.reference) {
    out.push({ mark: "warn", label: "Reference", detail: "The screenshot had no readable 12-digit reference, so a match cannot rest on it." });
  } else if (!row) {
    out.push({ mark: "warn", label: "Reference", detail: `${claim.reference} is not on the statement.` });
  } else if (narration.includes(claim.reference)) {
    out.push({ mark: "ok", label: "Reference", detail: "Found in the statement line." });
  } else {
    out.push({ mark: "warn", label: "Reference", detail: "The statement line does not contain the screenshot's reference." });
  }

  if (!row) {
    out.push({ mark: "warn", label: "Statement", detail: "No credit on the statement lines up with this claim." });
    return out;
  }

  const a = Number(claim.amount), b = Number(row.credit);
  if (isFinite(a) && isFinite(b)) {
    out.push(
      Math.round(a * 100) === Math.round(b * 100)
        ? { mark: "ok", label: "Amount", detail: `Both say ₹${b}.` }
        : { mark: "warn", label: "Amount", detail: `Screenshot says ₹${a}, statement says ₹${b}.` },
    );
  }

  const cDay = claim.timestamp?.slice(0, 10);
  const rDay = row.datetime?.slice(0, 10);
  if (isDateOnly(row.datetime) && cDay && rDay) {
    out.push(
      cDay === rDay
        ? { mark: "ok", label: "Date", detail: "The statement shows the date only, and it is the same day as the screenshot." }
        : { mark: "warn", label: "Date", detail: `The statement credit is dated ${rDay}, the screenshot ${cDay}.` },
    );
  } else {
    const t1 = claim.timestamp ? new Date(claim.timestamp).getTime() : NaN;
    const t2 = row.datetime ? new Date(row.datetime).getTime() : NaN;
    if (isFinite(t1) && isFinite(t2)) {
      const mins = Math.round(Math.abs(t1 - t2) / 60000);
      const gap = mins < 90 ? `${mins} min` : `${(mins / 60).toFixed(1)} h`;
      out.push({ mark: mins <= 30 ? "ok" : "warn", label: "Time", detail: `The two times are ${gap} apart.` });
    }
  }

  const cw = words(claim.payer_name);
  if (cw.length === 0) {
    out.push({ mark: "info", label: "Payer name", detail: "No payer name could be read from the screenshot." });
  } else {
    const hay = words(narration);
    const shared = cw.filter((w) => hay.includes(w));
    out.push(
      shared.length
        ? { mark: "ok", label: "Payer name", detail: `Shares “${shared[0]}” with the statement line.` }
        : { mark: "warn", label: "Payer name", detail: "No part of the name appears in the statement line (banks often show a UPI ID instead of a name)." },
    );
  }
  return out;
}

// The matcher lists every look-alike screenshot. Collapse those lines into one and swap raw ids for names.
const SIMILAR = /^Image fingerprint resembles .* not treated as a duplicate\.?$/i;
const CLAIM_ID = /claim_[0-9a-f]{6,}/g;

function tidyReasons(reasons: string[], labelOf?: (id: string) => string) {
  let similar = 0;
  const kept: string[] = [];
  for (const r of reasons) {
    if (SIMILAR.test(r.trim())) { similar++; continue; }
    kept.push(labelOf ? r.replace(CLAIM_ID, (id) => labelOf(id)) : r);
  }
  return { kept, similar };
}

const MEANING: Record<string, string> = {
  "Verified": "A credit with the same reference and amount is on your statement, at a matching time.",
  "Likely match": "A credit looks like this payment, but the reference could not be used to confirm it. PayZen never accepts these automatically.",
  "Contradicted": "The reference is on your statement, but something else disagrees with the screenshot.",
  "Not found": "Your statement covers this time and no matching credit is on it.",
  "Duplicate": "The same proof was submitted more than once, so only one claim can own that credit.",
  "Can't verify yet": "Your statement doesn't cover this payment's time, or the screenshot was too unclear to decide.",
};

const NEXT: Record<string, string> = {
  "Verified": "Mark it paid.",
  "Likely match": "Check the transaction ID in your bank app, or ask the payer for the 12-digit reference, then mark it paid.",
  "Contradicted": "Ask the payer to re-check and send the right screenshot or the difference. Use the reply below.",
  "Not found": "Ask for the transaction ID from their bank app. Not finding it is not proof of fraud. Use the reply below.",
  "Duplicate": "Ask the second person for their own transaction details. Use the reply below.",
  "Can't verify yet": "Upload a newer statement and re-check. No action needed from the payer yet.",
};

export default function ReasonCard({
  verdict, claim, row, meta, onEdit, onClose, labelOf,
}: {
  verdict: Verdict;
  claim?: Claim;
  row?: StatementRow;
  meta?: StatementMeta | null;
  onEdit?: (c: Claim) => void;
  onClose: () => void;
  labelOf?: (claimId: string) => string;
}) {
  const [copied, setCopied] = useState(false);
  const ref = useRef<HTMLElement>(null);
  const pending = verdict.status === "Can't verify yet";
  const pct = Math.round((verdict.confidence ?? 0) * 100);
  const diffs = Object.entries(verdict.field_differences ?? {});
  const { kept, similar } = tidyReasons(verdict.reasons ?? [], labelOf);
  const signals = buildSignals(verdict.status, meta, claim, row);

  useEffect(() => {
    ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, []);

  async function copyReply() {
    try {
      await navigator.clipboard.writeText(verdict.suggested_reply ?? "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard blocked */ }
  }

  return (
    <aside className="reason-card" ref={ref}>
      <button className="close" onClick={onClose} aria-label="Close">×</button>
      <h3>{claim?.payer_name ?? verdict.claim_id}</h3>
      <p className="muted">
        {claim ? `₹${claim.amount} · ref ${claim.reference ?? "not visible"}` : ""}
        {verdict.tier ? ` · match tier ${verdict.tier}` : ""}
      </p>

      <div className="conf">
        <span>
          {verdict.status}
          {!pending && ` · ${pct}% `}
          {verdict.status === "Not found" ? "sure it's missing"
            : verdict.status === "Contradicted" ? "sure it conflicts"
            : pending ? "" : "confidence"}
        </span>
        {!pending && <div className="bar"><div className="fill" style={{ width: `${pct}%` }} /></div>}
      </div>

      <h4>Why this verdict</h4>
      <p className="why-lead">{MEANING[verdict.status] ?? ""}</p>
      {kept.length > 0 && <ul>{kept.map((r, i) => <li key={i}>{r}</li>)}</ul>}
      {signals.length > 0 && (
        <ul className="signals" aria-label="Checks">
          {signals.map((s, i) => (
            <li key={i} className={`sig sig-${s.mark}`}>
              <span className="sig-dot" aria-hidden>{s.mark === "ok" ? "✓" : s.mark === "warn" ? "!" : "·"}</span>
              <span><strong>{s.label}.</strong> {s.detail}</span>
            </li>
          ))}
        </ul>
      )}
      {similar > 0 && (
        <p className="muted small">
          Looks visually similar to {similar} other screenshot{similar > 1 ? "s" : ""} (same payment-app layout).
          Their payment details differ, so they are not treated as duplicates.
        </p>
      )}

      <h4>What to do next</h4>
      <p>{NEXT[verdict.status] ?? "Confirm in your bank app."}</p>

      {diffs.length > 0 && (
        <>
          <h4>What differs</h4>
          <ul className="diffs">
            {diffs.map(([k, v]) => (
              <li key={k}><strong>{k}:</strong> {typeof v === "string" ? v : JSON.stringify(v)}</li>
            ))}
          </ul>
        </>
      )}

      {claim && (
        <>
          <h4>Screenshot says</h4>
          <p className="muted">{claim.reference ?? "no reference"} · ₹{claim.amount} · {fmtDate(claim.timestamp)}</p>
        </>
      )}
      <h4>Statement says</h4>
      {row ? (
        <p className="muted">{row.narration} · ₹{row.credit} · {fmtRow(row.datetime)}</p>
      ) : (
        <p className="muted">No matching credit on the statement.</p>
      )}

      {pending && (
        <div className="followup">
          <strong>Can't verify yet</strong>
          {meta && <p>Your statement covers up to {fmtDate(meta.coverage_end)}.</p>}
          {verdict.follow_up_after && <p>Upload a newer statement after {fmtDate(verdict.follow_up_after)}.</p>}
        </div>
      )}

      {claim && onEdit && <EditClaim key={claim.claim_id} claim={claim} onSave={onEdit} />}

      {verdict.suggested_reply && (
        <>
          <h4>Suggested reply</h4>
          <p className="reply">{verdict.suggested_reply}</p>
          <button className="run" onClick={copyReply}>{copied ? "Copied ✓" : "Copy reply"}</button>
        </>
      )}
    </aside>
  );
}