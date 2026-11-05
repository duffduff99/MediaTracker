import { useState, type FormEvent, type ReactNode } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { api } from "../api";
import { applyTheme, useApp } from "../state";
import { Scanner } from "./Scanner";
import { Icon, TapeLogo } from "./ui";

export function Layout() {
  const { user, setUser, savePrefs, can } = useApp();
  const navigate = useNavigate();
  const theme = user?.prefs.theme ?? "system";
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const effective = theme === "system" ? (prefersDark ? "dark" : "light") : theme;

  const cycleTheme = () => {
    const next = effective === "dark" ? "light" : "dark";
    applyTheme(next);
    savePrefs({ theme: next }).catch(() => {});
  };

  const logout = async () => {
    await api.post("/api/auth/logout").catch(() => {});
    setUser(null);
    navigate("/");
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="brand" aria-label="MediaTracker home">
            <TapeLogo />
            <span className="brand-name">MediaTracker</span>
          </Link>
          <nav className="nav" aria-label="Main">
            <NavLink to="/" end>Overview</NavLink>
            <NavLink to="/search">Search</NavLink>
            <NavLink to="/boxsets">Box sets</NavLink>
            <NavLink to="/wishlist">Wish list</NavLink>
            <NavLink to="/settings">Settings</NavLink>
          </nav>
          <div className="spacer" />
          <div className="user-menu">
            {can("editor") && (
              <Link to="/items/new" className="btn sm accent hide-sm">
                <Icon name="plus" size={16} /> Add
              </Link>
            )}
            <span className="hide-sm small muted">{user?.display_name}</span>
            <span className="role-tag hide-sm">{user?.role}</span>
            <button type="button" className="icon-btn" onClick={cycleTheme} aria-label="Switch light/dark mode" title="Light/dark mode">
              <Icon name={effective === "dark" ? "sun" : "moon"} />
            </button>
            <button type="button" className="btn sm ghost hide-sm" onClick={logout}>
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="main" id="main">
        <Outlet />
      </main>
      <nav className="bottom-nav" aria-label="Main (mobile)">
        <NavLink to="/" end>Home</NavLink>
        <NavLink to="/search">Search</NavLink>
        {can("editor") ? <NavLink to="/items/new">Add</NavLink> : <NavLink to="/boxsets">Sets</NavLink>}
        <NavLink to="/more">More</NavLink>
      </nav>
    </div>
  );
}

/** The amber "display window" search box with a scan button. */
export function SearchBar({
  value,
  onChange,
  onSubmit,
  onScan,
  autoFocus,
  extra,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit?: (v: string) => void;
  onScan: (code: string) => void;
  autoFocus?: boolean;
  extra?: ReactNode;
}) {
  const [scanning, setScanning] = useState(false);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit?.(value);
    (document.activeElement as HTMLElement | null)?.blur?.();
  };
  return (
    <form className="vfd" role="search" onSubmit={submit}>
      <div className="vfd-field">
        <label htmlFor="q">Do I already own it?</label>
        <input
          id="q"
          type="search"
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          enterKeyHint="search"
          placeholder="TITLE, ARTIST OR BARCODE_"
          value={value}
          autoFocus={autoFocus}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
      <button type="button" className="btn accent lg" onClick={() => setScanning(true)}>
        <Icon name="barcode" /> Scan
      </button>
      {extra}
      {scanning && (
        <Scanner
          onClose={() => setScanning(false)}
          onDetected={(code) => {
            setScanning(false);
            onScan(code);
          }}
        />
      )}
    </form>
  );
}
