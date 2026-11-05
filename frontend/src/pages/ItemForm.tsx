import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, qs } from "../api";
import { FieldInput } from "../components/FieldInput";
import { Scanner } from "../components/Scanner";
import { ErrorText, FormatBadge, Icon, useToast } from "../components/ui";
import { useApp } from "../state";
import type { BoxSet, CustomValue, Item, TitleDetail, TitleHit } from "../types";

const LAST_FORMAT = "mt-last-format";

export function ItemForm() {
  const { id } = useParams();
  const editing = !!id;
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { meta, formatById, categoryById, fieldsFor } = useApp();

  const [formatId, setFormatId] = useState<number>(() => {
    const fromQuery = Number(params.get("format_id"));
    if (fromQuery) return fromQuery;
    try {
      return Number(localStorage.getItem(LAST_FORMAT)) || 0;
    } catch {
      return 0;
    }
  });
  const [titleText, setTitleText] = useState(params.get("title") ?? "");
  const [linked, setLinked] = useState<TitleHit | null>(null);
  const [suggestions, setSuggestions] = useState<TitleHit[]>([]);
  const [showSuggest, setShowSuggest] = useState(false);
  const [year, setYear] = useState("");
  const [artist, setArtist] = useState("");
  const [barcode, setBarcode] = useState(params.get("barcode") ?? "");
  const [boxSetId, setBoxSetId] = useState<number | null>(Number(params.get("box_set_id")) || null);
  const [notes, setNotes] = useState("");
  const [custom, setCustom] = useState<Record<string, CustomValue>>({});
  const [boxSets, setBoxSets] = useState<BoxSet[]>([]);
  const [dupes, setDupes] = useState<Item[]>([]);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const titleRef = useRef<HTMLInputElement>(null);

  // default format once meta loads
  useEffect(() => {
    if (meta && !meta.formats.some((f) => f.id === formatId)) setFormatId(meta.formats[0]?.id ?? 0);
  }, [meta, formatId]);

  useEffect(() => {
    api.get<BoxSet[]>("/api/boxsets").then(setBoxSets).catch(() => {});
  }, []);

  // load existing item, or a title passed in the URL
  useEffect(() => {
    if (editing) {
      api
        .get<Item>(`/api/items/${id}`)
        .then((i) => {
          setFormatId(i.format_id);
          setLinked({ id: i.title_id, name: i.title, year: i.year, artist: i.artist, category_id: i.category_id, formats: [] });
          setTitleText(i.title);
          setBarcode(i.barcode ?? "");
          setBoxSetId(i.box_set_id);
          setNotes(i.notes ?? "");
          setCustom(i.custom);
        })
        .catch((e) => setError(e.message));
    } else if (params.get("title_id")) {
      api
        .get<TitleDetail>(`/api/titles/${params.get("title_id")}`)
        .then((t) => {
          setLinked({ id: t.id, name: t.name, year: t.year, artist: t.artist, category_id: t.category_id, formats: [] });
          setTitleText(t.name);
          const fmt = meta?.formats.find((f) => f.category_id === t.category_id && !t.items.some((i) => i.format_id === f.id));
          if (fmt && formatById(formatId)?.category_id !== t.category_id) setFormatId(fmt.id);
        })
        .catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const format = formatById(formatId);
  const category = categoryById(format?.category_id ?? 0);

  // unlink a title from another category if the format changes category
  useEffect(() => {
    if (linked && format && linked.category_id !== format.category_id) setLinked(null);
  }, [format, linked]);

  // title suggestions
  useEffect(() => {
    if (linked || titleText.trim().length < 2 || !format) {
      setSuggestions([]);
      return;
    }
    const t = window.setTimeout(() => {
      api
        .get<TitleHit[]>(`/api/titles${qs({ q: titleText, category_id: format.category_id, limit: 8 })}`)
        .then(setSuggestions)
        .catch(() => {});
    }, 200);
    return () => window.clearTimeout(t);
  }, [titleText, linked, format]);

  // warn if this barcode is already in the collection
  useEffect(() => {
    const code = barcode.replace(/\D/g, "");
    if (code.length < 8) {
      setDupes([]);
      return;
    }
    const t = window.setTimeout(() => {
      api
        .get<Item[]>(`/api/items${qs({ q: code })}`)
        .then((r) => setDupes(r.filter((i) => String(i.id) !== id && (i.barcode ?? "").replace(/\D/g, "").replace(/^0+/, "") === code.replace(/^0+/, ""))))
        .catch(() => {});
    }, 300);
    return () => window.clearTimeout(t);
  }, [barcode, id]);

  const fields = format ? fieldsFor([format.id]) : [];

  const save = async (addAnother: boolean) => {
    setError(null);
    if (!format) return setError("Pick a format.");
    if (!linked && !titleText.trim()) return setError("Enter a title.");
    setBusy(true);
    const body = {
      title_id: linked?.id ?? null,
      title: linked ? null : titleText.trim(),
      year: linked ? null : year ? Number(year) : null,
      artist: linked ? null : artist.trim() || null,
      format_id: format.id,
      barcode: barcode.trim() || null,
      box_set_id: boxSetId,
      notes: notes.trim() || null,
      custom: Object.fromEntries(Object.entries(custom).filter(([k]) => fields.some((f) => f.key === k))),
    };
    try {
      const saved = editing ? await api.put<Item>(`/api/items/${id}`, body) : await api.post<Item>("/api/items", body);
      try {
        localStorage.setItem(LAST_FORMAT, String(format.id));
      } catch {
        /* ignore */
      }
      toast(editing ? "Saved" : `Added ${saved.title} (${format.name})`);
      if (addAnother) {
        setLinked(null);
        setTitleText("");
        setYear("");
        setArtist("");
        setBarcode("");
        setNotes("");
        setCustom({});
        setDupes([]);
        titleRef.current?.focus();
        window.scrollTo({ top: 0 });
      } else {
        navigate(`/titles/${saved.title_id}`);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!confirm("Move this item to the trash? You can restore it for 30 days.")) return;
    await api.del(`/api/items/${id}`);
    toast("Moved to the trash");
    navigate(linked ? `/titles/${linked.id}` : "/search");
  };

  const newBoxSet = async () => {
    const name = prompt("Box set name (e.g. The James Bond Collection)");
    if (!name?.trim()) return;
    const b = await api.post<BoxSet>("/api/boxsets", { name: name.trim() });
    setBoxSets((s) => [...s, b]);
    setBoxSetId(b.id);
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    save(false);
  };

  return (
    <>
      <div className="page-head">
        <div>
          <div className="page-sub">{editing ? "Edit item" : "Add to collection"}</div>
          <h1 className="page-title">{editing ? titleText || "…" : "New item"}</h1>
        </div>
        {linked && (
          <Link className="crumb" to={`/titles/${linked.id}`}>
            View title →
          </Link>
        )}
      </div>

      <form className="card form" onSubmit={submit}>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="format">Format</label>
            <select id="format" className="input" value={formatId || ""} onChange={(e) => setFormatId(Number(e.target.value))}>
              {meta?.categories.map((c) => (
                <optgroup key={c.id} label={c.name}>
                  {meta.formats
                    .filter((f) => f.category_id === c.id)
                    .map((f) => (
                      <option key={f.id} value={f.id}>
                        {f.name}
                      </option>
                    ))}
                </optgroup>
              ))}
            </select>
          </div>

          <div className="field" style={{ gridColumn: "span 2" }}>
            <label htmlFor="title">{category?.has_artist ? "Album title" : "Title"}</label>
            {linked ? (
              <div className="linked">
                <strong>{linked.name}</strong>
                <span className="muted">{[linked.year, linked.artist].filter(Boolean).join(" · ")}</span>
                {linked.formats.length > 0 && <span className="small muted">You own: {linked.formats.join(", ")}</span>}
                <div className="spacer" />
                <button
                  type="button"
                  className="btn sm"
                  onClick={() => {
                    setLinked(null);
                    setTimeout(() => titleRef.current?.focus());
                  }}
                >
                  Change
                </button>
              </div>
            ) : (
              <div className="ac">
                <input
                  id="title"
                  ref={titleRef}
                  className="input"
                  autoComplete="off"
                  value={titleText}
                  onChange={(e) => {
                    setTitleText(e.target.value);
                    setShowSuggest(true);
                  }}
                  onFocus={() => setShowSuggest(true)}
                  onBlur={() => setTimeout(() => setShowSuggest(false), 150)}
                  aria-autocomplete="list"
                  aria-controls="title-suggestions"
                  required
                />
                {showSuggest && suggestions.length > 0 && (
                  <ul className="ac-list" id="title-suggestions" role="listbox">
                    {suggestions.map((s) => (
                      <li key={s.id}>
                        <button type="button" role="option" aria-selected="false" onMouseDown={(e) => e.preventDefault()} onClick={() => { setLinked(s); setTitleText(s.name); setShowSuggest(false); }}>
                          <strong>
                            {s.name} {s.year ? `(${s.year})` : ""}
                          </strong>
                          <span className="small muted">
                            {s.artist ? `${s.artist} · ` : ""}You own: {s.formats.join(", ")}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                <span className="hint">Pick an existing title to link this copy to the formats you already own.</span>
              </div>
            )}
          </div>

          {!linked && category?.has_artist && (
            <div className="field">
              <label htmlFor="artist">Artist</label>
              <input id="artist" className="input" value={artist} onChange={(e) => setArtist(e.target.value)} />
            </div>
          )}
          {!linked && (
            <div className="field">
              <label htmlFor="year">Year (original release)</label>
              <input id="year" className="input" type="number" inputMode="numeric" min={1800} max={2200} value={year} onChange={(e) => setYear(e.target.value)} />
            </div>
          )}

          {format?.physical !== false && (
            <div className="field">
              <label htmlFor="barcode">Barcode</label>
              <div className="input-row">
                <input id="barcode" className="input" inputMode="numeric" autoComplete="off" value={barcode} onChange={(e) => setBarcode(e.target.value)} />
                <button type="button" className="icon-btn" aria-label="Scan barcode" onClick={() => setScanning(true)}>
                  <Icon name="barcode" />
                </button>
              </div>
            </div>
          )}

          <div className="field">
            <label htmlFor="boxset">Box set</label>
            <div className="input-row">
              <select id="boxset" className="input" value={boxSetId ?? ""} onChange={(e) => setBoxSetId(Number(e.target.value) || null)}>
                <option value="">None</option>
                {boxSets.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
              <button type="button" className="btn sm" onClick={newBoxSet}>
                New
              </button>
            </div>
          </div>
        </div>

        {dupes.length > 0 && (
          <div className="notice warn" role="status">
            <strong>This barcode is already in your collection:</strong>{" "}
            {dupes.map((d, n) => (
              <span key={d.id}>
                {n > 0 && ", "}
                <Link to={`/titles/${d.title_id}`}>{d.title}</Link> ({formatById(d.format_id)?.name})
              </span>
            ))}
          </div>
        )}

        {fields.length > 0 && (
          <div className="form-grid">
            {fields.map((f) => (
              <FieldInput
                key={f.key}
                field={f}
                value={custom[f.key]}
                onChange={(v) =>
                  setCustom((c) => {
                    const next = { ...c };
                    if (v === undefined) delete next[f.key];
                    else next[f.key] = v;
                    return next;
                  })
                }
              />
            ))}
          </div>
        )}

        <div className="field">
          <label htmlFor="notes">Notes</label>
          <textarea id="notes" className="input" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>

        <ErrorText error={error} />
        <div className="form-actions">
          <button className="btn primary lg" type="submit" disabled={busy}>
            Save
          </button>
          {!editing && (
            <button className="btn lg" type="button" disabled={busy} onClick={() => save(true)}>
              Save &amp; add another
            </button>
          )}
          <div className="spacer" />
          {format && <FormatBadge format={format} />}
          {editing && (
            <button className="btn danger" type="button" onClick={remove}>
              Delete
            </button>
          )}
        </div>
      </form>

      {scanning && (
        <Scanner
          onClose={() => setScanning(false)}
          onDetected={(code) => {
            setScanning(false);
            setBarcode(code);
          }}
        />
      )}
    </>
  );
}
