import { useState } from "react";

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

type LinkResult = { tag: string; link: string; payer: string; qr_png_base64: string };

const VPA = /^[\w.-]{2,}@[A-Za-z]{2,}$/;

export default function LinksPanel() {
  const [vpa, setVpa] = useState("");
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("300");
  const [label, setLabel] = useState("");
  const [result, setResult] = useState<LinkResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);

  async function create() {
    setError(null);
    const amt = Number(amount);
    if (!VPA.test(vpa.trim())) { setError("Enter your UPI ID, for example yourname@bank."); return; }
    if (!name.trim()) { setError("Enter the name that should appear on the payment."); return; }
    if (!(amt > 0)) { setError("Enter an amount greater than zero."); return; }
    setBusy(true);
    try {
      const r = await fetch(`${BASE}/links/new`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          payee_vpa: vpa.trim(), payee_name: name.trim(), amount: amt, payer_label: label.trim(),
        }),
      });
      if (!r.ok) {
        let detail: unknown = "";
        try { detail = (await r.json()).detail; } catch { /* body was not JSON */ }
        throw new Error(typeof detail === "string" && detail ? detail : `Request failed (${r.status})`);
      }
      setResult(await r.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function copy(text: string, key: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      setTimeout(() => setCopied(null), 1500);
    } catch { /* clipboard blocked */ }
  }

  return (
    <section className="lk">
      <h2>Prevent: a unique payment link for every payer</h2>
      <p className="muted">
        Give each payer their own link or QR. Its short tag travels in the payment note, so it can appear in your
        bank statement and the payment can be matched by that tag alone. This is a prototype: it only works for banks
        that copy the payment note into the statement, and we have not tested it with real bank transfers.
      </p>

      <div className="lk-form">
        <label>Your UPI ID
          <input value={vpa} onChange={(e) => setVpa(e.target.value)} placeholder="technovafest@examplebank" />
        </label>
        <label>Name on the payment
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Technova Fest Fund" />
        </label>
        <label>Amount (₹)
          <input type="number" min="1" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </label>
        <label>Payer (optional label)
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Aarav Patel" />
        </label>
        <button className="run" disabled={busy} onClick={create}>{busy ? "Creating..." : "Create link and QR"}</button>
      </div>

      {error && <p className="error">{error}</p>}

      {result && (
        <div className="lk-result">
          <img src={`data:image/png;base64,${result.qr_png_base64}`} alt={`QR code for ${result.tag}`} width={200} height={200} />
          <div>
            <p>Tag: <code>{result.tag}</code></p>
            <p className="lk-link">{result.link}</p>
            <button className="run secondary" onClick={() => copy(result.link, "link")}>
              {copied === "link" ? "Copied ✓" : "Copy link"}
            </button>{" "}
            <button className="run secondary" onClick={() => copy(result.tag, "tag")}>
              {copied === "tag" ? "Copied ✓" : "Copy tag"}
            </button>{" "}
            <a className="run secondary lk-dl" download={`${result.tag}.png`} href={`data:image/png;base64,${result.qr_png_base64}`}>
              Download QR
            </a>
          </div>
        </div>
      )}
    </section>
  );
}