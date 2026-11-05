import { useEffect, useState, type FormEvent } from "react";
import { Link, NavLink } from "react-router-dom";
import { api } from "../api";
import { ErrorText, FormatBadge, dateOnly, useToast } from "../components/ui";
import { useApp } from "../state";
import type { Item, WishItem } from "../types";

// ------------------------------------------------------------------ wish list (a simple to-do list)

export function WishList() {
  const { can } = useApp();
  const [items, setItems] = useState<WishItem[] | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = () => api.get<WishItem[]>("/api/wishlist").then(setItems).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const add = async (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    await api.post("/api/wishlist", { text });
    setText("");
    load();
  };
  const toggle = async (w: WishItem) => {
    await api.put(`/api/wishlist/${w.id}`, { done: !w.done });
    load();
  };
  const remove = async (w: WishItem) => {
    await api.del(`/api/wishlist/${w.id}`);
    load();
  };
  const clearDone = async () => {
    await api.post("/api/wishlist/clear-done");
    load();
  };
  const open = items?.filter((w) => !w.done) ?? [];
  const done = items?.filter((w) => w.done) ?? [];

  return (
    <>
      <div className="page-head">
        <div>
          <div className="page-sub">{open.length} still looking for</div>
          <h1 className="page-title">Wish list</h1>
        </div>
      </div>
      {can("editor") && (
        <form className="input-row" onSubmit={add}>
          <label htmlFor="wish" className="visually-hidden">
            Add to wish list
          </label>
          <input id="wish" className="input" placeholder="e.g. Jaws on Laserdisc, better copy of Robocop VHS" value={text} onChange={(e) => setText(e.target.value)} />
          <button className="btn primary" type="submit">
            Add
          </button>
        </form>
      )}
      <ErrorText error={error} />
      <div className="card">
        <ul className="list">
          {[...open, ...done].map((w) => (
            <li key={w.id}>
              <label className="check" style={{ flex: 1 }}>
                <input type="checkbox" checked={!!w.done} disabled={!can("editor")} onChange={() => toggle(w)} />
                <span className={w.done ? "wish-done" : undefined}>{w.text}</span>
              </label>
              <span className="small muted">{dateOnly(w.created_at)}</span>
              {can("editor") && (
                <button className="btn sm ghost" type="button" onClick={() => remove(w)} aria-label={`Delete ${w.text}`}>
                  Delete
                </button>
              )}
            </li>
          ))}
        </ul>
        {items?.length === 0 && <p className="empty">Nothing on the list.</p>}
        {can("editor") && done.length > 0 && (
          <button className="btn sm" type="button" onClick={clearDone} style={{ marginTop: 10 }}>
            Clear {done.length} done
          </button>
        )}
      </div>
    </>
  );
}

// ------------------------------------------------------------------ trash

export function Trash() {
  const { formatById, can } = useApp();
  const toast = useToast();
  const [items, setItems] = useState<Item[] | null>(null);
  const load = () => api.get<Item[]>("/api/trash").then(setItems);
  useEffect(() => {
    load();
  }, []);

  const restore = async (i: Item) => {
    await api.post(`/api/trash/${i.id}/restore`);
    toast(`Restored ${i.title}`);
    load();
  };
  const purge = async (i: Item) => {
    if (!confirm(`Permanently delete ${i.title}? This can't be undone.`)) return;
    await api.del(`/api/trash/${i.id}`);
    load();
  };
  const empty = async () => {
    if (!confirm("Permanently delete everything in the trash? This can't be undone.")) return;
    await api.post("/api/trash/empty");
    load();
  };

  return (
    <>
      <div className="page-head">
        <div>
          <div className="page-sub">Deleted items are kept for 30 days</div>
          <h1 className="page-title">Trash</h1>
        </div>
        {can("admin") && items && items.length > 0 && (
          <button className="btn danger" type="button" onClick={empty}>
            Empty trash
          </button>
        )}
      </div>
      <div className="card flush">
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Format</th>
                <th>Deleted</th>
                <th>
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items?.map((i) => (
                <tr key={i.id}>
                  <td>{i.title}</td>
                  <td>
                    <FormatBadge format={formatById(i.format_id)} />
                  </td>
                  <td className="muted">{dateOnly(i.deleted_at)}</td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    {can("editor") && (
                      <button className="btn sm" type="button" onClick={() => restore(i)}>
                        Restore
                      </button>
                    )}{" "}
                    {can("admin") && (
                      <button className="btn sm danger" type="button" onClick={() => purge(i)}>
                        Delete forever
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {items?.length === 0 && <div className="empty">The trash is empty.</div>}
        </div>
      </div>
    </>
  );
}

// ------------------------------------------------------------------ "More" menu (phone)

export function More() {
  const { user } = useApp();
  const links: [string, string][] = [
    ["/wishlist", "Wish list"],
    ["/boxsets", "Box sets"],
    ["/trash", "Trash"],
    ["/settings", "Settings"],
  ];
  return (
    <>
      <div className="page-head">
        <div>
          <div className="page-sub">
            Signed in as {user?.display_name} ({user?.role})
          </div>
          <h1 className="page-title">More</h1>
        </div>
      </div>
      <div className="card">
        <ul className="list">
          {links.map(([to, label]) => (
            <li key={to}>
              <NavLink to={to} style={{ flex: 1, fontWeight: 700, fontSize: 18, textDecoration: "none", padding: "6px 0" }}>
                {label} →
              </NavLink>
            </li>
          ))}
          <li>
            <SignOutLink />
          </li>
        </ul>
      </div>
    </>
  );
}

function SignOutLink() {
  const { setUser } = useApp();
  return (
    <Link
      to="/"
      style={{ flex: 1, fontWeight: 700, fontSize: 18, textDecoration: "none", padding: "6px 0" }}
      onClick={async () => {
        await api.post("/api/auth/logout").catch(() => {});
        setUser(null);
      }}
    >
      Sign out
    </Link>
  );
}
