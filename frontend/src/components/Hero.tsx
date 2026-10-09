import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import "./hero.css";

export default function Hero() {
  const stage = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = stage.current;
    if (!el || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const move = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - 0.5;
      const y = (e.clientY - r.top) / r.height - 0.5;
      el.style.setProperty("--ry", `${x * 14}deg`);
      el.style.setProperty("--rx", `${-y * 12}deg`);
    };
    const leave = () => {
      el.style.setProperty("--ry", "0deg");
      el.style.setProperty("--rx", "0deg");
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerleave", leave);
    return () => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerleave", leave);
    };
  }, []);

  return (
    <header className="hx">
      <div className="hx-bg" aria-hidden="true" />
      <nav className="hx-nav">
        <Link className="hx-logo" to="/">PAYZEN</Link>
        <div className="hx-nav-r">
          <a className="hx-navlink" href="#how">How it works</a>
          <a className="hx-navlink" href="#verdicts">Verdicts</a>
          <a className="hx-navlink" href="#tested">Tested</a>
          <Link className="hx-btn hx-btn-sm" to="/verify">Open the app →</Link>
        </div>
      </nav>

      <div className="hx-grid">
        <div className="hx-copy">
          <span className="hx-pill"><i /> Payment proof verifier</span>
          <h1>A screenshot isn't proof. <em>Your statement is.</em></h1>
          <p>
            Check payment screenshots against your own bank statement. Every verdict comes with evidence,
            a confidence level and a polite reply you can send.
          </p>
          <div className="hx-cta">
            <Link className="hx-btn" to="/verify">Verify payments →</Link>
            <a className="hx-link" href="#how">See how it works</a>
          </div>
          <ul className="hx-checks">
            <li>Any statement format</li>
            <li>Evidence for every verdict</li>
            <li>Nothing stored</li>
          </ul>
        </div>

        <div className="hx-stage" ref={stage} aria-hidden="true">
          <div className="hx-scene">
            <div className="hx-panel hx-p3" />
            <div className="hx-panel hx-p2" />
            <div className="hx-panel hx-p1">
              <div className="hx-lines">
                <span className="hx-amount">₹300</span>
                <b /><b /><b />
              </div>
            </div>
            <div className="hx-core">
              <div className="hx-orbit"><b /><b /></div>
              <div className="hx-shield"><span>✓</span></div>
            </div>
          </div>
          <div className="hx-chip hx-c1"><i /> Verified</div>
          <div className="hx-chip hx-c2"><i /> Contradicted</div>
          <div className="hx-chip hx-c3"><i /> Duplicate</div>
        </div>
      </div>

      <section className="hx-feats" id="how">
        <article className="hx-card">
          <h3>Reads any screenshot</h3>
          <p>A vision model reads the amount, time and reference from any payment app. No templates.</p>
          <span className="hx-stat">Any app</span>
        </article>
        <article className="hx-card hx-dark">
          <h3>Matches deterministically</h3>
          <p>Verdicts come from exact, testable rules, not from a model's guess.</p>
          <span className="hx-stat">0 / 45</span>
          <small>seeded fakes marked Verified (synthetic test, screenshot reading simulated)</small>
        </article>
        <article className="hx-card">
          <h3>Explains every verdict</h3>
          <p>Six verdicts, each with reasons, differences and a non-accusatory reply.</p>
          <span className="hx-stat">6 verdicts</span>
        </article>
      </section>
    </header>
  );
}