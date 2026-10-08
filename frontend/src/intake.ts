const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type IntakeAttachment = {
  filename: string; kind: string; size_bytes?: number | null; outcome?: Record<string, any>;
};
export type IntakeRecord = {
  message_id: string; from: string; subject: string; received_at?: string; processed_at?: string;
  status: "accepted" | "quarantined" | "held_by_agentboxd" | "error";
  assessment?: { decision: string; severity: string; reasons: string[]; scores?: Record<string, number>; labels?: string[] };
  attachments: IntakeAttachment[];
  error?: string;
};
export type IntakeAlert = { message_id: string; from: string; severity: string; reasons: string[]; at: string };
export type IntakeStatus = { address: string; inbox_id: string; counts: Record<string, number>; alerts: number };

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, init);
  if (!r.ok) {
    let detail = "";
    try { detail = (await r.json()).detail ?? ""; } catch { /* not JSON */ }
    throw new Error(detail || `Request failed (${r.status})`);
  }
  return r.json();
}

export const intakeStatus = () => j<IntakeStatus>("/intake/status");
export const intakePoll = () =>
  j<{ processed: number; accepted: number; quarantined: number; records: IntakeRecord[] }>("/intake/poll", { method: "POST" });
export const intakeMessages = async () => (await j<{ data: IntakeRecord[] }>("/intake/messages")).data;
export const intakeAlerts = async () => (await j<{ data: IntakeAlert[] }>("/intake/alerts")).data;