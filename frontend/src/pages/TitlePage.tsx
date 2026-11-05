import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, qs } from "../api";
import { ConditionSticker, ErrorText, FormatBadge, Modal, dateOnly, formatValue, useToast } from "../components/ui";
import { useApp } from "../state";
import type { TitleDetail, TitleHit } from "../types";

export function TitlePage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { formatById, categoryById, fieldsFor, can } = useApp();
  const [t, setT] = useState<TitleDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [merging, setMerging] = useState(false);

  const load = () =>
    api
      .get<TitleDetail>(`/api/titles/${id}`)
      .then(setT)
      .catch((e) => setError(e.message));
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (error) return <ErrorText error={error} />;
  if (!t) return <p className="status-line">LOADING…</p>;
  const category = categoryById(t.category_id);

  const split = async (itemId: number) => {
    if (!confirm("Move this copy to its own separate title? Use this when two different films were matched together (e.g. a remake).")) return;
    const item = await api.post<{ title_id: number }>(`/api/items/${itemId}/split`);
    toast("Moved to a separate title");
    navigate(`/titles/${item.title_id}`);
  };

  const remove = async (itemId: number) => {
    if (!confirm("Move this item to the trash? You can restore it for 30 days.")) return;
    await api.del(`/api/items/${itemId}`);
    toast("Moved to the trash");
    if (t.items.length <= 1) navigate("/search");
    else load();
  };

  return (
    <>
      <div className="detail-head">
        <div>
          <div className="page-sub">{[category?.name, t.year].filter(Boolean).join(" · ")}</div>
          <h1 className="page-title">{t.name}</h1>
          {t.artist && <div style={{ fontSize: 18, marginTop: 4 }}>{t.artist}</div>}
        </div>
        {can("editor") && (
          <div className="row">
            <Link className="btn accent" to={`/items/new${qs({ title_id: t.id })}`}>
              + Add another copy
            </Link>
            <button className="btn" type="button" onClick={() => setEditing(true)}>
              Edit title
            </button>
            <button className="btn" type="button" onClick={() => setMerging(true)}>
              Merge…
            </button>
          </div>
        )}
      </div>

      <div className="vfd" style={{ gap: 8 }}>
        <span className="vfd-readout">
          OWNED IN {new Set(t.items.map((i) => i.format_id)).size} FORMAT{new Set(t.items.map((i) => i.format_id)).size === 1 ? "" : "S"}:
        </span>
        {[...new Set(t.items.map((i) => i.format_id))].map((fid) => (
          <FormatBadge key={fid} format={formatById(fid)} />
        ))}
      </div>

      {t.box_sets.length > 0 && (
        <div className="notice">
          Part of{" "}
          {t.box_sets.map((b, n) => (
            <span key={b.id}>
              {n > 0 && ", "}
              <Link to={`/boxsets/${b.id}`}>
                <strong>{b.name}</strong>
              </Link>{" "}
              ({b.count} items)
            </span>
          ))}
        </div>
      )}

      <section className="copies" aria-label="Copies">
        {t.items.map((i) => {
          const fmt = formatById(i.format_id);
          const fields = fieldsFor([i.format_id]).filter((f) => f.key !== "condition");
          return (
            <article key={i.id} className="card" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                <FormatBadge format={fmt} />
                <ConditionSticker value={i.custom.condition} />
              </div>
              <dl className="kv">
                {fmt?.physical !== false && (
                  <>
                    <dt>Barcode</dt>
                    <dd className={i.barcode ? "mono" : "muted"}>{i.barcode || "—"}</dd>
                  </>
                )}
                {i.box_set_id && (
                  <>
                    <dt>Box set</dt>
                    <dd>
                      <Link to={`/boxsets/${i.box_set_id}`}>{i.box_set_name}</Link>
                    </dd>
                  </>
                )}
                {fields
                  .filter((f) => formatValue(f, i.custom[f.key]))
                  .map((f) => (
                    <div key={f.key} style={{ display: "contents" }}>
                      <dt>{f.label}</dt>
                      <dd>{formatValue(f, i.custom[f.key])}</dd>
                    </div>
                  ))}
                {i.notes && (
                  <>
                    <dt>Notes</dt>
                    <dd style={{ whiteSpace: "pre-line" }}>{i.notes}</dd>
                  </>
                )}
                <dt>Added</dt>
                <dd className="muted">
                  {dateOnly(i.created_at)}
                  {i.added_by ? ` by ${i.added_by}` : ""}
                </dd>
              </dl>
              {can("editor") && (
                <div className="row">
                  <Link className="btn sm" to={`/items/${i.id}/edit`}>
                    Edit
                  </Link>
                  {t.items.length > 1 && (
                    <button className="btn sm ghost" type="button" onClick={() => split(i.id)}>
                      Not the same title
                    </button>
                  )}
                  <div className="spacer" />
                  <button className="btn sm danger" type="button" onClick={() => remove(i.id)}>
                    Delete
                  </button>
                </div>
              )}
            </article>
          );
        })}
      </section>

      {editing && <EditTitle title={t} hasArtist={!!category?.has_artist} onClose={() => setEditing(false)} onSaved={(nt) => { setT(nt); setEditing(false); }} />}
      {merging && <MergeTitle title={t} onClose={() => setMerging(false)} onMerged={(nt) => { setMerging(false); navigate(`/titles/${nt.id}`); }} />}
    </>
  );
}

function EditTitle({ title, hasArtist, onClose, onSaved }: { title: TitleDetail; hasArtist: boolean; onClose: () => void; onSaved: (t: TitleDetail) => void }) {
  const [name, setName] = useState(title.name);
  const [year, setYear] = useState(title.year ? String(title.year) : "");
  const [artist, setArtist] = useState(title.artist ?? "");
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      onSaved(await api.put<TitleDetail>(`/api/titles/${title.id}`, { name, year: year ? Number(year) : null, artist: artist || null }));
    } catch (err) {
      setError((err as Error).message);
    }
  };
  return (
    <Modal title="Edit title" onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <p className="hint">Changes apply to every copy of this title.</p>
        <div className="field">
          <label htmlFor="t-name">Title</label>
          <input id="t-name" className="input" value={name} onChange={(e) => setName(e.target.value)} required />
        </div>
        {hasArtist && (
          <div className="field">
            <label htmlFor="t-artist">Artist</label>
            <input id="t-artist" className="input" value={artist} onChange={(e) => setArtist(e.target.value)} />
          </div>
        )}
        <div className="field">
          <label htmlFor="t-year">Year (original release)</label>
          <input id="t-year" className="input" type="number" inputMode="numeric" value={year} onChange={(e) => setYear(e.target.value)} />
        </div>
        <ErrorText error={error} />
        <div className="form-actions">
          <button className="btn primary" type="submit">
            Save
          </button>
        </div>
      </form>
    </Modal>
  );
}

function MergeTitle({ title, onClose, onMerged }: { title: TitleDetail; onClose: () => void; onMerged: (t: TitleDetail) => void }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<TitleHit[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (q.trim().length < 2) return setHits([]);
    const t = window.setTimeout(() => {
      api
        .get<TitleHit[]>(`/api/titles${qs({ q, category_id: title.category_id, limit: 10 })}`)
        .then((r) => setHits(r.filter((h) => h.id !== title.id)))
        .catch(() => {});
    }, 200);
    return () => window.clearTimeout(t);
  }, [q, title]);
  const merge = async (into: TitleHit) => {
    if (!confirm(`Move all copies of “${title.name}” into “${into.name}”?`)) return;
    try {
      onMerged(await api.post<TitleDetail>(`/api/titles/${title.id}/merge`, { into_id: into.id }));
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <Modal title="Merge into another title" onClose={onClose}>
      <p className="hint">Use this when the same film or album ended up as two separate titles. All copies move to the title you pick.</p>
      <div className="field">
        <label htmlFor="merge-q">Find title</label>
        <input id="merge-q" className="input" value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off" />
      </div>
      <ul className="list">
        {hits.map((h) => (
          <li key={h.id}>
            <div style={{ flex: 1 }}>
              <strong>{h.name}</strong> {h.year ? `(${h.year})` : ""}
              <div className="small muted">{h.formats.join(", ")}</div>
            </div>
            <button className="btn sm" type="button" onClick={() => merge(h)}>
              Merge here
            </button>
          </li>
        ))}
      </ul>
      <ErrorText error={error} />
    </Modal>
  );
}
