import { useState } from "react";
import "./App.css";
import type { Claim, StatementMeta, StatementRow, Verdict } from "./types";
import { uploadClaims, uploadStatement, verify } from "./api";
import UploadPanel from "./components/UploadPanel";
import SummaryBar from "./components/SummaryBar";
import ResultsTable from "./components/ResultsTable";
import ReasonDrawer from "./components/ReasonDrawer";

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

  async function run() {
    if (!statementFile || claimFiles.length === 0) return;
    setLoading(true);
    setError(null);
    setVerdicts([]);
    setSelectedId(null);
    try {
      const c = await uploadClaims(claimFiles);
      const s = await uploadStatement(statementFile);
      const v = await verify(c, s.rows, s.meta);
      setClaims(c);
      setRows(s.rows);
      setMeta(s.meta);
      setVerdicts(v);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const selectedVerdict = verdicts.find((v) => v.claim_id === selectedId);
  const selectedClaim = claims.find((c) => c.claim_id === selectedId);
  const selectedRow = rows.find((r) => r.row_id === selectedVerdict?.matched_row_id);

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
        onStatementFile={setStatementFile}
      />

      <button className="run" disabled={loading || !statementFile || claimFiles.length === 0} onClick={run}>
        {loading ? "Verifying..." : "Verify payments"}
      </button>
      {error && <p className="error">{error}</p>}

      {meta && (
        <p className="muted">
          Statement understood: {meta.row_count ?? 0} rows, {meta.coverage_start ?? "?"} to {meta.coverage_end ?? "?"}, balance check: {meta.balance_chain_result ?? "n/a"}
        </p>
      )}

      {verdicts.length > 0 && (
        <>
          <SummaryBar claims={claims} verdicts={verdicts} />
          <ResultsTable claims={claims} verdicts={verdicts} selectedId={selectedId} onSelect={setSelectedId} />
        </>
      )}

      {selectedVerdict && (
        <ReasonDrawer claim={selectedClaim} verdict={selectedVerdict} row={selectedRow} onClose={() => setSelectedId(null)} />
      )}
    </div>
  );
}