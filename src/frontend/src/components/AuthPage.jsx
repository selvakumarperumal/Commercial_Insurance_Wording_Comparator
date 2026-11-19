import { useState } from "react";
import { api } from "../api.js";
import { DocsArt, Logo } from "./Icons.jsx";

export default function AuthPage({ onLogin }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const isSignup = mode === "signup";

  async function submit(event) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (isSignup) await api.signup(email, password);
      const { access_token } = await api.login(email, password);
      onLogin(access_token);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  function switchTo(next) {
    setMode(next);
    setError("");
  }

  return (
    <main className="auth">
      <section className="auth-aside">
        <div className="brand">
          <Logo />
          <span>Wording Comparator</span>
        </div>

        <div className="pitch">
          <h1 className="display">
            Two policy wordings.
            <br />
            <em>One clear comparison.</em>
          </h1>
          <p>
            Upload two commercial insurance wordings and see, subject by subject, which one serves the insured
            better, with the pages behind every verdict.
          </p>
        </div>

        <DocsArt />

        <ul className="points">
          <li>Works with any layout: numbered clauses, plain prose or scanned pages</li>
          <li>A verdict and a reason for every subject</li>
          <li>Page references you can check</li>
        </ul>
      </section>

      <section className="auth-main">
        <form className="auth-form" onSubmit={submit}>
          <div className="brand brand-compact">
            <Logo />
            <span>Wording Comparator</span>
          </div>

          <div className="segmented" role="tablist">
            <button type="button" role="tab" aria-selected={!isSignup} onClick={() => switchTo("login")}>
              Log in
            </button>
            <button type="button" role="tab" aria-selected={isSignup} onClick={() => switchTo("signup")}>
              Sign up
            </button>
          </div>

          <div>
            <h2 className="display">{isSignup ? "Create your account" : "Welcome back"}</h2>
            <p className="muted">
              {isSignup ? "It takes a few seconds, then you can compare." : "Log in to see your comparisons."}
            </p>
          </div>

          <label className="field">
            <span>Email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              required
              autoComplete="email"
            />
          </label>

          <label className="field">
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={isSignup ? "At least 8 characters" : "Your password"}
              required
              minLength={isSignup ? 8 : undefined}
              autoComplete={isSignup ? "new-password" : "current-password"}
            />
          </label>

          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}

          <button className="primary block" disabled={busy}>
            {busy ? "One moment…" : isSignup ? "Create account" : "Log in"}
          </button>
        </form>
      </section>
    </main>
  );
}
