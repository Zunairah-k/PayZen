import type { Claim, Verdict } from "../types";
import { STATUS_COLORS } from "../statusColors";

interface Props {
  claims: Claim[];
  verdicts: Verdict[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  sourceOf?: (claimId: string) => string;
}

export default function ResultsTable({ claims, verdicts, selectedId, onSelect, sourceOf }: Props) {
  const claimById = new Map(claims.map((c) => [c.claim_id, c]));
  return (
    <table className="results">
      <thead>
        <tr>
          <th>Payer</th>
          {sourceOf && <th>Source</th>}
          <th>Amount</th>
          <th>Reference</th>
          <th>Verdict</th>
          <th>Confidence</th>
        </tr>
      </thead>
      <tbody>
        {verdicts.map((v) => {
          const c = claimById.get(v.claim_id);
          return (
            <tr
              key={v.claim_id}
              className={v.claim_id === selectedId ? "selected" : ""}
              onClick={() => onSelect(v.claim_id)}
            >
              <td>{c?.payer_name ?? c?.source_file ?? v.claim_id}</td>
              {sourceOf && (
                <td>
                  <span className="src-chip">{sourceOf(v.claim_id)}</span>
                </td>
              )}
              <td>{c?.amount != null ? `₹${c.amount}` : "-"}</td>
              <td>{c?.reference ?? "-"}</td>
              <td>
                <span className="chip" style={{ background: STATUS_COLORS[v.status] }}>
                  {v.status}
                </span>
              </td>
              <td>{v.status === "Can't verify yet" ? "n/a" : `${Math.round(v.confidence * 100)}%`}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}