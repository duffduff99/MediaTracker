import { useApp } from "../state";
import type { Field, LookupAttempt, LookupCandidate, LookupResult, TitleHit } from "../types";
import { Icon, formatValue } from "./ui";

const STATUS: Record<LookupAttempt["status"], string> = {
  found: "found",
  not_found: "not found",
  skipped: "skipped",
  rate_limited: "limit reached",
  unreachable: "couldn't connect",
  auth: "key rejected",
  error: "error",
};

export function attemptsSummary(attempts: LookupAttempt[]): string {
  return attempts.map((a) => `${a.source}: ${STATUS[a.status] ?? a.status}${a.cached ? " (saved result)" : ""}`).join(" · ");
}

function fieldsLine(c: LookupCandidate, fields: Field[]): string {
  return Object.entries(c.custom)
    .map(([k, v]) => {
      const f = fields.find((x) => x.key === k);
      return f ? `${f.label}: ${formatValue(f, v) || "Yes"}` : "";
    })
    .filter(Boolean)
    .join(" · ");
}

/** Shows what a barcode lookup found and lets the person apply it to the form. */
export function LookupPanel({
  result,
  loading,
  error,
  formatId,
  onUse,
  onLink,
  onDismiss,
  onRetry,
}: {
  result: LookupResult | null;
  loading: boolean;
  error: string | null;
  formatId: number | null;
  onUse?: (c: LookupCandidate) => void;
  onLink?: (t: TitleHit, c: LookupCandidate | null) => void;
  onDismiss?: () => void;
  onRetry?: () => void;
}) {
  const { fieldsFor } = useApp();
  const fields = formatId ? fieldsFor([formatId]) : [];
  if (loading) {
    return (
      <div className="notice lookup" role="status">
        <span className="status-line">LOOKING UP BARCODE…</span>
      </div>
    );
  }
  if (error) {
    return (
      <div className="notice warn lookup" role="alert">
        <div className="row">
          <strong>Lookup failed:</strong> {error}
          <div className="spacer" />
          {onDismiss && (
            <button type="button" className="icon-btn" aria-label="Dismiss" onClick={onDismiss}>
              <Icon name="close" size={16} />
            </button>
          )}
        </div>
      </div>
    );
  }
  if (!result) return null;
  const best = result.suggestion;
  const others = result.candidates.slice(1);
  const failed = result.attempts.filter((a) => ["rate_limited", "unreachable", "auth", "error"].includes(a.status));

  return (
    <div className={`notice lookup${best ? "" : " warn"}`} role="status" aria-live="polite">
      <div className="row" style={{ alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 6 }}>
          {best ? (
            <>
              <span className="label-caps">Found on {best.source}</span>
              <span style={{ fontWeight: 800, fontStretch: "110%", fontSize: 19 }}>
                {best.title}
                {best.year ? ` (${best.year})` : ""}
              </span>
              {best.artist && <span>{best.artist}</span>}
              {best.detail && <span className="small muted">{best.detail}</span>}
              {fieldsLine(best, fields) && <span className="small">{fieldsLine(best, fields)}</span>}
            </>
          ) : (
            <>
              <strong>Nothing found for {result.barcode}.</strong>
              <span className="small muted">You can still fill the form in by hand.</span>
            </>
          )}
          {result.warnings.map((w) => (
            <span key={w} className="small" style={{ fontWeight: 700 }}>
              ⚠ {w}
            </span>
          ))}
          {failed.map((a) => (
            <span key={a.source} className="small error">
              {a.source}: {a.message}
            </span>
          ))}
        </div>
        {onDismiss && (
          <button type="button" className="icon-btn" aria-label="Dismiss lookup result" onClick={onDismiss}>
            <Icon name="close" size={16} />
          </button>
        )}
      </div>

      {(onUse || onLink) && (
        <div className="row">
          {result.existing_titles.length > 0 && onLink
            ? result.existing_titles.map((t) => (
                <button key={t.id} type="button" className="btn primary sm wrap" onClick={() => onLink(t, best)}>
                  Link to your “{t.name}”{t.year ? ` (${t.year})` : ""} · you own {t.formats.join(", ")}
                </button>
              ))
            : null}
          {best && onUse && (
            <button type="button" className={`btn sm${result.existing_titles.length ? "" : " primary"}`} onClick={() => onUse(best)}>
              {result.existing_titles.length ? "Use as a new title" : "Use this"}
            </button>
          )}
          {onRetry && (
            <button type="button" className="btn sm ghost" onClick={onRetry}>
              Look up again
            </button>
          )}
        </div>
      )}

      {others.length > 0 && (
        <details>
          <summary className="small">Other matches ({others.length})</summary>
          <ul className="list" style={{ marginTop: 6 }}>
            {others.map((c, i) => (
              <li key={i}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <strong>
                    {c.title}
                    {c.year ? ` (${c.year})` : ""}
                  </strong>
                  {c.artist ? ` · ${c.artist}` : ""}
                  <div className="small muted">
                    {c.source}
                    {c.detail ? ` · ${c.detail}` : ""}
                  </div>
                </div>
                {onUse && (
                  <button type="button" className="btn sm" onClick={() => onUse(c)}>
                    Use
                  </button>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}

      <span className="small muted">
        {attemptsSummary(result.attempts)}
        {best?.url && (
          <>
            {" · "}
            <a href={best.url} target="_blank" rel="noopener noreferrer">
              View on {best.source}
            </a>
          </>
        )}
      </span>
    </div>
  );
}
