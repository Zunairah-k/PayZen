import type { Claim, StatementMeta, StatementRow, Verdict } from "./types";

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export async function uploadClaims(files: File[]): Promise<Claim[]> {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  const r = await fetch(`${BASE}/claims/upload`, { method: "POST", body: fd });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function uploadStatement(file: File): Promise<{ rows: StatementRow[]; meta: StatementMeta }> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`${BASE}/statement/upload`, { method: "POST", body: fd });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function verify(claims: Claim[], rows: StatementRow[], meta: StatementMeta): Promise<Verdict[]> {
  const r = await fetch(`${BASE}/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ claims, rows, meta }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}