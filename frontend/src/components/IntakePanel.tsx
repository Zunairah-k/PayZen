import { useEffect, useState } from "react";
import {
  intakeAlerts, intakeMessages, intakePoll, intakeStatus,
  type IntakeAlert, type IntakeAttachment, type IntakeRecord, type IntakeStatus,
} from "../intake";

// Sender and subject come from outside: React escapes them (never use dangerouslySetInnerHTML here),
// and we show only a masked sender because an email address is personal data.
function maskSender(s: string) {
  const m = s.match(/([^<>\s@"]+)@([^<>\s"]+)/);
  return m ? `${m[1].slice(0, 2)}***@${m[2]}` : s.slice(0, 20);
}
const clip = (s: string, n = 80) => (s.length > n ? s.slice(0, n) + "…" : s);

function outcomeText(a: IntakeAttachment): string {
  const o = a.outcome ?? {};
  if (o.ignored) return "ignored (not a statement or screenshot)";
  if (a.kind === "statement") {
    if (o.ok) {
      return `${o.rows} rows read${o.chain === "pass" ? ", balance check passed" : ""}${o.needs_confirmation ? ", needs your confirmation" : ""}`;
    }
    return o.message ?? "could not be read";
  }
  if (o.ok === true) {
    const r = (o as unknown as { result?: { extracted?: boolean; amount?: number | null; reference?: string | null } }).result;
    if (r?.extracted === false) return "screenshot received, but no payment details could be read";
    if (r?.extracted) return `screenshot read: ₹${r.amount ?? "?"}${r.reference ? ` · ref ${r.reference}` : ""} (not verified yet)`;
    return "screenshot read";
  }
  if (o.ok === null) return "screenshot received, not read yet";
  return "could not be processed";
}

const SAMPLE: IntakeRecord[] = [
  { message_id: "ex1", from: "treasurer.demo@example.com", subject: "Fest fee payments, 7 Oct", status: "accepted",
    assessment: { decision: "accepted", severity: "none", reasons: [], scores: { injection: 0.01, phishing: 0.02 } },
    attachments: [
      { filename: "statement.csv", kind: "statement", outcome: { ok: true, rows: 80, chain: "pass" } },
      { filename: "proof.png", kind: "screenshot", outcome: { ok: true } },
    ] },
  { message_id: "ex2", from: "unknown.sender@example.net", subject: "(withheld)", status: "held_by_agentboxd",
    assessment: { decision: "quarantined", severity: "high", reasons: ["held by Agentboxd screening (injection_risk)"] },
    attachments: [] },
  { message_id: "ex3", from: "payments.team@example.org", subject: "Urgent: confirm your account", status: "quarantined",
    assessment: { decision: "quarantined", severity: "medium", reasons: ["sender failed authentication (spf-fail)"] },
    attachments: [] },
];

export default function IntakePanel() {
  const [status, setStatus] = useState<IntakeStatus | null>(null);
  const [records, setRecords] = useState<IntakeRecord[]>([]);
  const [alerts, setAlerts] = useState<IntakeAlert[]>([]);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [example, setExample] = useState(false);
  const [copied, setCopied] = useState(false);

  async function refresh() {
    const [s, m, a] = await Promise.all([intakeStatus(), intakeMessages(), intakeAlerts()]);
    setStatus(s); setRecords(m); setAlerts(a); setUnavailable(null);
  }

  useEffect(() => {
    refresh().catch((e) => setUnavailable(e instanceof Error ? e.message : String(e)));
  }, []);

  async function check() {
    setBusy(true);
    setNote(null);
    try {
      const r = await intakePoll();
      await refresh();
      setNote(`${r.processed} new message(s): ${r.accepted} accepted, ${r.quarantined} blocked.`);
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function copyAddress() {
    try {
      await navigator.clipboard.writeText(status?.address ?? "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard blocked */ }
  }

  const shown = example ? SAMPLE : records;
  const shownAlerts: IntakeAlert[] = example
    ? SAMPLE.filter((r) => r.status !== "accepted").map((r) => ({
        message_id: r.message_id, from: r.from, severity: r.assessment?.severity ?? "high",
        reasons: r.assessment?.reasons ?? [], at: "",
      }))
    : alerts;

  return (
    <section className="intake">
      <h2>Secure email intake</h2>
      <p className="muted">
        Payment proofs can also arrive by email. Every message is screened for spoofing, prompt injection and
        phishing before anything is opened. Suspicious mail is quarantined and its attachments are never read.
      </p>

      {unavailable && !example && (
        <div className="prompt">
          <strong>Email intake isn't available right now</strong>
          <p className="muted small">{unavailable}</p>
          <button className="run secondary" onClick={() => setExample(true)}>Show an example</button>
        </div>
      )}
      {example && <p className="muted">Showing example data, not your inbox.{" "}
        <button className="linklike" onClick={() => setExample(false)}>Back</button></p>}

      {status && !example && (
        <div className="ix-address">
          <span>Email payment proofs to</span> <code>{status.address}</code>{" "}
          <button className="run secondary" onClick={copyAddress}>{copied ? "Copied ✓" : "Copy"}</button>{" "}
          <button className="run" disabled={busy} onClick={check}>{busy ? "Checking..." : "Check inbox"}</button>
          {note && <p className="muted">{note}</p>}
        </div>
      )}

      {shown.length > 0 && (
        <table className="ix-table">
          <thead><tr><th>From</th><th>Subject</th><th>Result</th><th>Details</th></tr></thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.message_id}>
                <td>{maskSender(r.from)}</td>
                <td>{clip(r.subject)}</td>
                <td>
                  <span className={`ix-chip ${r.status === "accepted" ? "ix-ok" : r.status === "error" ? "ix-warn" : "ix-bad"}`}>
                    {r.status === "accepted" ? "Accepted" : r.status === "held_by_agentboxd" ? "Held" : r.status === "error" ? "Error" : "Quarantined"}
                  </span>
                </td>
                <td>
                  {(r.assessment?.reasons ?? []).map((x, i) => <div key={i} className="muted">{clip(x, 120)}</div>)}
                  {r.attachments.map((a, i) => (
                    <div key={i} className="muted">{clip(a.filename, 40)}: {outcomeText(a)}</div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {shownAlerts.length > 0 && (
        <div className="ix-alerts">
          <strong>Security alerts</strong>
          <ul>
            {shownAlerts.map((a, i) => (
              <li key={i}>{maskSender(a.from)}: {clip(a.reasons.join("; "), 140)} ({a.severity})</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}