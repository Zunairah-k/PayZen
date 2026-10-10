import { Link } from "react-router-dom";
import Hero from "../components/Hero";
import "./LandingPage.css";

const STEPS = [
  {
    title: "Add the screenshots",
    text: "Drop what payers sent you, or upload a WhatsApp chat export. Any payment app, any layout.",
  },
  {
    title: "Add your bank statement",
    text: "CSV, XLSX, PDF, pasted text or even a photo. We find the columns, dates and references ourselves.",
  },
  {
    title: "Read the verdicts",
    text: "Each payment gets a verdict, the evidence behind it, and a polite reply you can copy.",
  },
];

const VERDICTS: { name: string; color: string; text: string }[] = [
  { name: "Verified", color: "#1f8a4c", text: "A credit in your statement matches the amount, time and reference." },
  { name: "Likely match", color: "#0e7490", text: "Amount, time and payer line up, but the statement has no reference to confirm it." },
  { name: "Contradicted", color: "#d97706", text: "A matching credit exists, but a detail such as the amount or payer disagrees." },
  { name: "Not found", color: "#c0392b", text: "Nothing in your statement matches this payment." },
  { name: "Duplicate", color: "#6b4fd8", text: "The same reference or image was already used for another claim." },
  { name: "Can't verify yet", color: "#6b7280", text: "The payment is after your statement ends. Upload a newer one to re-check." },
];

// Numbers come from eval/results/results.md, docs/email_eval_results.md and docs/photo_degradation_results.md.
// Update here if the evaluation is re-run.
const TESTED = [
  { big: "0 / 45", label: "seeded fakes marked Verified, on every one of 5 statement layouts (matching rules, simulated reading)" },
  { big: "0 / 11", label: "fakes marked Verified when the AI read real screenshots, in each of 4 image conditions" },
  { big: "27 / 27", label: "amounts, references and times read correctly, including resized and simulated-photo screenshots" },
  { big: "17 / 17", label: "statement layouts read correctly; balance check passed on 16 (one has no balance column)" },
  { big: "10 / 10", label: "malicious emails stopped, with 0 of 10 normal emails blocked" },
  { big: "642", label: "automated tests passing" },
];

export default function LandingPage() {
  return (
    <div className="lp">
      <Hero />

      <section className="lp-sec" aria-labelledby="lp-how">
        <div className="lp-head">
          <h2 id="lp-how">From a pile of screenshots to a verified list</h2>
          <p>
            For clubs, fests, tuition teachers and small sellers who collect money on plain UPI and get
            screenshots as proof. The proof that counts is the one in your own bank statement.
          </p>
        </div>
        <ol className="lp-steps">
          {STEPS.map((s, i) => (
            <li key={s.title} className="lp-step">
              <span className="lp-num">{i + 1}</span>
              <h3>{s.title}</h3>
              <p>{s.text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="lp-sec" id="verdicts" aria-labelledby="lp-verdicts">
        <div className="lp-head">
          <h2 id="lp-verdicts">Six verdicts, never an accusation</h2>
          <p>
            We say "Not found", not "fake". Every verdict lists its reasons and the differences it saw, so you
            decide what to do next.
          </p>
        </div>
        <div className="lp-verdicts">
          {VERDICTS.map((v) => (
            <article key={v.name} className="lp-verdict">
              <span className="lp-vchip" style={{ background: v.color }}>{v.name}</span>
              <p>{v.text}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="lp-sec" id="tested" aria-labelledby="lp-tested">
        <div className="lp-dark">
          <div className="lp-dark-copy">
            <h2 id="lp-tested">Tested, with the limits stated</h2>
            <p>
              Results on synthetic data we generated. The matching rules were measured on 100 labelled claims
              with the screenshot-reading step simulated, and the real screenshot reader was measured on a
              27-claim sample in four image conditions. We checked one real GPay ₹1 payment end to end against a
              statement built to match it; we have not tested real bank exports. Photographed statements are the
              weak spot: in our test only 1 of 3 tilted, blurred photos was read with the right number of rows,
              which is why every photo asks you to check the dates.
            </p>
          </div>
          <dl className="lp-stats">
            {TESTED.map((t) => (
              <div key={t.big}>
                <dt>{t.big}</dt>
                <dd>{t.label}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <section className="lp-sec lp-two" aria-labelledby="lp-privacy">
        <article className="lp-card">
          <h3 id="lp-privacy">Your statement stays yours</h3>
          <p>
            Statements are processed in memory and never stored. Pictures sent to the vision model leave our
            server, so the app asks first and tells you to use blurred or synthetic samples when you try it.
          </p>
        </article>
        <article className="lp-card">
          <h3>Prevention, not only checking</h3>
          <p>
            Give each payer a unique link or QR with a short tag in the payment note, so their payment can be
            matched by the tag alone. It is a prototype and only works for banks that copy the note into the
            statement.
          </p>
        </article>
      </section>

      <section className="lp-cta">
        <div>
          <h2>Check the next payment before you trust it.</h2>
          <p>Try it with the built-in sample, no upload needed.</p>
        </div>
        <Link className="hx-btn" to="/verify">Open the app →</Link>
      </section>

      <footer className="lp-foot">
        <span className="hx-logo">PAYZEN</span>
        <span>Decision support. Confirm in your own bank app before acting on high-value payments.</span>
      </footer>
    </div>
  );
}