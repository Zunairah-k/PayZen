import { useRef, useState } from "react";
import "./App.css";
import type { Claim, StatementMeta, StatementRow, Verdict } from "./types";
import {
  uploadClaims, uploadStatement, verify, recheck,
  type IngestOpts, type Preview, type StatementResult,
} from "./api";
import UploadPanel from "./components/UploadPanel";
import SummaryBar from "./components/SummaryBar";
import ResultsTable from "./components/ResultsTable";
import StatementPrompt from "./components/StatementPrompt";
import ReasonCard from "./ReasonCard";
import IntakePanel from "./components/IntakePanel";
import { exportReconciliation } from "./exportCsv";
import {
  sampleClaims, sampleRows, sampleMeta, sampleVerdicts,
  sampleNewerRows, sampleNewerMeta, sampleRecheckVerdicts,
} from "./sampleData";

type Change = { claim_id: string; from: string; to: string };

export default function App() {
  const [claimFiles, setClaimFiles] = useState<File[]>([]);
  const [statementFile, setStatementFile] = useState<File | null>(null);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [rows, setRows] = useState<StatementRow[]>([]);
  const [meta, setMeta] = useState<StatementMeta | null>(null);
  const [verdicts, setVerdicts] = useState<Verdict[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isSample, setIsSample] = useState(false);

  // statement preview (green tick / one question / password / consent)
  const [preview, setPreview] = useState<Preview | null>(null);
  const [pending, setPending] = useState<{ claims: Claim[]; s: StatementResult } | null>(null);
  const ingestOpts = useRef<IngestOpts>({});
  // avoid re-extracting screenshots (and re-calling the vision model) when only a password/consent is needed
  const claimCache = useRef<{ key: string; claims: Claim[] } | null>(null);

  // re-check state
  const [newRows, setNewRows] = useState<StatementRow[]>([]);
  const [recheckedIds, setRecheckedIds] = useState<string[]>([]);
  const [changes, setChanges] = useState<Change[]>([]);

  function resetRecheck() {
    setNewRows([]);
    setRecheckedIds([]);
    setChanges([]);
  }

  function pickStatement(f: File) {
    setStatementFile(f);
    ingestOpts.current = {};
    setPreview(null);
    setPending(null);
  }

  function loadSample() {
    setClaims(sampleClaims);
    setRows(sampleRows);
    setMeta(sampleMeta);
    setVerdicts(sampleVerdicts);
    setSelectedId(null);
    setError(null);
    setPreview(null);
    setPending(null);
    setIsSample(true);
    resetRecheck();
  }

  async function finish(c: Claim[], s: StatementResult) {
    const v = await verify(c, s.rows, s.meta);
    setClaims(c);
    setRows(s.rows);
    setMeta(s.meta);
    setVerdicts(v);
    setPending(null);
    ingestOpts.current = {}; // the password is never kept after use
  }

  async function run(extra: IngestOpts = {}) {
    setIsSample(false);
    if (!statementFile || claimFiles.length === 0) return;
    ingestOpts.current = { ...ingestOpts.current, ...extra };
    setLoading(true);
    setError(null);
    setVerdicts([]);
    setSelectedId(null);
    setPending(null);
    resetRecheck();
    try {
      const key = claimFiles.map((f) => `${f.name}:${f.size}:${f.lastModified}`).join("|");
      let c = claimCache.current?.key === key ? claimCache.current.claims : null;
      if (!c) {
        c = await uploadClaims(claimFiles);
        claimCache.current = { key, claims: c };
      }
      const s = await uploadStatement(statementFile, ingestOpts.current);
      setPreview(s.preview);
      if (s.preview?.status === "failed") return;          // prompt shows what is needed
      if (s.preview?.status === "check") {                  // ask ONE question, then continue
        setPending({ claims: c, s });
        return;
      }
      await finish(c, s);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function confirmRead() {
    if (!pending) return;
    setLoading(true);
    setError(null);
    try {
      await finish(pending.claims, pending.s);
      setPreview((p) => (p ? { ...p, status: "ok", question: null, headline: "Statement read (confirmed by you)" } : p));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleEdit(updated: Claim) {
    if (isSample) {
      setError("Editing is shown on demo data only; upload real files to re-verify.");
      return;
    }
    const next = claims.map((c) => (c.claim_id === updated.claim_id ? updated : c));
    setClaims(next);
    try {
      setError(null);
      setVerdicts(await verify(next, rows, meta!));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  // ---- re-check ----
  const pendingIds = verdicts
    .filter((v) => v.status === "Can't verify yet")
    .map((v) => v.claim_id);

  function applyRecheck(fresh: Verdict[], nr: StatementRow[], nm: StatementMeta) {
    const found: Change[] = [];
    const merged = verdicts.map((old) => {
      const nv = fresh.find((v) => v.claim_id === old.claim_id);
      if (!nv) return old;
      if (nv.status !== old.status) {
        found.push({ claim_id: old.claim_id, from: old.status, to: nv.status });
      }
      return nv;
    });
    setVerdicts(merged);
    setNewRows((prev) => [...prev, ...nr]);
    setRecheckedIds((prev) => [...prev, ...fresh.map((v) => v.claim_id)]);
    // keep BOTH statements in the coverage line instead of showing only the newer one
    setMeta({
      ...nm,
      coverage_start: [meta?.coverage_start, nm.coverage_start].filter(Boolean).sort()[0] as string,
      coverage_end: [meta?.coverage_end, nm.coverage_end].filter(Boolean).sort().slice(-1)[0] as string,
      row_count: (meta?.row_count ?? 0) + (nm.row_count ?? 0),
    });
    setChanges(found);
  }

  function recheckSample() {
    applyRecheck(sampleRecheckVerdicts, sampleNewerRows, sampleNewerMeta);
  }

  async function recheckReal(file: File) {
    if (pendingIds.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      const s = await uploadStatement(file);
      if (s.preview?.status === "failed") {
        throw new Error(`${s.preview.headline}. ${s.preview.action_text ?? ""}`.trim());
      }
      // preferred: backend rechecker (protects already-verified credits)
      let fresh = await recheck(claims, s.rows, s.meta, verdicts);
      if (fresh === null) {
        // fallback until /recheck exists: re-run only the pending claims
        const todo = claims.filter((c) => pendingIds.includes(c.claim_id));
        fresh = await verify(todo, s.rows, s.meta);
      }
      applyRecheck(fresh, s.rows, s.meta);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const selectedVerdict = verdicts.find((v) => v.claim_id === selectedId);
  const selectedClaim = claims.find((c) => c.claim_id === selectedId);
  const matchedId = selectedVerdict?.matched_row_id;
  // rechecked claims point at rows from the newer statement
  const selectedRow =
    selectedId && recheckedIds.includes(selectedId)
      ? newRows.find((r) => r.row_id === matchedId) ?? rows.find((r) => r.row_id === matchedId)
      : rows.find((r) => r.row_id === matchedId);

  const nameOf = (id: string) => claims.find((c) => c.claim_id === id)?.payer_name ?? id;

  return (
    <div className="app">
      <header>
        <h1>PayZen</h1>
        <p>Check payment screenshots against your own bank statement.</p>
      </header>

      <UploadPanel
        claimFiles={claimFiles}
        statementFile={statementFile}
        onClaimFiles={setClaimFiles}
        onStatementFile={pickStatement}
      />

      <button
        className="run"
        disabled={loading || !statementFile || claimFiles.length === 0}
        onClick={() => run()}
      >
        {loading ? "Verifying..." : "Verify payments"}
      </button>
      <button className="run secondary" onClick={loadSample}>
        Try sample data
      </button>
      {verdicts.length > 0 && (
        <button className="run secondary" onClick={() => exportReconciliation(claims, verdicts)}>
          Export CSV
        </button>
      )}

      {error && <p className="error">{error}</p>}
      {isSample && <p className="muted">Showing built-in demo data, not your files.</p>}

      {preview && (
        <StatementPrompt
          preview={preview}
          busy={loading}
          onPassword={(pw) => run({ password: pw })}
          onConsent={() => run({ allowVision: true })}
          onContinue={confirmRead}
        />
      )}

      {meta && (
        <p className="muted">
          Statement understood: {meta.row_count ?? 0} rows, {meta.coverage_start ?? "?"} to{" "}
          {meta.coverage_end ?? "?"}, balance check: {meta.balance_chain_result ?? "n/a"}
        </p>
      )}

      {changes.length > 0 && (
        <div className="changes">
          <strong>Re-check complete. {changes.length} claim(s) updated:</strong>
          <ul>
            {changes.map((c) => (
              <li key={c.claim_id}>
                {nameOf(c.claim_id)}: {c.from} → <strong>{c.to}</strong>
              </li>
            ))}
          </ul>
        </div>
      )}

      {verdicts.length > 0 && (
        <>
          <SummaryBar claims={claims} verdicts={verdicts} />

          {pendingIds.length > 0 && (
            <div className="recheck">
              <strong>{pendingIds.length} payment(s) can't be verified yet.</strong>
              <p className="muted">
                Their time is after your statement ends. Upload a newer statement and only these
                will be checked again.
              </p>
              {isSample ? (
                <button className="run secondary" onClick={recheckSample}>
                  Re-check with sample newer statement
                </button>
              ) : (
                <label className="recheck-upload">
                  Upload newer statement:{" "}
                  <input
                    type="file"
                    disabled={loading}
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) recheckReal(f);
                      e.target.value = "";
                    }}
                  />
                </label>
              )}
            </div>
          )}

          <ResultsTable
            claims={claims}
            verdicts={verdicts}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </>
      )}

      {selectedVerdict && (
        <ReasonCard
          verdict={selectedVerdict}
          claim={selectedClaim}
          row={selectedRow}
          meta={meta}
          onEdit={handleEdit}
          onClose={() => setSelectedId(null)}
        />
      )}
      <IntakePanel />
      
      <footer className="muted footer">
        Decision support. Confirm in your own bank app before acting on high-value payments.
        Files are processed in memory and not stored.
      </footer>
    </div>
  );
}