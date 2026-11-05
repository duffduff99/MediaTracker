import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useApp } from "../state";
import type { CustomValue, Field, Format } from "../types";

// ------------------------------------------------------------------ colour helpers

export function textOn(hex: string): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex);
  if (!m) return "#ffffff";
  const n = parseInt(m[1], 16);
  const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  const lum = 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
  return lum > 0.35 ? "#18171a" : "#ffffff";
}

// ------------------------------------------------------------------ icons

const paths: Record<string, ReactNode> = {
  barcode: <path d="M3 5v14M7 5v14M10 5v14M14 5v14M17 5v14M21 5v14" />,
  plus: <path d="M12 5v14M5 12h14" />,
  close: <path d="M6 6l12 12M18 6L6 18" />,
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </>
  ),
  moon: <path d="M20 14.5A8 8 0 1 1 9.5 4 6.5 6.5 0 0 0 20 14.5z" />,
  up: <path d="M12 19V5M6 11l6-6 6 6" />,
  down: <path d="M12 5v14M6 13l6 6 6-6" />,
  columns: <path d="M4 5h16v14H4zM9.5 5v14M14.5 5v14" />,
  download: <path d="M12 4v11M7 10l5 5 5-5M5 20h14" />,
};

export function Icon({ name, size = 20 }: { name: keyof typeof paths | string; size?: number }) {
  return (
    <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      {paths[name]}
    </svg>
  );
}

export function TapeLogo({ size = 34 }: { size?: number }) {
  return (
    <svg aria-hidden="true" width={size} height={(size * 30) / 44} viewBox="0 0 44 30" fill="none" strokeWidth="2.6">
      <rect x="2" y="2" width="40" height="26" rx="3" />
      <circle cx="13" cy="15" r="5" />
      <circle cx="31" cy="15" r="5" />
      <path d="M18 15h8" />
    </svg>
  );
}

// ------------------------------------------------------------------ badges

export function FormatBadge({ format, to }: { format?: Format; to?: string }) {
  if (!format) return <span className="badge">?</span>;
  const style = { background: format.color, color: textOn(format.color) };
  const cls = `badge${format.physical ? "" : " digital"}`;
  if (to)
    return (
      <Link to={to} className={cls} style={style}>
        {format.name}
      </Link>
    );
  return (
    <span className={cls} style={style}>
      {format.name}
    </span>
  );
}

/** Condition is an ordinary configurable select field; its options are ordered best → worst. */
export function ConditionSticker({ value, small }: { value?: CustomValue; small?: boolean }) {
  const { meta } = useApp();
  const field = meta?.fields.find((f) => f.key === "condition");
  if (!field || typeof value !== "string" || !value) return null;
  const idx = field.options.indexOf(value);
  const n = field.options.length;
  // first option teal, last red, the ones between mustard then white
  let cls = "c4";
  if (idx === 0) cls = "c0";
  else if (idx === n - 1 && n > 1) cls = "c3";
  else if (idx === 1) cls = "c1";
  else if (idx > 1) cls = "c2";
  return (
    <span className={`sticker ${cls}${small ? " sm" : ""}`} title={`Condition: ${value}`}>
      {value}
    </span>
  );
}

export function formatValue(field: Field, value: CustomValue | undefined): string {
  if (value === undefined || value === null || value === "") return "";
  if (field.type === "boolean") return value ? "Yes" : "";
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}

// ------------------------------------------------------------------ meter

export function Meter({ value, max, segments = 30 }: { value: number; max: number; segments?: number }) {
  const lit = max > 0 ? Math.max(value > 0 ? 1 : 0, Math.round((value / max) * segments)) : 0;
  return (
    <div className="meter" aria-hidden="true">
      {Array.from({ length: segments }, (_, i) => (
        <span key={i} className={i < lit ? "on" : undefined} />
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ modal

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("input, select, textarea, button:not(.icon-btn)")?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      prev?.focus();
    };
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <div className="modal-head">
          <h2 className="card-title" style={{ margin: 0 }}>
            {title}
          </h2>
          <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>
            <Icon name="close" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ toast

const ToastCtx = createContext<(msg: string) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [msg, setMsg] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const show = useCallback((m: string) => {
    setMsg(m);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setMsg(null), 3200);
  }, []);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      {msg && (
        <div className="toast" role="status">
          {msg}
        </div>
      )}
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);

export function ErrorText({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <p className="error" role="alert">
      {error}
    </p>
  );
}

export function dateOnly(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}
