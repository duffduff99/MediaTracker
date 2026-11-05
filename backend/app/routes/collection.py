"""The collection itself: items (physical copies), titles, box sets, search, stats, trash, wish list."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import text
from ..db import now, tx
from ..security import current_user, get_db, require
from ..services import (
    clean_custom,
    delete_orphan_titles,
    fetch_items,
    filter_items,
    find_or_create_title,
    resolve_category,
    get_item,
    load_meta,
)

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ items


class ItemIn(BaseModel):
    title_id: int | None = None
    title: str | None = Field(default=None, max_length=300)
    year: int | None = Field(default=None, ge=1800, le=2200)
    artist: str | None = Field(default=None, max_length=300)
    format_id: int
    category_id: int | None = None  # only needed for a new title when the format has several categories
    barcode: str | None = Field(default=None, max_length=64)
    box_set_id: int | None = None
    notes: str | None = Field(default=None, max_length=5000)
    custom: dict = {}


def _resolve_title(conn: sqlite3.Connection, body: ItemIn) -> int:
    category_id = resolve_category(conn, body.format_id, body.title_id, body.category_id)
    if body.title_id:
        return body.title_id
    return find_or_create_title(conn, body.title or "", category_id, body.year, body.artist)


def _check_box_set(conn: sqlite3.Connection, box_set_id: int | None) -> None:
    if box_set_id and not conn.execute("SELECT 1 FROM box_sets WHERE id = ?", (box_set_id,)).fetchone():
        raise HTTPException(400, "Unknown box set.")


@router.get("/items")
def list_items(
    q: str | None = None,
    format_id: list[int] = Query(default=[]),
    category_id: int | None = None,
    box_set_id: int | None = None,
    _=Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    meta = load_meta(conn)
    items = fetch_items(conn)
    if format_id:
        items = [i for i in items if i["format_id"] in format_id]
    if category_id:
        items = [i for i in items if i["category_id"] == category_id]
    if box_set_id:
        items = [i for i in items if i["box_set_id"] == box_set_id]
    items = filter_items(items, q, meta["formats"])
    items.sort(key=lambda i: (i["sort_title"], i["year"] or 0, i["format_id"]))
    return items


@router.get("/items/{item_id}")
def read_item(item_id: int, _=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return get_item(conn, item_id)


@router.post("/items")
def create_item(body: ItemIn, user=Depends(require("editor")), conn: sqlite3.Connection = Depends(get_db)):
    meta = load_meta(conn)
    _check_box_set(conn, body.box_set_id)
    custom = clean_custom(meta["fields"], body.format_id, body.custom)
    ts = now()
    with tx(conn):
        title_id = _resolve_title(conn, body)
        cur = conn.execute(
            """INSERT INTO items (title_id, format_id, barcode, box_set_id, notes, custom, added_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (title_id, body.format_id, (body.barcode or "").strip() or None, body.box_set_id,
             (body.notes or "").strip() or None, json.dumps(custom), user["display_name"], ts, ts),
        )
    return get_item(conn, cur.lastrowid)


@router.put("/items/{item_id}")
def update_item(item_id: int, body: ItemIn, _=Depends(require("editor")), conn: sqlite3.Connection = Depends(get_db)):
    get_item(conn, item_id)
    meta = load_meta(conn)
    _check_box_set(conn, body.box_set_id)
    custom = clean_custom(meta["fields"], body.format_id, body.custom)
    with tx(conn):
        title_id = _resolve_title(conn, body)
        conn.execute(
            """UPDATE items SET title_id = ?, format_id = ?, barcode = ?, box_set_id = ?, notes = ?, custom = ?,
               updated_at = ? WHERE id = ?""",
            (title_id, body.format_id, (body.barcode or "").strip() or None, body.box_set_id,
             (body.notes or "").strip() or None, json.dumps(custom), now(), item_id),
        )
        delete_orphan_titles(conn)
    return get_item(conn, item_id)


@router.delete("/items/{item_id}")
def delete_item(item_id: int, _=Depends(require("editor")), conn: sqlite3.Connection = Depends(get_db)):
    get_item(conn, item_id)
    conn.execute("UPDATE items SET deleted_at = ? WHERE id = ?", (now(), item_id))
    return {"ok": True}


class IdsIn(BaseModel):
    ids: list[int] = Field(max_length=10000)


@router.post("/items/bulk-delete")
def bulk_delete(body: IdsIn, _=Depends(require("editor")), conn: sqlite3.Connection = Depends(get_db)):
    ts = now()
    with tx(conn):
        for i in body.ids:
            conn.execute("UPDATE items SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL", (ts, i))
    return {"ok": True, "count": len(body.ids)}


@router.post("/items/{item_id}/split")
def split_item(item_id: int, _=Depends(require("editor")), conn: sqlite3.Connection = Depends(get_db)):
    """Detach a copy into its own new title (for copies that were matched to the wrong title)."""
    item = get_item(conn, item_id)
    t = conn.execute("SELECT * FROM titles WHERE id = ?", (item["title_id"],)).fetchone()
    ts = now()
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO titles (category_id, name, match_key, artist, year, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (t["category_id"], t["name"], t["match_key"], t["artist"], t["year"], ts, ts),
        )
        conn.execute("UPDATE items SET title_id = ?, updated_at = ? WHERE id = ?", (cur.lastrowid, ts, item_id))
        delete_orphan_titles(conn)
    return get_item(conn, item_id)


# ------------------------------------------------------------------ titles


@router.get("/titles")
def search_titles(
    q: str = "", category_id: int | None = None, limit: int = Query(default=10, le=50),
    _=Depends(current_user), conn: sqlite3.Connection = Depends(get_db),
):
    toks = text.tokens(q)
    if not toks:
        return []
    rows = conn.execute("SELECT * FROM titles" + (" WHERE category_id = ?" if category_id else ""),
                        (category_id,) if category_id else ()).fetchall()
    fmt_names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM formats")}
    formats_by_title: dict[int, list[str]] = defaultdict(list)
    for r in conn.execute("SELECT title_id, format_id FROM items WHERE deleted_at IS NULL"):
        formats_by_title[r["title_id"]].append(fmt_names.get(r["format_id"], "?"))
    q_norm = text.search_norm(q)
    hits = []
    for r in rows:
        if r["id"] not in formats_by_title:
            continue
        hay = text.search_norm(f"{r['name']} {r['artist'] or ''}")
        if text.matches(hay, toks):
            starts = text.sort_name(r["name"]).startswith(text.sort_name(q_norm))
            hits.append((0 if starts else 1, text.sort_name(r["name"]), r))
    hits.sort(key=lambda h: (h[0], h[1]))
    return [
        {"id": r["id"], "name": r["name"], "year": r["year"], "artist": r["artist"],
         "category_id": r["category_id"], "formats": sorted(formats_by_title[r["id"]])}
        for _, _, r in hits[:limit]
    ]


def _title_detail(conn: sqlite3.Connection, title_id: int) -> dict:
    t = conn.execute("SELECT * FROM titles WHERE id = ?", (title_id,)).fetchone()
    if t is None:
        raise HTTPException(404, "Title not found.")
    items = fetch_items(conn, "i.deleted_at IS NULL AND i.title_id = ?", (title_id,))
    box_ids = sorted({i["box_set_id"] for i in items if i["box_set_id"]})
    box_sets = []
    for bid in box_ids:
        b = conn.execute("SELECT * FROM box_sets WHERE id = ?", (bid,)).fetchone()
        members = conn.execute(
            """SELECT COUNT(*) FROM items WHERE box_set_id = ? AND deleted_at IS NULL""", (bid,)
        ).fetchone()[0]
        box_sets.append({"id": b["id"], "name": b["name"], "count": members})
    return {**dict(t), "items": items, "box_sets": box_sets}


@router.get("/titles/{title_id}")
def read_title(title_id: int, _=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return _title_detail(conn, title_id)


class TitleIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    year: int | None = Field(default=None, ge=1800, le=2200)
    artist: str | None = Field(default=None, max_length=300)
    category_id: int | None = None


def _blocking_formats(conn: sqlite3.Connection, title_ids: list[int], category_id: int) -> list[str]:
    """Formats used by these titles' copies that aren't set up for ``category_id``."""
    if not title_ids:
        return []
    marks = ",".join("?" * len(title_ids))
    rows = conn.execute(
        f"""SELECT DISTINCT f.name FROM items i JOIN formats f ON f.id = i.format_id
            WHERE i.title_id IN ({marks})
              AND f.category_id != ?
              AND NOT EXISTS (SELECT 1 FROM format_categories fc WHERE fc.format_id = f.id AND fc.category_id = ?)""",
        (*title_ids, category_id, category_id),
    ).fetchall()
    return [r[0] for r in rows]


@router.put("/titles/{title_id}")
def update_title(title_id: int, body: TitleIn, _=Depends(require("editor")), conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute("SELECT * FROM titles WHERE id = ?", (title_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Title not found.")
    category_id = body.category_id or row["category_id"]
    if category_id != row["category_id"]:
        if not conn.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone():
            raise HTTPException(400, "Unknown category.")
        blocked = _blocking_formats(conn, [title_id], category_id)
        if blocked:
            raise HTTPException(400, f"{', '.join(blocked)} isn't set up for that category (Settings → Media types).")
    name = body.name.strip()
    with tx(conn):
        conn.execute(
            "UPDATE titles SET name = ?, match_key = ?, year = ?, artist = ?, category_id = ?, updated_at = ? WHERE id = ?",
            (name, text.match_key(name) or text.search_norm(name), body.year,
             (body.artist or "").strip() or None, category_id, now(), title_id),
        )
    return _title_detail(conn, title_id)


class CategoryMoveIn(BaseModel):
    item_ids: list[int] = Field(max_length=10000)
    category_id: int


@router.post("/titles/change-category")
def change_category(body: CategoryMoveIn, _=Depends(require("editor")), conn: sqlite3.Connection = Depends(get_db)):
    """Move the titles of the selected copies (with all their copies) to another category."""
    if not conn.execute("SELECT 1 FROM categories WHERE id = ?", (body.category_id,)).fetchone():
        raise HTTPException(400, "Unknown category.")
    title_ids = sorted({r[0] for r in conn.execute(
        f"SELECT title_id FROM items WHERE id IN ({','.join('?' * len(body.item_ids))})", body.item_ids
    )}) if body.item_ids else []
    moved, skipped = 0, []
    with tx(conn):
        for tid in title_ids:
            t = conn.execute("SELECT name, category_id FROM titles WHERE id = ?", (tid,)).fetchone()
            if t["category_id"] == body.category_id:
                continue
            blocked = _blocking_formats(conn, [tid], body.category_id)
            if blocked:
                skipped.append(f"{t['name']} ({', '.join(blocked)} isn't set up for that category)")
                continue
            conn.execute("UPDATE titles SET category_id = ?, updated_at = ? WHERE id = ?", (body.category_id, now(), tid))
            moved += 1
    return {"moved": moved, "skipped": skipped}


class MergeIn(BaseModel):
    into_id: int


@router.post("/titles/{title_id}/merge")
def merge_title(title_id: int, body: MergeIn, _=Depends(require("editor")), conn: sqlite3.Connection = Depends(get_db)):
    if title_id == body.into_id:
        raise HTTPException(400, "Pick a different title.")
    src = conn.execute("SELECT * FROM titles WHERE id = ?", (title_id,)).fetchone()
    dst = conn.execute("SELECT * FROM titles WHERE id = ?", (body.into_id,)).fetchone()
    if src is None or dst is None:
        raise HTTPException(404, "Title not found.")
    if src["category_id"] != dst["category_id"]:
        raise HTTPException(400, "Titles in different categories can't be merged.")
    with tx(conn):
        conn.execute("UPDATE items SET title_id = ?, updated_at = ? WHERE title_id = ?", (body.into_id, now(), title_id))
        conn.execute("DELETE FROM titles WHERE id = ?", (title_id,))
    return _title_detail(conn, body.into_id)


# ------------------------------------------------------------------ box sets


class BoxSetIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    barcode: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=5000)


@router.get("/boxsets")
def list_box_sets(_=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        """SELECT b.*, (SELECT COUNT(*) FROM items i WHERE i.box_set_id = b.id AND i.deleted_at IS NULL) AS count
           FROM box_sets b"""
    ).fetchall()
    out = [dict(r) for r in rows]
    out.sort(key=lambda b: text.sort_name(b["name"]))
    return out


def _box_set_detail(conn: sqlite3.Connection, box_id: int) -> dict:
    b = conn.execute("SELECT * FROM box_sets WHERE id = ?", (box_id,)).fetchone()
    if b is None:
        raise HTTPException(404, "Box set not found.")
    items = fetch_items(conn, "i.deleted_at IS NULL AND i.box_set_id = ?", (box_id,))
    items.sort(key=lambda i: (i["year"] or 9999, i["sort_title"]))
    return {**dict(b), "items": items}


@router.get("/boxsets/{box_id}")
def read_box_set(box_id: int, _=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return _box_set_detail(conn, box_id)


@router.post("/boxsets")
def create_box_set(body: BoxSetIn, _=Depends(require("editor")), conn: sqlite3.Connection = Depends(get_db)):
    ts = now()
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO box_sets (name, barcode, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (body.name.strip(), (body.barcode or "").strip() or None, (body.notes or "").strip() or None, ts, ts),
        )
    return _box_set_detail(conn, cur.lastrowid)


@router.put("/boxsets/{box_id}")
def update_box_set(box_id: int, body: BoxSetIn, _=Depends(require("editor")), conn: sqlite3.Connection = Depends(get_db)):
    _box_set_detail(conn, box_id)
    with tx(conn):
        conn.execute(
            "UPDATE box_sets SET name = ?, barcode = ?, notes = ?, updated_at = ? WHERE id = ?",
            (body.name.strip(), (body.barcode or "").strip() or None, (body.notes or "").strip() or None, now(), box_id),
        )
    return _box_set_detail(conn, box_id)


@router.delete("/boxsets/{box_id}")
def delete_box_set(box_id: int, _=Depends(require("editor")), conn: sqlite3.Connection = Depends(get_db)):
    """Deletes the box set grouping only; its items stay in the collection."""
    _box_set_detail(conn, box_id)
    with tx(conn):
        conn.execute("UPDATE items SET box_set_id = NULL WHERE box_set_id = ?", (box_id,))
        conn.execute("DELETE FROM box_sets WHERE id = ?", (box_id,))
    return {"ok": True}


@router.post("/boxsets/{box_id}/items")
def add_to_box_set(box_id: int, body: IdsIn, _=Depends(require("editor")), conn: sqlite3.Connection = Depends(get_db)):
    _box_set_detail(conn, box_id)
    with tx(conn):
        for i in body.ids:
            conn.execute("UPDATE items SET box_set_id = ?, updated_at = ? WHERE id = ?", (box_id, now(), i))
    return _box_set_detail(conn, box_id)


@router.delete("/boxsets/{box_id}/items/{item_id}")
def remove_from_box_set(box_id: int, item_id: int, _=Depends(require("editor")), conn: sqlite3.Connection = Depends(get_db)):
    with tx(conn):
        conn.execute(
            "UPDATE items SET box_set_id = NULL, updated_at = ? WHERE id = ? AND box_set_id = ?", (now(), item_id, box_id)
        )
    return _box_set_detail(conn, box_id)


# ------------------------------------------------------------------ quick search


@router.get("/search")
def quick_search(q: str = "", _=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """Search grouped by title — the "do I already own it?" view."""
    if not q.strip():
        return {"titles": [], "box_sets": [], "wishlist": [], "total_items": 0}
    meta = load_meta(conn)
    items = filter_items(fetch_items(conn), q, meta["formats"])
    groups: dict[int, dict] = {}
    for i in items:
        g = groups.setdefault(i["title_id"], {
            "title_id": i["title_id"], "name": i["title"], "year": i["year"], "artist": i["artist"],
            "category_id": i["category_id"], "items": [],
        })
        g["items"].append(i)
    q_sort = text.sort_name(text.search_norm(q))
    titles = sorted(
        groups.values(),
        key=lambda g: (0 if text.sort_name(g["name"]).startswith(q_sort) else 1, text.sort_name(g["name"]), g["year"] or 0),
    )
    toks = text.tokens(q)
    key = text.barcode_key(q) if text.looks_like_barcode_query(q) else None
    box_sets = []
    for b in conn.execute(
        "SELECT b.*, (SELECT COUNT(*) FROM items i WHERE i.box_set_id = b.id AND i.deleted_at IS NULL) AS count FROM box_sets b"
    ):
        if (key and text.barcode_key(b["barcode"]) == key) or (toks and text.matches(text.search_norm(b["name"]), toks)):
            box_sets.append(dict(b))
    wish = [
        dict(w) for w in conn.execute("SELECT * FROM wishlist WHERE done = 0")
        if toks and text.matches(text.search_norm(w["text"]), toks)
    ]
    return {"titles": titles[:60], "box_sets": box_sets[:20], "wishlist": wish[:20], "total_items": len(items),
            "total_titles": len(titles)}


# ------------------------------------------------------------------ stats


@router.get("/stats")
def stats(physical: bool = False, _=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    meta = load_meta(conn)
    fmt = {f["id"]: f for f in meta["formats"]}
    items = fetch_items(conn)
    if physical:
        items = [i for i in items if fmt.get(i["format_id"], {}).get("physical", True)]
    by_format: dict[int, int] = defaultdict(int)
    by_category: dict[int, int] = defaultdict(int)
    formats_per_title: dict[int, set[int]] = defaultdict(set)
    for i in items:
        by_format[i["format_id"]] += 1
        by_category[i["category_id"]] += 1
        formats_per_title[i["title_id"]].add(i["format_id"])
    recent = sorted(items, key=lambda i: (i["created_at"], i["id"]), reverse=True)[:8]
    return {
        "items": len(items),
        "titles": len(formats_per_title),
        "multi_format_titles": sum(1 for s in formats_per_title.values() if len(s) > 1),
        "formats_in_use": len(by_format),
        "box_sets": conn.execute("SELECT COUNT(*) FROM box_sets").fetchone()[0],
        "wishlist_open": conn.execute("SELECT COUNT(*) FROM wishlist WHERE done = 0").fetchone()[0],
        "by_format": sorted(
            ({"format_id": k, "count": v} for k, v in by_format.items()), key=lambda r: -r["count"]
        ),
        "by_category": [{"category_id": k, "count": v} for k, v in by_category.items()],
        "recent": recent,
    }


# ------------------------------------------------------------------ trash


@router.get("/trash")
def list_trash(_=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    items = fetch_items(conn, "i.deleted_at IS NOT NULL")
    items.sort(key=lambda i: i["deleted_at"], reverse=True)
    return items


@router.post("/trash/{item_id}/restore")
def restore_item(item_id: int, _=Depends(require("editor")), conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("UPDATE items SET deleted_at = NULL WHERE id = ?", (item_id,))
    return get_item(conn, item_id)


@router.delete("/trash/{item_id}")
def purge_item(item_id: int, _=Depends(require("admin")), conn: sqlite3.Connection = Depends(get_db)):
    with tx(conn):
        conn.execute("DELETE FROM items WHERE id = ? AND deleted_at IS NOT NULL", (item_id,))
        delete_orphan_titles(conn)
    return {"ok": True}


@router.post("/trash/empty")
def empty_trash(_=Depends(require("admin")), conn: sqlite3.Connection = Depends(get_db)):
    with tx(conn):
        cur = conn.execute("DELETE FROM items WHERE deleted_at IS NOT NULL")
        delete_orphan_titles(conn)
    return {"ok": True, "count": cur.rowcount}


# ------------------------------------------------------------------ wish list


class WishIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class WishUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=500)
    done: bool | None = None


@router.get("/wishlist")
def list_wishlist(_=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return [dict(r) for r in conn.execute("SELECT * FROM wishlist ORDER BY done, created_at DESC, id DESC")]


@router.post("/wishlist")
def add_wish(body: WishIn, user=Depends(require("editor")), conn: sqlite3.Connection = Depends(get_db)):
    cur = conn.execute(
        "INSERT INTO wishlist (text, added_by, created_at) VALUES (?, ?, ?)",
        (body.text.strip(), user["display_name"], now()),
    )
    return dict(conn.execute("SELECT * FROM wishlist WHERE id = ?", (cur.lastrowid,)).fetchone())


@router.put("/wishlist/{wish_id}")
def update_wish(wish_id: int, body: WishUpdate, _=Depends(require("editor")), conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute("SELECT * FROM wishlist WHERE id = ?", (wish_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Not found.")
    with tx(conn):
        if body.text is not None:
            conn.execute("UPDATE wishlist SET text = ? WHERE id = ?", (body.text.strip(), wish_id))
        if body.done is not None:
            conn.execute(
                "UPDATE wishlist SET done = ?, done_at = ? WHERE id = ?",
                (int(body.done), now() if body.done else None, wish_id),
            )
    return dict(conn.execute("SELECT * FROM wishlist WHERE id = ?", (wish_id,)).fetchone())


@router.delete("/wishlist/{wish_id}")
def delete_wish(wish_id: int, _=Depends(require("editor")), conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("DELETE FROM wishlist WHERE id = ?", (wish_id,))
    return {"ok": True}


@router.post("/wishlist/clear-done")
def clear_done(_=Depends(require("editor")), conn: sqlite3.Connection = Depends(get_db)):
    cur = conn.execute("DELETE FROM wishlist WHERE done = 1")
    return {"ok": True, "count": cur.rowcount}
