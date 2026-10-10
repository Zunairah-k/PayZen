import { useState } from "react";
import type { Claim, Verdict } from "../types";
import { STATUS_COLORS } from "../statusColors";
import { LANGS, buildReply, type Lang } from "../replies";

const ORDER = ["Contradicted", "Not found", "Duplicate", "Likely match", "Can't verify yet"];

interface Props {
  claims: Claim[];
  verdicts: Verdict[];
  lang: Lang;
  onLang: (l: Lang) => void;
}

export default function FollowUpList({ claims, verdicts, lang, onLang }: Props) {
  const [copied, setCopied] = useState<string | null>(null);
  const byId = new Map(claims.map((c) => [c.claim_id, c]));

  const items = verdicts
    .filter((v) => v.status !== "Verified")
    .sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status))
    .map((v) => {
      const c = byId.get(v.claim_id);
      return {
        v,
        who: c?.payer_name ?? c?.source_file ?? v.claim_id,
        text: buildReply(v, c, lang),
      };
    });

  if (items.length === 0) return null;
  const urgent = items.filter((i) => i.v.status !== "Can't verify yet").length;

  async function copy(key: string, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      setTimeout(() => setCopied(null), 1500);
    } catch { /* clipboard blocked */ }
  }

  const all = items.map((i) => `${i.who}:\n${i.text}`).join("\n\n");

  return (
    <section className="fu vp-card" aria-label="Replies to send">
      <div className="fu-head">
        <div>
          <h2>Replies to send</h2>
          <p className="muted">
            {urgent} payment(s) need a message{items.length > urgent ? ` (plus ${items.length - urgent} optional)` : ""}.
            Written to the payer, never accusing.
          </p>
        </div>
        <div className="lang-row">
          <span className="muted small">Message language</span>
          <div className="lang-toggle" role="group" aria-label="Reply language">
            {LANGS.map((l) => (
              <button key={l.id} type="button" className={lang === l.id ? "is-on" : ""} onClick={() => onLang(l.id)}>
                {l.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      <ul className="fu-list">
        {items.map((i) => (
          <li key={i.v.claim_id} className="fu-item">
            <div className="fu-top">
              <strong>{i.who}</strong>
              <span className="chip" style={{ background: STATUS_COLORS[i.v.status] }}>{i.v.status}</span>
              {i.v.status === "Can't verify yet" && <span className="fu-optional">optional courtesy message</span>}
            </div>
            <p className="fu-text">{i.text}</p>
            <button type="button" className="run secondary" onClick={() => copy(i.v.claim_id, i.text)}>
              {copied === i.v.claim_id ? "Copied ✓" : "Copy"}
            </button>
          </li>
        ))}
      </ul>

      <button type="button" className="run" onClick={() => copy("all", all)}>
        {copied === "all" ? "Copied ✓" : "Copy all messages"}
      </button>
    </section>
  );
}