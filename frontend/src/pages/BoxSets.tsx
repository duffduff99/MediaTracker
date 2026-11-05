import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, qs } from "../api";
import { ConditionSticker, ErrorText, FormatBadge, Modal, useToast } from "../components/ui";
import { useApp } from "../state";
import type { BoxSet } from "../types";
import { search_norm } from "../util";

export function BoxSetList() {
  const { can } = useApp();
  const navigate = useNavigate();
  const [sets, setSets] = useState<BoxSet[] | null>(null);
  const [filter, setFilter] = useState("");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    api.get<BoxSet[]>("/api/boxsets").then(setSets).catch(() => setSets([]));
  }, []);

  const shown = (sets ?? []).filter((b) => search_norm(b.name).includes(search_norm(filter)));

  return (
    <>
      <div className="page-head">
        <div>
          <div className="page-sub">Collections sold as one package</div>
          <h1 className="page-title">Box sets</h1>
        </div>
        {can("editor") && (
          <button className="btn accent" type="button" onClick={() => setCreating(true)}>
            + New box set
          </button>
        )}
      </div>
      <div className="field" style={{ maxWidth: 420 }}>
        <label htmlFor="bs-filter">Filter</label>
        <input id="bs-filter" className="input" value={filter} onChange={(e) => setFilter(e.target.value)} />
      </div>
      <div className="card flush">
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Items</th>
                <th>Barcode</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((b) => (
                <tr key={b.id}>
                  <td className="title-cell">
                    <Link to={`/boxsets/${b.id}`}>{b.name}</Link>
                  </td>
                  <td className="num">{b.count}</td>
                  <td className="mono">{b.barcode}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {sets && shown.length === 0 && <div className="empty">No box sets yet.</div>}
        </div>
      </div>
      {creating && <BoxSetEditor onClose={() => setCreating(false)} onSaved={(b) => navigate(`/boxsets/${b.id}`)} />}
    </>
  );
}

export function BoxSetPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { formatById, can } = useApp();
  const [box, setBox] = useState<BoxSet | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    api.get<BoxSet>(`/api/boxsets/${id}`).then(setBox).catch((e) => setError(e.message));
  }, [id]);

  if (error) return <ErrorText error={error} />;
  if (!box) return <p className="status-line">LOADING…</p>;

  const removeItem = async (itemId: number) => {
    setBox(await api.del<BoxSet>(`/api/boxsets/${box.id}/items/${itemId}`));
    toast("Removed from the box set (the item is still in your collection)");
  };
  const deleteSet = async () => {
    if (!confirm("Delete this box set? The items in it stay in your collection.")) return;
    await api.del(`/api/boxsets/${box.id}`);
    navigate("/boxsets");
  };

  return (
    <>
      <div className="detail-head">
        <div>
          <div className="page-sub">Box set · {box.items?.length ?? 0} items</div>
          <h1 className="page-title">{box.name}</h1>
          {box.barcode && <div className="mono muted">{box.barcode}</div>}
        </div>
        {can("editor") && (
          <div className="row">
            <Link className="btn accent" to={`/items/new${qs({ box_set_id: box.id })}`}>
              + Add item to set
            </Link>
            <button className="btn" type="button" onClick={() => setEditing(true)}>
              Edit
            </button>
            <button className="btn danger" type="button" onClick={deleteSet}>
              Delete set
            </button>
          </div>
        )}
      </div>
      {box.notes && <p className="notice" style={{ whiteSpace: "pre-line" }}>{box.notes}</p>}
      <div className="card flush">
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Year</th>
                <th>Format</th>
                <th>Condition</th>
                <th>
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {box.items?.map((i) => (
                <tr key={i.id}>
                  <td className="title-cell">
                    <Link to={`/titles/${i.title_id}`}>{i.title}</Link>
                  </td>
                  <td className="num">{i.year ?? ""}</td>
                  <td>
                    <FormatBadge format={formatById(i.format_id)} />
                  </td>
                  <td>
                    <ConditionSticker value={i.custom.condition} small />
                  </td>
                  <td>
                    {can("editor") && (
                      <button className="btn sm ghost" type="button" onClick={() => removeItem(i.id)}>
                        Remove
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {box.items?.length === 0 && <div className="empty">Nothing in this set yet.</div>}
        </div>
      </div>
      {editing && <BoxSetEditor box={box} onClose={() => setEditing(false)} onSaved={(b) => { setBox(b); setEditing(false); }} />}
    </>
  );
}

function BoxSetEditor({ box, onClose, onSaved }: { box?: BoxSet; onClose: () => void; onSaved: (b: BoxSet) => void }) {
  const [name, setName] = useState(box?.name ?? "");
  const [barcode, setBarcode] = useState(box?.barcode ?? "");
  const [notes, setNotes] = useState(box?.notes ?? "");
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const body = { name, barcode: barcode || null, notes: notes || null };
      onSaved(box ? await api.put<BoxSet>(`/api/boxsets/${box.id}`, body) : await api.post<BoxSet>("/api/boxsets", body));
    } catch (err) {
      setError((err as Error).message);
    }
  };
  return (
    <Modal title={box ? "Edit box set" : "New box set"} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <div className="field">
          <label htmlFor="bs-name">Name</label>
          <input id="bs-name" className="input" value={name} onChange={(e) => setName(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="bs-barcode">Barcode (on the outer box)</label>
          <input id="bs-barcode" className="input" inputMode="numeric" value={barcode} onChange={(e) => setBarcode(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="bs-notes">Notes</label>
          <textarea id="bs-notes" className="input" value={notes} onChange={(e) => setNotes(e.target.value)} />
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
