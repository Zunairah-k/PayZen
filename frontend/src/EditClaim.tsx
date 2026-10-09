import { useState } from "react";
import type { Claim } from "./types";

const LOW = 0.7;
type FieldKey = "reference" | "amount" | "payer_name" | "timestamp";
const FIELDS: { key: FieldKey; label: string }[] = [
  { key: "reference", label: "Reference" },
  { key: "amount", label: "Amount" },
  { key: "payer_name", label: "Payer name" },
  { key: "timestamp", label: "Time" },
];

export default function EditClaim({
  claim,
  onSave,
}: {
  claim: Claim;
  onSave: (c: Claim) => void;
}) {
  const [draft, setDraft] = useState<Claim>(claim);
  const conf = (claim.confidence ?? {}) as Record<string, number>;
  const CRITICAL: FieldKey[] = ["reference", "amount", "timestamp"];
  const low = FIELDS.filter((f) => {
    const v = claim[f.key];
    if (v == null || v === "") return CRITICAL.includes(f.key); // payer name absent is fine
      return (conf[f.key] ?? 0) < LOW;
  });
  if (low.length === 0) return null;

  return (
    <div className="edit-claim">
      <h4>Please check these fields</h4>
      <p className="muted">
        Some details could not be read with confidence. Fix anything wrong, then re-verify.
      </p>
      {low.map((f) => (
        <label key={f.key}>
          {f.label}{" "}
          <span className="muted">({Math.round((conf[f.key] ?? 0) * 100)}% sure)</span>
          <input
            value={(draft[f.key] as string | number | null) ?? ""}
            onChange={(e) =>
              setDraft({
                ...draft,
                [f.key]: f.key === "amount" ? Number(e.target.value) : e.target.value || null,
              })
            }
          />
        </label>
      ))}
      <button
        className="run"
        onClick={() =>
          onSave({
            ...draft,
            confidence: {
              ...conf,
              ...Object.fromEntries(low.map((f) => [f.key, 1])),
            },
          })
        }
      >
        Save and re-verify
      </button>
    </div>
  );
}