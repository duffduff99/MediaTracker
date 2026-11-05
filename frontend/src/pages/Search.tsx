import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, qs } from "../api";
import { SearchBar } from "../components/Layout";
import { Scanner } from "../components/Scanner";
import { ConditionSticker, ErrorText, FormatBadge, Icon, Modal, dateOnly, formatValue, useToast } from "../components/ui";
import { useApp } from "../state";
import type { Field, Item, SearchResult } from "../types";

const PAGE = 100;
const DEFAULT_HIDDEN = ["notes", "added_by", "created_at"];

interface Column {
  key: string;
  label: string;
  field?: Field;
  value: (i: Item) => string | number;
  render?: (i: Item) => React.ReactNode;
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function Search() {
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [scanNow, setScanNow] = useState(params.get("scan") === "1");
  const debouncedQ = useDebounced(q.trim(), 250);
  const view = (params.get("view") as "titles" | "grid" | null) ?? (window.innerWidth >= 900 ? "grid" : "titles");
  const formatIds = params.getAll("format").map(Number).filter(Boolean);
  const categoryId = Number(params.get("category")) || undefined;

  const update = (patch: Record<string, string | string[] | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      next.delete(k);
      if (Array.isArray(v)) v.forEach((x) => next.append(k, x));
      else if (v) next.set(k, v);
    }
    next.delete("scan");
    setParams(next, { replace: true });
  };

  useEffect(() => {
    if ((params.get("q") ?? "") !== debouncedQ) update({ q: debouncedQ || null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQ]);

  const onScan = (code: string) => {
    setQ(code);
    update({ q: code, view: "titles" });
  };

  return (
    <>
      <SearchBar value={q} onChange={setQ} onScan={onScan} autoFocus={!q && window.innerWidth >= 900} />
      {scanNow && <Scanner onClose={() => setScanNow(false)} onDetected={(c) => { setScanNow(false); onScan(c); }} />}
      <div className="row">
        <div className="chips" role="group" aria-label="View">
          <button type="button" className="chip" aria-pressed={view === "titles"} onClick={() => update({ view: "titles" })}>
            By title
          </button>
          <button type="button" className="chip" aria-pressed={view === "grid"} onClick={() => update({ view: "grid" })}>
            Grid
          </button>
        </div>
      </div>
      {view === "titles" ? (
        <TitleResults q={debouncedQ} />
      ) : (
        <Grid q={debouncedQ} formatIds={formatIds} categoryId={categoryId} update={update} />
      )}
    </>
  );
}

// ------------------------------------------------------------------ grouped results ("do I own it?")

function TitleResults({ q }: { q: string }) {
  const { formatById, categoryById, can, fieldsFor } = useApp();
  const [res, setRes] = useState<SearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

  useEffect(() => {
    if (!q) {
      setRes(null);
      return;
    }
    let live = true;
    api
      .get<SearchResult>(`/api/search${qs({ q })}`)
      .then((r) => live && setRes(r))
      .catch((e) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [q]);

  if (!q) return <p className="muted">Type a title, artist or barcode, or scan one. Results update as you type.</p>;
  if (error) return <ErrorText error={error} />;
  if (!res) return <p className="status-line">SEARCHING…</p>;

  const isBarcode = /^[\d\s-]{6,}$/.test(q);
  const addToWish = async () => {
    await api.post("/api/wishlist", { text: q });
    toast(`Added “${q}” to the wish list`);
  };

  return (
    <>
      <p className="status-line" aria-live="polite">
        {res.total_titles ?? res.titles.length} TITLE{(res.total_titles ?? 0) === 1 ? "" : "S"} · {res.total_items} COP{res.total_items === 1 ? "Y" : "IES"}
      </p>
      {res.wishlist.length > 0 && (
        <div className="notice warn">
          <strong>On your wish list:</strong> {res.wishlist.map((w) => w.text).join(" · ")}
        </div>
      )}
      {res.box_sets.map((b) => (
        <div key={b.id} className="result">
          <div className="result-head">
            <Link to={`/boxsets/${b.id}`} className="result-name">
              {b.name}
            </Link>
            <span className="result-meta">Box set · {b.count} items</span>
          </div>
        </div>
      ))}
      {res.titles.length === 0 && res.box_sets.length === 0 ? (
        <div className="card not-found">
          <div style={{ fontWeight: 800, fontStretch: "112%", fontSize: 22 }}>Not in your collection.</div>
          {can("editor") && (
            <div className="row">
              {!isBarcode && (
                <button className="btn" type="button" onClick={addToWish}>
                  + Add “{q}” to wish list
                </button>
              )}
              <Link className="btn primary" to={`/items/new${qs(isBarcode ? { barcode: q } : { title: q })}`}>
                + Add to collection
              </Link>
            </div>
          )}
        </div>
      ) : (
        <div className="results">
          {res.titles.map((t) => (
            <article key={t.title_id} className="result">
              <div className="result-head">
                <Link to={`/titles/${t.title_id}`} className="result-name">
                  {t.name}
                </Link>
                <span className="result-meta">
                  {[t.year, categoryById(t.category_id)?.name].filter(Boolean).join(" · ")}
                </span>
              </div>
              {t.artist && <div className="muted">{t.artist}</div>}
              {t.items.map((i) => {
                const extras = fieldsFor([i.format_id])
                  .filter((f) => f.key !== "condition" && f.key !== "tags")
                  .map((f) => formatValue(f, i.custom[f.key]) && `${f.type === "boolean" ? f.label : formatValue(f, i.custom[f.key])}`)
                  .filter(Boolean)
                  .slice(0, 3);
                return (
                  <div key={i.id} className="copy">
                    <div className="copy-info">
                      <span>
                        <FormatBadge format={formatById(i.format_id)} to={`/items/${i.id}/edit`} />
                      </span>
                      {i.box_set_name && (
                        <span className="copy-sub">
                          In box set: <Link to={`/boxsets/${i.box_set_id}`}>{i.box_set_name}</Link>
                        </span>
                      )}
                      {extras.length > 0 && <span className="copy-sub">{extras.join(" · ")}</span>}
                    </div>
                    <ConditionSticker value={i.custom.condition} />
                  </div>
                );
              })}
            </article>
          ))}
        </div>
      )}
    </>
  );
}

// ------------------------------------------------------------------ grid

function Grid({
  q,
  formatIds,
  categoryId,
  update,
}: {
  q: string;
  formatIds: number[];
  categoryId?: number;
  update: (p: Record<string, string | string[] | null>) => void;
}) {
  const { meta, user, savePrefs, formatById, categoryById, fieldsFor, can } = useApp();
  const toast = useToast();
  const [items, setItems] = useState<Item[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 }>({ key: "title", dir: 1 });
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [picking, setPicking] = useState(false);
  const [moving, setMoving] = useState(false);
  const [reload, setReload] = useState(0);
  const hidden = new Set(user?.prefs.hidden_columns ?? DEFAULT_HIDDEN);
  const fmtKey = formatIds.join(",");

  useEffect(() => {
    let live = true;
    setItems(null);
    api
      .get<Item[]>(`/api/items${qs({ q, format_id: formatIds, category_id: categoryId })}`)
      .then((r) => {
        if (!live) return;
        setItems(r);
        setPage(0);
        setSelected(new Set());
      })
      .catch((e) => live && setError(e.message));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, fmtKey, categoryId, reload]);

  // Which formats are "in view" decides which custom columns make sense.
  const relevantFormatIds = useMemo(() => {
    if (formatIds.length) return formatIds;
    if (categoryId) return (meta?.formats ?? []).filter((f) => f.category_ids.includes(categoryId)).map((f) => f.id);
    return [...new Set((items ?? []).map((i) => i.format_id))];
  }, [fmtKey, categoryId, items, meta]); // eslint-disable-line react-hooks/exhaustive-deps

  const columns: Column[] = useMemo(() => {
    const showArtist = categoryId
      ? !!categoryById(categoryId)?.has_artist
      : relevantFormatIds.some((id) => (formatById(id)?.category_ids ?? []).some((c) => categoryById(c)?.has_artist));
    const cols: Column[] = [
      { key: "title", label: "Title", value: (i) => i.sort_title, render: (i) => <Link to={`/titles/${i.title_id}`}>{i.title}</Link> },
    ];
    if (showArtist) cols.push({ key: "artist", label: "Artist", value: (i) => (i.artist ?? "").toLowerCase() });
    cols.push(
      { key: "year", label: "Year", value: (i) => i.year ?? 0, render: (i) => i.year ?? "" },
      {
        key: "format",
        label: "Format",
        value: (i) => formatById(i.format_id)?.sort_order ?? 0,
        render: (i) => <FormatBadge format={formatById(i.format_id)} />,
      },
      { key: "barcode", label: "Barcode", value: (i) => i.barcode ?? "", render: (i) => i.barcode ?? "" },
      {
        key: "box_set",
        label: "Box set",
        value: (i) => (i.box_set_name ?? "").toLowerCase(),
        render: (i) => (i.box_set_id ? <Link to={`/boxsets/${i.box_set_id}`}>{i.box_set_name}</Link> : ""),
      }
    );
    for (const f of fieldsFor(relevantFormatIds)) {
      cols.push({
        key: f.key,
        label: f.label,
        field: f,
        value: (i) => {
          const v = i.custom[f.key];
          if (f.type === "number") return typeof v === "number" ? v : -Infinity;
          if (f.key === "condition" && typeof v === "string") return f.options.indexOf(v);
          return formatValue(f, v).toLowerCase();
        },
        render: (i) => (f.key === "condition" ? <ConditionSticker value={i.custom[f.key]} small /> : formatValue(f, i.custom[f.key])),
      });
    }
    cols.push(
      { key: "notes", label: "Notes", value: (i) => (i.notes ?? "").toLowerCase(), render: (i) => i.notes ?? "" },
      { key: "added_by", label: "Added by", value: (i) => i.added_by ?? "" },
      { key: "created_at", label: "Added", value: (i) => i.created_at, render: (i) => dateOnly(i.created_at) }
    );
    return cols;
  }, [relevantFormatIds, meta]); // eslint-disable-line react-hooks/exhaustive-deps

  const visible = columns.filter((c) => c.key === "title" || !hidden.has(c.key));

  const sorted = useMemo(() => {
    if (!items) return [];
    const col = columns.find((c) => c.key === sort.key) ?? columns[0];
    return [...items].sort((a, b) => {
      const va = col.value(a);
      const vb = col.value(b);
      const cmp = va < vb ? -1 : va > vb ? 1 : a.sort_title < b.sort_title ? -1 : a.sort_title > b.sort_title ? 1 : 0;
      return cmp * sort.dir;
    });
  }, [items, sort, columns]);

  const pageItems = sorted.slice(page * PAGE, (page + 1) * PAGE);
  const pages = Math.max(1, Math.ceil(sorted.length / PAGE));
  const exportQuery = qs({ q, format_id: formatIds, category_id: categoryId });

  const toggleFormat = (id: number) => {
    const next = formatIds.includes(id) ? formatIds.filter((x) => x !== id) : [...formatIds, id];
    update({ format: next.map(String) });
  };

  const bulkDelete = async () => {
    if (!confirm(`Move ${selected.size} item(s) to the trash? You can restore them for 30 days.`)) return;
    await api.post("/api/items/bulk-delete", { ids: [...selected] });
    toast(`Moved ${selected.size} item(s) to the trash`);
    setReload((n) => n + 1);
  };

  return (
    <>
      <div className="card" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div className="row">
          <label className="field-label label-caps" htmlFor="cat-filter">
            Category
          </label>
          <select
            id="cat-filter"
            className="input"
            style={{ width: "auto", minWidth: 160 }}
            value={categoryId ?? ""}
            onChange={(e) => update({ category: e.target.value || null, format: [] })}
          >
            <option value="">All</option>
            {meta?.categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <div className="spacer" />
          <button type="button" className="btn sm" onClick={() => setPicking(true)}>
            <Icon name="columns" size={16} /> Columns
          </button>
          <a className="btn sm" href={`/api/export.csv${qs({ q, format_id: formatIds, category_id: categoryId, columns: visible.map((c) => c.key).join(",") })}`} download>
            <Icon name="download" size={16} /> CSV
          </a>
          <a className="btn sm" href={`/api/export.xlsx${exportQuery}`} download>
            <Icon name="download" size={16} /> Excel
          </a>
        </div>
        <div className="chips" role="group" aria-label="Formats">
          {meta?.formats
            .filter((f) => !categoryId || f.category_ids.includes(categoryId))
            .map((f) => (
              <button key={f.id} type="button" className="chip" aria-pressed={formatIds.includes(f.id)} onClick={() => toggleFormat(f.id)}>
                {f.name}
              </button>
            ))}
          {formatIds.length > 0 && (
            <button type="button" className="chip" onClick={() => update({ format: [] })}>
              Clear
            </button>
          )}
        </div>
      </div>

      <ErrorText error={error} />
      <div className="card flush">
        <div className="row" style={{ padding: "12px 14px" }}>
          <span className="status-line" aria-live="polite">
            {items ? `${items.length.toLocaleString()} ITEM${items.length === 1 ? "" : "S"}` : "LOADING…"}
          </span>
          <div className="spacer" />
          {can("editor") && selected.size > 0 && (
            <>
              <button type="button" className="btn sm" onClick={() => setMoving(true)}>
                Change category…
              </button>
              <button type="button" className="btn sm danger" onClick={bulkDelete}>
                Delete {selected.size} selected
              </button>
            </>
          )}
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                {can("editor") && (
                  <th className="check-col">
                    <input
                      type="checkbox"
                      aria-label="Select all on this page"
                      checked={pageItems.length > 0 && pageItems.every((i) => selected.has(i.id))}
                      onChange={(e) => {
                        const next = new Set(selected);
                        pageItems.forEach((i) => (e.target.checked ? next.add(i.id) : next.delete(i.id)));
                        setSelected(next);
                      }}
                    />
                  </th>
                )}
                {visible.map((c) => (
                  <th key={c.key} aria-sort={sort.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : undefined}>
                    <button type="button" onClick={() => setSort((s) => ({ key: c.key, dir: s.key === c.key ? ((-s.dir) as 1 | -1) : 1 }))}>
                      {c.label}
                      {sort.key === c.key && <Icon name={sort.dir === 1 ? "up" : "down"} size={13} />}
                    </button>
                  </th>
                ))}
                <th>
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {pageItems.map((i) => (
                <tr key={i.id}>
                  {can("editor") && (
                    <td className="check-col">
                      <input
                        type="checkbox"
                        aria-label={`Select ${i.title}`}
                        checked={selected.has(i.id)}
                        onChange={(e) => {
                          const next = new Set(selected);
                          if (e.target.checked) next.add(i.id);
                          else next.delete(i.id);
                          setSelected(next);
                        }}
                      />
                    </td>
                  )}
                  {visible.map((c) => (
                    <td key={c.key} className={c.key === "title" ? "title-cell" : c.key === "notes" ? "notes" : c.key === "year" ? "num" : undefined}>
                      {c.render ? c.render(i) : c.value(i)}
                    </td>
                  ))}
                  <td>
                    {can("editor") && (
                      <Link className="btn sm ghost" to={`/items/${i.id}/edit`}>
                        Edit
                      </Link>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {items && items.length === 0 && <div className="empty">No items match.</div>}
        </div>
        {pages > 1 && (
          <div className="pager">
            <button type="button" className="btn sm" disabled={page === 0} onClick={() => setPage(page - 1)}>
              Previous
            </button>
            <span className="small muted">
              Page {page + 1} of {pages}
            </span>
            <button type="button" className="btn sm" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>
              Next
            </button>
          </div>
        )}
      </div>

      {moving && (
        <ChangeCategory
          itemIds={[...selected]}
          onClose={() => setMoving(false)}
          onDone={(msg) => {
            setMoving(false);
            toast(msg);
            setReload((n) => n + 1);
          }}
        />
      )}

      {picking && (
        <Modal title="Show columns" onClose={() => setPicking(false)}>
          <p className="hint">Only columns that apply to the formats in view are listed. Your choice is saved to your account.</p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 4 }}>
            {columns
              .filter((c) => c.key !== "title")
              .map((c) => (
                <label key={c.key} className="check">
                  <input
                    type="checkbox"
                    checked={!hidden.has(c.key)}
                    onChange={(e) => {
                      const next = new Set(hidden);
                      if (e.target.checked) next.delete(c.key);
                      else next.add(c.key);
                      savePrefs({ hidden_columns: [...next] });
                    }}
                  />
                  {c.label}
                </label>
              ))}
          </div>
          {can("admin") && (
            <p className="hint">
              To add or change columns, go to <Link to="/settings/fields">Settings → Columns</Link>.
            </p>
          )}
        </Modal>
      )}
    </>
  );
}

function ChangeCategory({ itemIds, onClose, onDone }: { itemIds: number[]; onClose: () => void; onDone: (msg: string) => void }) {
  const { meta } = useApp();
  const [categoryId, setCategoryId] = useState<number>(meta?.categories[0]?.id ?? 0);
  const [skipped, setSkipped] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const move = async () => {
    try {
      const r = await api.post<{ moved: number; skipped: string[] }>("/api/titles/change-category", { item_ids: itemIds, category_id: categoryId });
      if (r.skipped.length) setSkipped(r.skipped);
      else onDone(`Moved ${r.moved} title(s)`);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <Modal title="Change category" onClose={onClose}>
      {skipped ? (
        <>
          <p>Some titles couldn't move because their format isn't set up for that category (Settings → Media types):</p>
          <ul className="report-list">
            {skipped.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
          <button className="btn primary" type="button" onClick={() => onDone("Category changed")}>
            OK
          </button>
        </>
      ) : (
        <>
          <p className="hint">
            Moves the titles of the {itemIds.length} selected item(s), with all their copies, e.g. TV seasons that came in as Movies.
          </p>
          <div className="field">
            <label htmlFor="move-cat">New category</label>
            <select id="move-cat" className="input" value={categoryId} onChange={(e) => setCategoryId(Number(e.target.value))}>
              {meta?.categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <ErrorText error={error} />
          <button className="btn primary" type="button" onClick={move}>
            Move
          </button>
        </>
      )}
    </Modal>
  );
}
