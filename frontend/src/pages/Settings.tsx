import { useEffect, useState, type FormEvent } from "react";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import { api } from "../api";
import { ErrorText, FormatBadge, Icon, Modal, useToast } from "../components/ui";
import { applyTheme, useApp } from "../state";
import type { Category, Field, FieldType, Format, Meta, Role, User } from "../types";

export function Settings() {
  const { can } = useApp();
  return (
    <>
      <div className="page-head">
        <h1 className="page-title">Settings</h1>
      </div>
      <nav className="tabs" aria-label="Settings sections">
        <NavLink to="/settings" end>My account</NavLink>
        {can("admin") && <NavLink to="/settings/fields">Columns</NavLink>}
        {can("admin") && <NavLink to="/settings/media">Media types</NavLink>}
        {can("admin") && <NavLink to="/settings/users">Users</NavLink>}
        <NavLink to="/settings/data">Import &amp; export</NavLink>
      </nav>
      <Routes>
        <Route index element={<Account />} />
        {can("admin") && <Route path="fields" element={<Fields />} />}
        {can("admin") && <Route path="media" element={<MediaTypes />} />}
        {can("admin") && <Route path="users" element={<Users />} />}
        <Route path="data" element={<DataTools />} />
      </Routes>
    </>
  );
}

// ------------------------------------------------------------------ account

function Account() {
  const { user, savePrefs } = useApp();
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState<string | null>(null);
  const theme = user?.prefs.theme ?? "system";

  const change = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await api.post("/api/auth/password", { current_password: current, new_password: next });
      setCurrent("");
      setNext("");
      toast("Password changed");
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="grid-2">
      <div className="card form">
        <h2 className="card-title">You</h2>
        <dl className="kv">
          <dt>Name</dt>
          <dd>{user?.display_name}</dd>
          <dt>Username</dt>
          <dd>{user?.username}</dd>
          <dt>Role</dt>
          <dd>{user?.role}</dd>
        </dl>
        <div className="field">
          <label htmlFor="theme">Appearance</label>
          <select
            id="theme"
            className="input"
            value={theme}
            onChange={(e) => {
              const t = e.target.value as "system" | "light" | "dark";
              applyTheme(t);
              savePrefs({ theme: t });
            }}
          >
            <option value="system">Match this device</option>
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </select>
        </div>
        <Link to="/trash" className="btn" style={{ alignSelf: "flex-start" }}>
          Open trash
        </Link>
      </div>
      <form className="card form" onSubmit={change}>
        <h2 className="card-title">Change password</h2>
        <div className="field">
          <label htmlFor="cur">Current password</label>
          <input id="cur" className="input" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="new">New password (10+ characters)</label>
          <input id="new" className="input" type="password" autoComplete="new-password" minLength={10} value={next} onChange={(e) => setNext(e.target.value)} required />
        </div>
        <ErrorText error={error} />
        <button className="btn primary" type="submit" style={{ alignSelf: "flex-start" }}>
          Change password
        </button>
      </form>
    </div>
  );
}

// ------------------------------------------------------------------ columns (custom fields)

const TYPE_LABEL: Record<FieldType, string> = {
  text: "Text",
  longtext: "Long text",
  number: "Number",
  boolean: "Yes/No",
  select: "Dropdown",
  multiselect: "Multiple choice",
  date: "Date",
};

function Fields() {
  const { meta, setMeta, formatById } = useApp();
  const [editing, setEditing] = useState<Field | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!meta) return null;

  const move = async (idx: number, dir: -1 | 1) => {
    const ids = meta.fields.map((f) => f.id);
    const j = idx + dir;
    if (j < 0 || j >= ids.length) return;
    [ids[idx], ids[j]] = [ids[j], ids[idx]];
    setMeta(await api.put<Meta>("/api/fields-order", { ids }));
  };
  const remove = async (f: Field) => {
    if (!confirm(`Delete the “${f.label}” column? Its values on every item are deleted too. This can't be undone.`)) return;
    try {
      setMeta(await api.del<Meta>(`/api/fields/${f.id}`));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <>
      <div className="card">
        <h2 className="card-title">Built-in columns</h2>
        <p className="muted">
          Title, Artist (music only), Year, Format, Barcode, Box set and Notes are always available and can't be removed. You can hide any of them in the
          Search grid.
        </p>
      </div>
      <div className="card flush">
        <div className="row" style={{ padding: "14px 18px 4px" }}>
          <h2 className="card-title" style={{ margin: 0, padding: 0 }}>
            Your columns
          </h2>
          <div className="spacer" />
          <button className="btn accent sm" type="button" onClick={() => setEditing("new")}>
            + Add column
          </button>
        </div>
        <ErrorText error={error} />
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Order</th>
                <th>Column</th>
                <th>Type</th>
                <th>Shown for</th>
                <th>
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {meta.fields.map((f, idx) => (
                <tr key={f.id}>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button className="icon-btn" type="button" aria-label={`Move ${f.label} up`} onClick={() => move(idx, -1)} disabled={idx === 0}>
                      <Icon name="up" size={16} />
                    </button>{" "}
                    <button className="icon-btn" type="button" aria-label={`Move ${f.label} down`} onClick={() => move(idx, 1)} disabled={idx === meta.fields.length - 1}>
                      <Icon name="down" size={16} />
                    </button>
                  </td>
                  <td>
                    <strong>{f.label}</strong>
                    {f.options.length > 0 && <div className="small muted">{f.options.join(" · ")}</div>}
                  </td>
                  <td>{TYPE_LABEL[f.type]}</td>
                  <td>
                    {f.applies_all ? (
                      "All formats"
                    ) : (
                      <div className="chips">
                        {f.format_ids.map((id) => (
                          <FormatBadge key={id} format={formatById(id)} />
                        ))}
                      </div>
                    )}
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button className="btn sm" type="button" onClick={() => setEditing(f)}>
                      Edit
                    </button>{" "}
                    <button className="btn sm danger" type="button" onClick={() => remove(f)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {editing && <FieldEditor field={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function FieldEditor({ field, onClose }: { field: Field | null; onClose: () => void }) {
  const { meta, setMeta } = useApp();
  const [label, setLabel] = useState(field?.label ?? "");
  const [type, setType] = useState<FieldType>(field?.type ?? "text");
  const [options, setOptions] = useState<{ orig: string | null; value: string }[]>(
    (field?.options ?? []).map((o) => ({ orig: o, value: o }))
  );
  const [appliesAll, setAppliesAll] = useState(field?.applies_all ?? false);
  const [formatIds, setFormatIds] = useState<number[]>(field?.format_ids ?? []);
  const [error, setError] = useState<string | null>(null);
  const hasOptions = type === "select" || type === "multiselect";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const opts = options.map((o) => o.value.trim()).filter(Boolean);
    try {
      if (field) {
        const renames = Object.fromEntries(
          options.filter((o) => o.orig && o.value.trim() && o.orig !== o.value.trim()).map((o) => [o.orig as string, o.value.trim()])
        );
        setMeta(await api.put<Meta>(`/api/fields/${field.id}`, { label, options: opts, renames, applies_all: appliesAll, format_ids: formatIds }));
      } else {
        setMeta(await api.post<Meta>("/api/fields", { label, type, options: opts, applies_all: appliesAll, format_ids: formatIds }));
      }
      onClose();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const toggleFormat = (id: number, on: boolean) => setFormatIds((ids) => (on ? [...new Set([...ids, id])] : ids.filter((x) => x !== id)));

  return (
    <Modal title={field ? `Edit “${field.label}”` : "Add column"} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <div className="field">
          <label htmlFor="fe-label">Name</label>
          <input id="fe-label" className="input" value={label} onChange={(e) => setLabel(e.target.value)} required maxLength={60} />
        </div>
        <div className="field">
          <label htmlFor="fe-type">Type</label>
          <select id="fe-type" className="input" value={type} disabled={!!field} onChange={(e) => setType(e.target.value as FieldType)}>
            {Object.entries(TYPE_LABEL).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
          {field && <span className="hint">The type can't change after a column is created.</span>}
        </div>
        {hasOptions && (
          <div className="field">
            <span className="field-label">Options</span>
            {field?.key === "condition" && <span className="hint">Order these best to worst; the first shows teal and the last red.</span>}
            {options.map((o, i) => (
              <div className="input-row" key={i}>
                <label className="visually-hidden" htmlFor={`opt-${i}`}>
                  Option {i + 1}
                </label>
                <input
                  id={`opt-${i}`}
                  className="input"
                  value={o.value}
                  onChange={(e) => setOptions((all) => all.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))}
                />
                <button type="button" className="icon-btn" aria-label="Move up" disabled={i === 0} onClick={() => setOptions((all) => { const n = [...all]; [n[i - 1], n[i]] = [n[i], n[i - 1]]; return n; })}>
                  <Icon name="up" size={16} />
                </button>
                <button type="button" className="icon-btn" aria-label="Remove option" onClick={() => setOptions((all) => all.filter((_, j) => j !== i))}>
                  <Icon name="close" size={16} />
                </button>
              </div>
            ))}
            <button type="button" className="btn sm" style={{ alignSelf: "flex-start" }} onClick={() => setOptions((all) => [...all, { orig: null, value: "" }])}>
              + Add option
            </button>
            {field && <span className="hint">Renaming an option updates every item that uses it. Removing one leaves existing values as they are.</span>}
          </div>
        )}
        <div className="field">
          <span className="field-label">Show this column for</span>
          <label className="check">
            <input type="radio" name="applies" checked={appliesAll} onChange={() => setAppliesAll(true)} /> All formats (including ones added later)
          </label>
          <label className="check">
            <input type="radio" name="applies" checked={!appliesAll} onChange={() => setAppliesAll(false)} /> Only these formats:
          </label>
          {!appliesAll &&
            meta?.categories.map((c) => {
              const fmts = meta.formats.filter((f) => f.category_id === c.id);
              const allOn = fmts.length > 0 && fmts.every((f) => formatIds.includes(f.id));
              return (
                <fieldset key={c.id} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "6px 12px" }}>
                  <legend>
                    <label className="check">
                      <input type="checkbox" checked={allOn} onChange={(e) => fmts.forEach((f) => toggleFormat(f.id, e.target.checked))} />
                      <strong>{c.name}</strong>
                    </label>
                  </legend>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "0 16px" }}>
                    {fmts.map((f) => (
                      <label key={f.id} className="check">
                        <input type="checkbox" checked={formatIds.includes(f.id)} onChange={(e) => toggleFormat(f.id, e.target.checked)} />
                        {f.name}
                      </label>
                    ))}
                  </div>
                </fieldset>
              );
            })}
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

// ------------------------------------------------------------------ media types

function MediaTypes() {
  const { meta, setMeta, categoryById } = useApp();
  const [editing, setEditing] = useState<Format | "new" | null>(null);
  const [catEditing, setCatEditing] = useState<Category | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!meta) return null;

  const move = async (f: Format, dir: -1 | 1) => {
    const list = [...meta.formats];
    const i = list.findIndex((x) => x.id === f.id);
    const j = i + dir;
    if (j < 0 || j >= list.length) return;
    [list[i], list[j]] = [list[j], list[i]];
    let latest: Meta = meta;
    for (let k = 0; k < list.length; k++) {
      if (list[k].sort_order !== k) latest = await api.put<Meta>(`/api/formats/${list[k].id}`, { ...list[k], sort_order: k });
    }
    setMeta(latest);
  };
  const removeFormat = async (f: Format) => {
    if (!confirm(`Delete the “${f.name}” format?`)) return;
    try {
      setMeta(await api.del<Meta>(`/api/formats/${f.id}`));
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const removeCategory = async (c: Category) => {
    if (!confirm(`Delete the “${c.name}” category?`)) return;
    try {
      setMeta(await api.del<Meta>(`/api/categories/${c.id}`));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <>
      <ErrorText error={error} />
      <div className="card flush">
        <div className="row" style={{ padding: "14px 18px 4px" }}>
          <h2 className="card-title" style={{ margin: 0, padding: 0 }}>
            Formats
          </h2>
          <div className="spacer" />
          <button className="btn accent sm" type="button" onClick={() => setEditing("new")}>
            + Add format
          </button>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Order</th>
                <th>Format</th>
                <th>Category</th>
                <th>Physical</th>
                <th>
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {meta.formats.map((f, idx) => (
                <tr key={f.id}>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button className="icon-btn" type="button" aria-label={`Move ${f.name} up`} disabled={idx === 0} onClick={() => move(f, -1)}>
                      <Icon name="up" size={16} />
                    </button>{" "}
                    <button className="icon-btn" type="button" aria-label={`Move ${f.name} down`} disabled={idx === meta.formats.length - 1} onClick={() => move(f, 1)}>
                      <Icon name="down" size={16} />
                    </button>
                  </td>
                  <td>
                    <FormatBadge format={f} />
                  </td>
                  <td>{categoryById(f.category_id)?.name}</td>
                  <td>{f.physical ? "Yes" : "No (digital)"}</td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button className="btn sm" type="button" onClick={() => setEditing(f)}>
                      Edit
                    </button>{" "}
                    <button className="btn sm danger" type="button" onClick={() => removeFormat(f)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="row">
          <h2 className="card-title" style={{ margin: 0 }}>
            Categories
          </h2>
          <div className="spacer" />
          <button className="btn sm" type="button" onClick={() => setCatEditing("new")}>
            + Add category
          </button>
        </div>
        <p className="hint">Copies are only linked as the same title within a category, so a movie and its video game stay separate.</p>
        <ul className="list">
          {meta.categories.map((c) => (
            <li key={c.id}>
              <strong style={{ flex: 1 }}>{c.name}</strong>
              <span className="small muted">{c.has_artist ? "Has Artist" : ""}</span>
              <button className="btn sm" type="button" onClick={() => setCatEditing(c)}>
                Edit
              </button>
              <button className="btn sm danger" type="button" onClick={() => removeCategory(c)}>
                Delete
              </button>
            </li>
          ))}
        </ul>
      </div>
      {editing && <FormatEditor format={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
      {catEditing && <CategoryEditor category={catEditing === "new" ? null : catEditing} onClose={() => setCatEditing(null)} />}
    </>
  );
}

function FormatEditor({ format, onClose }: { format: Format | null; onClose: () => void }) {
  const { meta, setMeta } = useApp();
  const [name, setName] = useState(format?.name ?? "");
  const [categoryId, setCategoryId] = useState(format?.category_id ?? meta?.categories[0]?.id ?? 0);
  const [color, setColor] = useState(format?.color ?? "#55504a");
  const [physical, setPhysical] = useState(format?.physical ?? true);
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const body = { name, category_id: categoryId, color, physical, sort_order: format?.sort_order ?? (meta?.formats.length ?? 0) };
    try {
      setMeta(format ? await api.put<Meta>(`/api/formats/${format.id}`, body) : await api.post<Meta>("/api/formats", body));
      onClose();
    } catch (err) {
      setError((err as Error).message);
    }
  };
  return (
    <Modal title={format ? `Edit ${format.name}` : "Add format"} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <div className="field">
          <label htmlFor="fm-name">Name</label>
          <input id="fm-name" className="input" value={name} onChange={(e) => setName(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="fm-cat">Category</label>
          <select id="fm-cat" className="input" value={categoryId} onChange={(e) => setCategoryId(Number(e.target.value))}>
            {meta?.categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="fm-color">Label colour</label>
          <div className="row">
            <input id="fm-color" type="color" value={color} onChange={(e) => setColor(e.target.value)} style={{ width: 56, height: 40, border: "none", background: "none" }} />
            <FormatBadge format={{ id: 0, name: name || "Preview", category_id: categoryId, color, physical, sort_order: 0 }} />
          </div>
          <span className="hint">Tip: use the colour of the real case (Blu-ray blue, HD DVD red…).</span>
        </div>
        <label className="check">
          <input type="checkbox" checked={physical} onChange={(e) => setPhysical(e.target.checked)} /> Physical media (untick for digital copies)
        </label>
        {!format && <p className="hint">After adding it, choose which columns apply to it under Columns.</p>}
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

function CategoryEditor({ category, onClose }: { category: Category | null; onClose: () => void }) {
  const { meta, setMeta } = useApp();
  const [name, setName] = useState(category?.name ?? "");
  const [hasArtist, setHasArtist] = useState(category?.has_artist ?? false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const body = { name, has_artist: hasArtist, sort_order: category?.sort_order ?? meta?.categories.length ?? 0 };
    try {
      setMeta(category ? await api.put<Meta>(`/api/categories/${category.id}`, body) : await api.post<Meta>("/api/categories", body));
      onClose();
    } catch (err) {
      setError((err as Error).message);
    }
  };
  return (
    <Modal title={category ? `Edit ${category.name}` : "Add category"} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <div className="field">
          <label htmlFor="cat-name">Name</label>
          <input id="cat-name" className="input" value={name} onChange={(e) => setName(e.target.value)} required />
        </div>
        <label className="check">
          <input type="checkbox" checked={hasArtist} onChange={(e) => setHasArtist(e.target.checked)} /> Titles have an Artist (music)
        </label>
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

// ------------------------------------------------------------------ users

function Users() {
  const { user: me } = useApp();
  const toast = useToast();
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ username: "", display_name: "", role: "viewer" as Role, password: "" });
  const load = () => api.get<User[]>("/api/users").then(setUsers).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const add = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await api.post("/api/users", form);
      setForm({ username: "", display_name: "", role: "viewer", password: "" });
      toast("User added");
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  };
  const setRole = async (u: User, role: Role) => {
    try {
      await api.put(`/api/users/${u.id}`, { role });
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  };
  const resetPassword = async (u: User) => {
    const pw = prompt(`New password for ${u.display_name} (10+ characters)`);
    if (!pw) return;
    try {
      await api.put(`/api/users/${u.id}`, { password: pw });
      toast("Password reset");
    } catch (err) {
      setError((err as Error).message);
    }
  };
  const remove = async (u: User) => {
    if (!confirm(`Delete ${u.display_name}'s account?`)) return;
    try {
      await api.del(`/api/users/${u.id}`);
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <>
      <div className="card">
        <h2 className="card-title">Roles</h2>
        <p className="muted small" style={{ margin: 0 }}>
          <strong>Viewer</strong>: search, browse and export. <strong>Editor</strong>: also add, edit and delete items, box sets and the wish list.{" "}
          <strong>Admin</strong>: also manages columns, media types, users, import and the trash.
        </p>
      </div>
      <ErrorText error={error} />
      <div className="card flush">
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Username</th>
                <th>Role</th>
                <th>Last sign-in</th>
                <th>
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>{u.display_name}</td>
                  <td>{u.username}</td>
                  <td>
                    <label className="visually-hidden" htmlFor={`role-${u.id}`}>
                      Role for {u.display_name}
                    </label>
                    <select id={`role-${u.id}`} className="input" style={{ minHeight: 36, width: "auto" }} value={u.role} disabled={u.id === me?.id} onChange={(e) => setRole(u, e.target.value as Role)}>
                      <option value="viewer">Viewer</option>
                      <option value="editor">Editor</option>
                      <option value="admin">Admin</option>
                    </select>
                  </td>
                  <td className="muted small">{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "Never"}</td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button className="btn sm" type="button" onClick={() => resetPassword(u)}>
                      Reset password
                    </button>{" "}
                    {u.id !== me?.id && (
                      <button className="btn sm danger" type="button" onClick={() => remove(u)}>
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <form className="card form" onSubmit={add}>
        <h2 className="card-title">Add a user</h2>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="nu-name">Name</label>
            <input id="nu-name" className="input" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} required />
          </div>
          <div className="field">
            <label htmlFor="nu-user">Username</label>
            <input id="nu-user" className="input" autoCapitalize="none" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required pattern="[A-Za-z0-9._@-]+" />
          </div>
          <div className="field">
            <label htmlFor="nu-role">Role</label>
            <select id="nu-role" className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
              <option value="viewer">Viewer</option>
              <option value="editor">Editor</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="nu-pw">Password (10+ characters)</label>
            <input id="nu-pw" className="input" type="password" autoComplete="new-password" minLength={10} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
          </div>
        </div>
        <button className="btn primary" type="submit" style={{ alignSelf: "flex-start" }}>
          Add user
        </button>
      </form>
    </>
  );
}

// ------------------------------------------------------------------ import, export, backup

interface ImportReport {
  committed: boolean;
  counts: Record<string, number>;
  lists: Record<string, string[]>;
  warnings: string[];
}

const REPORT_LABELS: [string, string][] = [
  ["items_created", "Items to import"],
  ["skipped_already_imported", "Already imported (skipped)"],
  ["titles_created", "Titles"],
  ["titles_in_multiple_formats", "Titles owned in 2+ formats"],
  ["box_sets_created", "Box sets"],
  ["titles_cleaned", "Titles tidied (e.g. “Mask, The” → “The Mask”)"],
  ["barcodes_leading_zero_restored", "Barcodes with lost leading zero restored"],
  ["barcodes_addon_trimmed", "Barcodes with 2-digit add-on trimmed"],
  ["barcodes_need_rescan", "Barcodes corrupted in Jira — tagged “Re-scan barcode”"],
  ["barcodes_unverified", "Barcodes kept but failing the check digit"],
  ["catalog_numbers_moved", "Catalog numbers moved out of Barcode"],
  ["year_differences_merged", "Same title with different years — linked (earliest year kept)"],
  ["same_name_kept_separate", "Same name but years 10+ apart — kept separate"],
  ["linked_by_jira_relates", "Linked using your Jira “Relates” links"],
  ["possible_box_sets", "Possible box sets (several titles share a barcode)"],
  ["options_added", "Dropdown options added"],
  ["formats_created", "Formats created"],
];

function DataTools() {
  const { can, refreshMeta } = useApp();
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (commit: boolean) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await api.post<ImportReport>(`/api/import/jira?commit=${commit}`, fd);
      setReport(r);
      if (commit) {
        await refreshMeta();
        toast(`Imported ${r.counts.items_created ?? 0} items`);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <div className="card form">
        <h2 className="card-title">Export</h2>
        <p className="muted" style={{ margin: 0 }}>
          The Excel file has a summary sheet, an “All items” sheet and one sheet per format with only that format's columns. It's set up to print
          landscape, one page wide. To export a filtered list, use the CSV and Excel buttons in the Search grid.
        </p>
        <div className="row">
          <a className="btn" href="/api/export.xlsx" download>
            <Icon name="download" size={16} /> Everything (Excel)
          </a>
          <a className="btn" href="/api/export.csv" download>
            <Icon name="download" size={16} /> Everything (CSV)
          </a>
        </div>
      </div>

      {can("admin") && (
        <div className="card form">
          <h2 className="card-title">Import from Jira</h2>
          <p className="muted" style={{ margin: 0 }}>
            Upload the CSV exported from Jira. First run a preview: nothing is saved until you press Import. Items already imported are skipped, so it's safe
            to run again.
          </p>
          <div className="field">
            <label htmlFor="jira-file">Jira CSV file</label>
            <input
              id="jira-file"
              className="input"
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null);
                setReport(null);
              }}
            />
          </div>
          <div className="row">
            <button className="btn" type="button" disabled={!file || busy} onClick={() => run(false)}>
              {busy ? "Working…" : "Preview"}
            </button>
            {report && !report.committed && (
              <button className="btn primary" type="button" disabled={busy} onClick={() => run(true)}>
                Import {report.counts.items_created ?? 0} items
              </button>
            )}
          </div>
          <ErrorText error={error} />
          {report && (
            <div className={report.committed ? "notice" : "notice warn"}>
              <strong>{report.committed ? "Import finished." : "Preview — nothing has been saved yet."}</strong>
              {REPORT_LABELS.filter(([k]) => report.counts[k]).map(([k, label]) => (
                <details key={k} style={{ marginTop: 8 }}>
                  <summary>
                    {label}: <strong>{report.counts[k].toLocaleString()}</strong>
                  </summary>
                  {report.lists[k] && (
                    <ul className="report-list">
                      {report.lists[k].map((line, i) => (
                        <li key={i}>{line}</li>
                      ))}
                    </ul>
                  )}
                </details>
              ))}
              {report.warnings.length > 0 && (
                <details style={{ marginTop: 8 }}>
                  <summary>Warnings: {report.warnings.length}</summary>
                  <ul className="report-list">
                    {report.warnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                </details>
              )}
              <p className="small muted">Watched / Unwatched / Replace statuses are not imported.</p>
            </div>
          )}
        </div>
      )}

      {can("admin") && (
        <div className="card form">
          <h2 className="card-title">Backup</h2>
          <p className="muted" style={{ margin: 0 }}>
            A copy of the database is saved automatically every night (the last 14 are kept in the data volume's <code>backups</code> folder). You can also
            download one now.
          </p>
          <a className="btn" href="/api/admin/backup" download style={{ alignSelf: "flex-start" }}>
            <Icon name="download" size={16} /> Download backup
          </a>
        </div>
      )}
    </div>
  );
}
