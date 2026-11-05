import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, qs } from "../api";
import { SearchBar } from "../components/Layout";
import { dateOnly, ErrorText, FormatBadge, Meter } from "../components/ui";
import { useApp } from "../state";
import type { Stats } from "../types";

export function Overview() {
  const { user, savePrefs, formatById, categoryById, meta } = useApp();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const physicalOnly = !!user?.prefs.physical_only;
  const hasDigital = meta?.formats.some((f) => !f.physical);

  useEffect(() => {
    api
      .get<Stats>(`/api/stats${qs({ physical: physicalOnly })}`)
      .then(setStats)
      .catch((e) => setError(e.message));
  }, [physicalOnly]);

  const max = Math.max(1, ...(stats?.by_format.map((f) => f.count) ?? [1]));

  return (
    <>
      <SearchBar
        value={q}
        onChange={setQ}
        onSubmit={(v) => navigate(`/search${qs({ q: v })}`)}
        onScan={(code) => navigate(`/search${qs({ q: code })}`)}
      />
      <ErrorText error={error} />

      {hasDigital && (
        <div className="row">
          <label className="check">
            <input type="checkbox" checked={physicalOnly} onChange={(e) => savePrefs({ physical_only: e.target.checked })} />
            Physical media only
          </label>
        </div>
      )}

      <section className="stats" aria-label="Collection totals">
        <div className="card">
          <div className="label-caps">Items</div>
          <div className="stat-value">{stats ? stats.items.toLocaleString() : "—"}</div>
          <div className="stat-note">across {stats?.formats_in_use ?? "—"} formats</div>
        </div>
        <div className="card">
          <div className="label-caps">Unique titles</div>
          <div className="stat-value">{stats ? stats.titles.toLocaleString() : "—"}</div>
          <div className="stat-note">movies, music and games</div>
        </div>
        <div className="card">
          <div className="label-caps">Owned in 2+ formats</div>
          <div className="stat-value">{stats ? stats.multi_format_titles.toLocaleString() : "—"}</div>
          <div className="stat-note">titles on more than one format</div>
        </div>
        <Link to="/wishlist" className="card" style={{ textDecoration: "none" }}>
          <div className="label-caps">Wish list</div>
          <div className="stat-value">{stats ? stats.wishlist_open.toLocaleString() : "—"}</div>
          <div className="stat-note">still looking for</div>
        </Link>
      </section>

      <section className="grid-2">
        <div className="card">
          <h2 className="card-title">Items by format</h2>
          {stats && stats.by_format.length === 0 && (
            <p className="muted">
              Nothing here yet. <Link to="/items/new">Add your first item</Link> or import from Jira in Settings.
            </p>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {stats?.by_format.map((row) => (
              <Link key={row.format_id} to={`/search${qs({ format: row.format_id, view: "grid" })}`} className="meter-row" aria-label={`${formatById(row.format_id)?.name}: ${row.count}`}>
                <span>
                  <FormatBadge format={formatById(row.format_id)} />
                </span>
                <Meter value={row.count} max={max} />
                <span className="meter-count">{row.count.toLocaleString()}</span>
              </Link>
            ))}
          </div>
        </div>

        <div className="stack">
          <div className="card">
            <h2 className="card-title">By category</h2>
            <div className="stats" style={{ gridTemplateColumns: `repeat(${Math.max(1, stats?.by_category.length ?? 1)}, minmax(0, 1fr))` }}>
              {stats?.by_category
                .slice()
                .sort((a, b) => b.count - a.count)
                .map((c) => (
                  <Link key={c.category_id} to={`/search${qs({ category: c.category_id, view: "grid" })}`} style={{ textDecoration: "none" }}>
                    <div className="label-caps">{categoryById(c.category_id)?.name}</div>
                    <div style={{ fontWeight: 800, fontStretch: "112%", fontSize: 28 }}>{c.count.toLocaleString()}</div>
                    <div className="stat-note">{stats.items ? Math.round((c.count / stats.items) * 100) : 0}%</div>
                  </Link>
                ))}
            </div>
          </div>

          <div className="card flush">
            <h2 className="card-title">New arrivals</h2>
            <div className="table-wrap">
              <table className="table">
                <tbody>
                  {stats?.recent.map((i) => (
                    <tr key={i.id}>
                      <td className="title-cell">
                        <Link to={`/titles/${i.title_id}`}>{i.title}</Link>
                      </td>
                      <td>
                        <FormatBadge format={formatById(i.format_id)} />
                      </td>
                      <td className="num muted">{i.year ?? ""}</td>
                      <td className="muted" style={{ whiteSpace: "nowrap", textAlign: "right" }}>
                        {dateOnly(i.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
