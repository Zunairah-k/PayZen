import { useState } from "react";
import type { Preview } from "../api";

export default function StatementPrompt({
  preview, busy, onPassword, onConsent, onContinue,
}: {
  preview: Preview;
  busy: boolean;
  onPassword: (pw: string) => void;
  onConsent: () => void;
  onContinue: () => void;
}) {
  const [pw, setPw] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [altChosen, setAltChosen] = useState<string | null>(null);
  const p = preview;

  // ---- green tick: statement read and checked ----
  if (p.status === "ok") {
    return (
      <details className="read-ok">
        <summary>✓ {p.headline}</summary>
        <ul>{p.details.map((d, i) => <li key={i}>{d}</li>)}</ul>
        {p.notes.length > 0 && (
          <ul className="notes">{p.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
        )}
      </details>
    );
  }

  // ---- the file could not be read: wording comes from the backend ----
  if (p.status === "failed") {
    return (
      <div className="prompt">
        <strong>{p.headline}</strong>
        {p.details.map((d, i) => <p key={i} className="muted">{d}</p>)}
        {p.action_text && <p className="muted">{p.action_text}</p>}

        {p.needs === "password" && (
          <>
            <input
              type="password"
              autoComplete="off"
              placeholder="PDF password"
              value={pw}
              onChange={(e) => setPw(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && pw && !busy) { onPassword(pw); setPw(""); } }}
            />
            <button className="run" disabled={!pw || busy} onClick={() => { onPassword(pw); setPw(""); }}>
              {busy ? "Unlocking..." : "Unlock and verify"}
            </button>
          </>
        )}

        {p.needs === "consent" && (
          <>
            <label className="consent">
              <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
              I agree to send this statement to an AI vision model so it can be read. It is processed in
              memory and not stored.
            </label>
            <button className="run" disabled={!agreed || busy} onClick={onConsent}>
              {busy ? "Reading..." : "Allow and continue"}
            </button>
          </>
        )}

        {p.needs === "mapping" && (
          <p className="muted small">
            Choosing columns by hand is not available in this version yet. Download the statement again as CSV
            or Excel and upload that.
          </p>
        )}
      </div>
    );
  }

  // ---- "check": show the summary and ask ONE question ----
  const [primary, ...others] = p.actions;
  return (
    <div className="prompt">
      <strong>{p.headline}</strong>
      <ul>{p.details.map((d, i) => <li key={i}>{d}</li>)}</ul>
      {p.notes.length > 0 && <ul className="notes">{p.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
      {p.question && <p><strong>{p.question}</strong></p>}

      <button className="run" disabled={busy} onClick={onContinue}>
        {busy ? "Verifying..." : primary ?? "Looks right"}
      </button>
      {others.map((label) => (
        <button key={label} className="run secondary" disabled={busy} onClick={() => setAltChosen(label)}>
          {label}
        </button>
      ))}
      {altChosen && (
        <p className="muted small">
          "{altChosen}" is not available in this version yet. Download the statement again as CSV or Excel
          with the dates and columns you expect, then upload it.
        </p>
      )}
    </div>
  );
}