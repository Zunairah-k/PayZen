import type { Claim, Verdict } from "../types";
import { STATUS_COLORS } from "../statusColors";

interface Props {
  claims: Claim[];
  verdicts: Verdict[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export default function ResultsTable({ claims, verdicts, selectedId, onSelect }: Props) {
  const claimById = new Map(claims.map((c) => [c.claim_id, c]));
  return (
    <table className="results">
      <thead>
        <tr>
          <th>Payer</th>
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
            <tr key={v.claim_id} className={v.claim_id === selectedId ? "selected" : ""} onClick={() => onSelect(v.claim_id)}>
              <td>{c?.payer_name ?? c?.source_file ?? v.claim_id}</td>
              <td>{c?.amount != null ? `₹${c.amount}` : "-"}</td>
              <td>{c?.reference ?? "-"}</td>
              <td>
                <span className="chip" style={{ background: STATUS_COLORS[v.status] }}>{v.status}</span>
              </td>
              <td>{Math.round(v.confidence * 100)}%</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}