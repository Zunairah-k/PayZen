import type { Claim, StatementRow, Verdict } from "../types";
import { STATUS_COLORS } from "../statusColors";

interface Props {
  claim?: Claim;
  verdict: Verdict;
  row?: StatementRow;
  onClose: () => void;
}

const show = (v: unknown) => (v === null || v === undefined || v === "" ? "-" : String(v));

export default function ReasonDrawer({ claim, verdict, row, onClose }: Props) {
  const compare = [
    ["Reference", claim?.reference, row?.extracted_reference],
    ["Amount", claim?.amount, row?.credit],
    ["Time", claim?.timestamp, row?.datetime],
    ["Name", claim?.payer_name, row?.name_hint],
  ];
  return (
    <aside className="drawer">
      <button className="close" onClick={onClose}>Close</button>
      <h3>{claim?.payer_name ?? verdict.claim_id}</h3>
      <span className="chip" style={{ background: STATUS_COLORS[verdict.status] }}>{verdict.status}</span>
      <p className="muted">Confidence {Math.round(verdict.confidence * 100)}%{verdict.tier ? ` | match tier ${verdict.tier}` : ""}</p>

      <h4>Why</h4>
      <ul>
        {verdict.reasons.map((r, i) => <li key={i}>{r}</li>)}
      </ul>

      <h4>Screenshot says vs statement says</h4>
      <table className="compare">
        <thead><tr><th></th><th>Screenshot</th><th>Statement</th></tr></thead>
        <tbody>
          {compare.map(([label, a, b]) => {
            const differs = a != null && b != null && String(a) !== String(b);
            return (
              <tr key={String(label)} className={differs ? "differs" : ""}>
                <td>{String(label)}</td>
                <td>{show(a)}</td>
                <td>{show(b)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {verdict.suggested_reply && (
        <>
          <h4>Suggested reply</h4>
          <p className="reply">{verdict.suggested_reply}</p>
        </>
      )}
      <p className="disclaimer">Decision support. Confirm in your own bank app before acting on high-value payments.</p>
    </aside>
  );
}