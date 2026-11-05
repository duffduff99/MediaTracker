"""Configuration managed in the app: categories, formats (media types) and custom fields (columns)."""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import text
from ..db import now, tx
from ..security import current_user, get_db, require
from ..services import load_meta

router = APIRouter(prefix="/api")

COLOR = r"^#[0-9A-Fa-f]{6}$"
FieldType = Literal["text", "longtext", "number", "boolean", "select", "multiselect", "date"]


@router.get("/meta")
def meta(_: sqlite3.Row = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return load_meta(conn)


# ------------------------------------------------------------------ categories


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    has_artist: bool = False
    sort_order: int = 0


@router.post("/categories")
def create_category(body: CategoryIn, _=Depends(require("admin")), conn: sqlite3.Connection = Depends(get_db)):
    if conn.execute("SELECT 1 FROM categories WHERE name = ?", (body.name.strip(),)).fetchone():
        raise HTTPException(409, "A category with that name exists.")
    with tx(conn):
        conn.execute(
            "INSERT INTO categories (name, has_artist, sort_order) VALUES (?, ?, ?)",
            (body.name.strip(), int(body.has_artist), body.sort_order),
        )
    return load_meta(conn)


@router.put("/categories/{cat_id}")
def update_category(cat_id: int, body: CategoryIn, _=Depends(require("admin")), conn: sqlite3.Connection = Depends(get_db)):
    clash = conn.execute("SELECT id FROM categories WHERE name = ? AND id != ?", (body.name.strip(), cat_id)).fetchone()
    if clash:
        raise HTTPException(409, "A category with that name exists.")
    with tx(conn):
        cur = conn.execute(
            "UPDATE categories SET name = ?, has_artist = ?, sort_order = ? WHERE id = ?",
            (body.name.strip(), int(body.has_artist), body.sort_order, cat_id),
        )
    if cur.rowcount == 0:
        raise HTTPException(404, "Category not found.")
    return load_meta(conn)


@router.delete("/categories/{cat_id}")
def delete_category(cat_id: int, _=Depends(require("admin")), conn: sqlite3.Connection = Depends(get_db)):
    if conn.execute("SELECT 1 FROM formats WHERE category_id = ?", (cat_id,)).fetchone():
        raise HTTPException(409, "Some formats use this as their default category. Change their default first.")
    if conn.execute("SELECT 1 FROM titles WHERE category_id = ?", (cat_id,)).fetchone():
        raise HTTPException(409, "This category still has titles.")
    with tx(conn):
        conn.execute("DELETE FROM categories WHERE id = ?", (cat_id,))
    return load_meta(conn)


# ------------------------------------------------------------------ formats


class FormatIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    category_id: int  # the default category
    category_ids: list[int] = []  # every category the format can be used for (the default is always included)
    color: str = Field(default="#55504A", pattern=COLOR)
    physical: bool = True
    sort_order: int = 0


def _set_format_categories(conn: sqlite3.Connection, format_id: int, body: FormatIn) -> None:
    wanted = set(body.category_ids) | {body.category_id}
    valid = {r[0] for r in conn.execute("SELECT id FROM categories")}
    if not wanted <= valid:
        raise HTTPException(400, "Unknown category.")
    current = {r[0] for r in conn.execute("SELECT category_id FROM format_categories WHERE format_id = ?", (format_id,))}
    for cat in current - wanted:
        used = conn.execute(
            "SELECT COUNT(*) FROM items i JOIN titles t ON t.id = i.title_id WHERE i.format_id = ? AND t.category_id = ?",
            (format_id, cat),
        ).fetchone()[0]
        if used:
            name = conn.execute("SELECT name FROM categories WHERE id = ?", (cat,)).fetchone()[0]
            raise HTTPException(409, f"{used} {name} item(s) use this format, so {name} can't be removed from it.")
    conn.execute("DELETE FROM format_categories WHERE format_id = ?", (format_id,))
    for cat in wanted:
        conn.execute("INSERT INTO format_categories (format_id, category_id) VALUES (?, ?)", (format_id, cat))


@router.post("/formats")
def create_format(body: FormatIn, _=Depends(require("admin")), conn: sqlite3.Connection = Depends(get_db)):
    if conn.execute("SELECT 1 FROM formats WHERE name = ?", (body.name.strip(),)).fetchone():
        raise HTTPException(409, "A format with that name exists.")
    if not conn.execute("SELECT 1 FROM categories WHERE id = ?", (body.category_id,)).fetchone():
        raise HTTPException(400, "Unknown category.")
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO formats (category_id, name, color, physical, sort_order) VALUES (?, ?, ?, ?, ?)",
            (body.category_id, body.name.strip(), body.color, int(body.physical), body.sort_order),
        )
        _set_format_categories(conn, cur.lastrowid, body)
    return load_meta(conn)


@router.put("/formats/{format_id}")
def update_format(format_id: int, body: FormatIn, _=Depends(require("admin")), conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute("SELECT * FROM formats WHERE id = ?", (format_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Format not found.")
    if conn.execute("SELECT 1 FROM formats WHERE name = ? AND id != ?", (body.name.strip(), format_id)).fetchone():
        raise HTTPException(409, "A format with that name exists.")
    with tx(conn):
        conn.execute(
            "UPDATE formats SET name = ?, category_id = ?, color = ?, physical = ?, sort_order = ? WHERE id = ?",
            (body.name.strip(), body.category_id, body.color, int(body.physical), body.sort_order, format_id),
        )
        if body.category_ids or body.category_id != row["category_id"]:
            if not body.category_ids:  # an older client sent only the default: keep the other categories
                body.category_ids = [r[0] for r in conn.execute(
                    "SELECT category_id FROM format_categories WHERE format_id = ?", (format_id,))]
            _set_format_categories(conn, format_id, body)
    return load_meta(conn)


@router.delete("/formats/{format_id}")
def delete_format(format_id: int, _=Depends(require("admin")), conn: sqlite3.Connection = Depends(get_db)):
    if conn.execute("SELECT 1 FROM items WHERE format_id = ?", (format_id,)).fetchone():
        raise HTTPException(409, "This format still has items (including items in the trash).")
    with tx(conn):
        conn.execute("DELETE FROM formats WHERE id = ?", (format_id,))
    return load_meta(conn)


# ------------------------------------------------------------------ fields (columns)


class FieldIn(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    type: FieldType
    options: list[str] = []
    applies_all: bool = True
    format_ids: list[int] = []


class FieldUpdate(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    options: list[str] = []
    renames: dict[str, str] = {}  # old option -> new option; existing values are rewritten
    applies_all: bool = True
    format_ids: list[int] = []


def _clean_options(options: list[str]) -> list[str]:
    seen: list[str] = []
    for o in options:
        o = o.strip()
        if o and o not in seen:
            seen.append(o)
    return seen


def _set_formats(conn: sqlite3.Connection, field_id: int, applies_all: bool, format_ids: list[int]) -> None:
    conn.execute("DELETE FROM field_formats WHERE field_id = ?", (field_id,))
    if applies_all:
        return
    valid = {r[0] for r in conn.execute("SELECT id FROM formats")}
    for fid in set(format_ids):
        if fid in valid:
            conn.execute("INSERT INTO field_formats (field_id, format_id) VALUES (?, ?)", (field_id, fid))


RESERVED_KEYS = {"title", "artist", "year", "format", "category", "barcode", "box_set", "notes", "added_by", "created_at"}


@router.post("/fields")
def create_field(body: FieldIn, _=Depends(require("admin")), conn: sqlite3.Connection = Depends(get_db)):
    options = _clean_options(body.options)
    if body.type in ("select", "multiselect") and not options:
        raise HTTPException(400, "Add at least one option.")
    base = text.slugify(body.label)
    if base in RESERVED_KEYS:
        base = f"{base}_custom"
    key, n = base, 2
    while conn.execute("SELECT 1 FROM fields WHERE key = ?", (key,)).fetchone():
        key, n = f"{base}_{n}", n + 1
    order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM fields").fetchone()[0]
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO fields (key, label, type, options, applies_all, sort_order, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (key, body.label.strip(), body.type, json.dumps(options), int(body.applies_all), order, now()),
        )
        _set_formats(conn, cur.lastrowid, body.applies_all, body.format_ids)
    return load_meta(conn)


@router.put("/fields/{field_id}")
def update_field(field_id: int, body: FieldUpdate, _=Depends(require("admin")), conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute("SELECT * FROM fields WHERE id = ?", (field_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Field not found.")
    options = _clean_options(body.options)
    if row["type"] in ("select", "multiselect") and not options:
        raise HTTPException(400, "Add at least one option.")
    renames = {o: n.strip() for o, n in body.renames.items() if n.strip() and o != n.strip()}
    with tx(conn):
        conn.execute(
            "UPDATE fields SET label = ?, options = ?, applies_all = ? WHERE id = ?",
            (body.label.strip(), json.dumps(options), int(body.applies_all), field_id),
        )
        _set_formats(conn, field_id, body.applies_all, body.format_ids)
        if renames:
            _rename_values(conn, row["key"], row["type"], renames)
    return load_meta(conn)


def _rename_values(conn: sqlite3.Connection, key: str, ftype: str, renames: dict[str, str]) -> None:
    path = f'$."{key}"'
    rows = conn.execute(
        "SELECT id, custom FROM items WHERE json_extract(custom, ?) IS NOT NULL", (path,)
    ).fetchall()
    for r in rows:
        custom = json.loads(r["custom"])
        value = custom.get(key)
        if ftype == "multiselect" and isinstance(value, list):
            new = [renames.get(v, v) for v in value]
        elif isinstance(value, str):
            new = renames.get(value, value)
        else:
            continue
        if new != value:
            custom[key] = new
            conn.execute("UPDATE items SET custom = ? WHERE id = ?", (json.dumps(custom), r["id"]))


class OrderIn(BaseModel):
    ids: list[int]


@router.put("/fields-order")
def reorder_fields(body: OrderIn, _=Depends(require("admin")), conn: sqlite3.Connection = Depends(get_db)):
    with tx(conn):
        for i, fid in enumerate(body.ids):
            conn.execute("UPDATE fields SET sort_order = ? WHERE id = ?", (i, fid))
    return load_meta(conn)


@router.delete("/fields/{field_id}")
def delete_field(field_id: int, _=Depends(require("admin")), conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute("SELECT * FROM fields WHERE id = ?", (field_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Field not found.")
    if not re.fullmatch(r"[a-z0-9_]+", row["key"]):
        raise HTTPException(500, "Unexpected field key.")
    with tx(conn):
        conn.execute("UPDATE items SET custom = json_remove(custom, ?)", (f'$."{row["key"]}"',))
        conn.execute("DELETE FROM fields WHERE id = ?", (field_id,))
    return load_meta(conn)
