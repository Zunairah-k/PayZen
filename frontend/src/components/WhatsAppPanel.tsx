import { useState } from "react";
import type { Claim } from "../types";

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

type Item = { filename: string; sender?: string | null; when?: string | null; claim: Claim | null; error: string | null };
type Resp = { count: number; claims: Item[]; warnings: string[] };

// Senders in a chat export are usually phone numbers: show only the start.
const mask = (s?: string | null) => (s ? `${s.slice(0, 3)}•••` : "—");
const fmt = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : String(v));

export default function WhatsAppPanel({ onUse }: { onUse: (claims: Claim[]) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resp, setResp] = useState<Resp | null>(null);

  async function read() {
    if (!file) return;
    setBusy(true);
    setError(null);
    setResp(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await fetch(`${BASE}/intake/whatsapp-zip`, { method: "POST", body: fd });
      if (!r.ok) {
        let detail: unknown = "";
        try {
          detail = (await r.json()).detail;
        } catch {
          /* body was not JSON */
        }
        throw new Error(typeof detail === "string" && detail ? detail : `Request failed (${r.status})`);
      }
      setResp(await r.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const usable: Claim[] = (resp?.claims ?? []).filter((i) => i.claim !== null).map((i) => i.claim as Claim);

  return (
    <details className="wa">
      <summary>Have a WhatsApp chat export instead? Upload the .zip</summary>
      <p className="muted small">
        Export the chat with media from WhatsApp and upload the .zip. Pictures in it are read by an AI vision model
        (Google Gemini), so use synthetic or blurred chats only.
      </p>
      <input type="file" accept=".zip" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />{" "}
      <button className="run secondary" disabled={!file || busy} onClick={read}>
        {busy ? "Reading pictures..." : "Read the export"}
      </button>
      {error && <p className="error">{error}</p>}

      {resp && (
        <>
          <p className="muted">
            {resp.count} picture(s) read, {usable.length} usable.
            {resp.warnings.length > 0 && ` ${resp.warnings.join(" ")}`}
          </p>
          {resp.claims.length > 0 && (
            <table>
              <thead>
                <tr><th>Picture</th><th>Sender</th><th>Payer</th><th>Amount</th><th>Reference</th></tr>
              </thead>
              <tbody>
                {resp.claims.map((i, idx) => (
                  <tr key={idx}>
                    <td>{i.filename.slice(0, 32)}</td>
                    <td>{mask(i.sender)}</td>
                    <td>{i.error ? "could not be read" : fmt(i.claim?.payer_name)}</td>
                    <td>{fmt(i.claim?.amount)}</td>
                    <td>{fmt(i.claim?.reference)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {usable.length > 0 && (
            <p>
              <button className="run" onClick={() => onUse(usable)}>
                Use these {usable.length} claims for verification
              </button>
            </p>
          )}
        </>
      )}
    </details>
  );
}