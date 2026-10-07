import type { Claim, Status, Verdict } from "../types";
import { STATUS_COLORS, STATUS_ORDER } from "../statusColors";

const money = (n: number) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(n);

interface Props {
  claims: Claim[];
  verdicts: Verdict[];
}

export default function SummaryBar({ claims, verdicts }: Props) {
  const claimById = new Map(claims.map((c) => [c.claim_id, c]));
  const sum = (statuses: Status[]) =>
    verdicts
      .filter((v) => statuses.includes(v.status))
      .reduce((t, v) => t + (claimById.get(v.claim_id)?.amount ?? 0), 0);
  const count = (s: Status) => verdicts.filter((v) => v.status === s).length;

  const cards = [
    { label: "Verified", value: money(sum(["Verified"])), color: STATUS_COLORS["Verified"] },
    { label: "Likely", value: money(sum(["Likely match"])), color: STATUS_COLORS["Likely match"] },
    { label: "At risk", value: money(sum(["Contradicted", "Not found", "Duplicate"])), color: STATUS_COLORS["Not found"] },
    { label: "Pending", value: money(sum(["Can't verify yet"])), color: STATUS_COLORS["Can't verify yet"] },
  ];

  return (
    <div>
      <div className="money-cards">
        {cards.map((c) => (
          <div key={c.label} className="money-card" style={{ borderTopColor: c.color }}>
            <span>{c.label}</span>
            <strong>{c.value}</strong>
          </div>
        ))}
      </div>
      <div className="count-chips">
        {STATUS_ORDER.map((s) => (
          <span key={s} className="chip" style={{ background: STATUS_COLORS[s] }}>
            {s}: {count(s)}
          </span>
        ))}
      </div>
    </div>
  );
}