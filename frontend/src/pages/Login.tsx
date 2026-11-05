import { useState, type FormEvent } from "react";
import { api } from "../api";
import { ErrorText, TapeLogo } from "../components/ui";
import { applyTheme, useApp } from "../state";
import type { User } from "../types";

export function Login() {
  const { setUser, refreshMeta } = useApp();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const u = await api.post<User>("/api/auth/login", { username, password });
      applyTheme(u.prefs.theme);
      setUser(u);
      await refreshMeta();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <form className="login card" onSubmit={submit}>
        <div className="brand" style={{ justifyContent: "center", padding: "6px 0" }}>
          <TapeLogo size={40} />
          <span className="brand-name" style={{ fontSize: 26 }}>
            MediaTracker
          </span>
        </div>
        <div className="vfd" style={{ justifyContent: "center" }}>
          <span className="vfd-readout">PLEASE SIGN IN_</span>
        </div>
        <div className="field">
          <label htmlFor="username">Username</label>
          <input id="username" className="input" autoComplete="username" autoCapitalize="none" value={username} onChange={(e) => setUsername(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="password">Password</label>
          <input id="password" className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </div>
        <ErrorText error={error} />
        <button className="btn primary lg" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
