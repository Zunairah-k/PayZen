import type { Claim, StatementMeta, StatementRow, Verdict } from "./types";

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

// Shape built by backend/app/ingestion/messages.py build_preview()
export type Preview = {
  status: "ok" | "check" | "failed";
  headline: string;
  details: string[];
  notes: string[];
  question: string | null;
  action_text: string | null;
  actions: string[];
  needs: "password" | "consent" | "mapping" | null;
  error_code: string | null;
  confirm_required: boolean;
};

export type StatementResult = {
  rows: StatementRow[];
  meta: StatementMeta;
  preview: Preview | null;
};

export type IngestOpts = { password?: string; allowVision?: boolean };

const emptyMeta = {
  coverage_start: "", coverage_end: "", mapping_used: {}, balance_chain_result: "",
  parse_confidence: 0, row_count: 0, warnings: [],
} as unknown as StatementMeta;

export async function uploadClaims(files: File[]): Promise<Claim[]> {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  const r = await fetch(`${BASE}/claims/upload`, { method: "POST", body: fd });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function uploadStatement(file: File, opts: IngestOpts = {}): Promise<StatementResult> {
  const fd = new FormData();
  fd.append("file", file);
  if (opts.password) fd.append("password", opts.password);
  fd.append("allow_vision", String(!!opts.allowVision));
  const r = await fetch(`${BASE}/statement/upload`, { method: "POST", body: fd });
  if (!r.ok) throw new Error(await r.text());
  const data = await r.json();
  return {
    rows: data.rows ?? [],
    meta: data.meta ?? emptyMeta,
    preview: data.preview ?? null,
  };
}

export async function verify(claims: Claim[], rows: StatementRow[], meta: StatementMeta): Promise<Verdict[]> {
  const r = await fetch(`${BASE}/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ claims, rows, meta }),
  });
  if (!r.ok) throw new Error(await r.text());
  const data = await r.json();
  return Array.isArray(data) ? data : (data.verdicts ?? []);
}

export async function recheck(
  claims: Claim[], rows: StatementRow[], meta: StatementMeta, previous: Verdict[]
): Promise<Verdict[] | null> {
  const r = await fetch(`${BASE}/recheck`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ claims, rows, meta, previous_verdicts: previous }),
  });
  if (r.status === 404) return null; // endpoint not wired yet
  if (!r.ok) throw new Error(await r.text());
  const data = await r.json();
  return Array.isArray(data) ? data : (data.verdicts ?? []);
}

export async function fetchEmailClaims(): Promise<Claim[]> {
  const r = await fetch(`${BASE}/claims/from-email`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}