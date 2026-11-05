"""Shared data-access helpers used by the API routes, importer and exporter."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import HTTPException

from . import text
from .db import now

# ------------------------------------------------------------------ config


def load_meta(conn: sqlite3.Connection) -> dict[str, Any]:
    categories = [dict(r) for r in conn.execute("SELECT * FROM categories ORDER BY sort_order, name")]
    for c in categories:
        c["has_artist"] = bool(c["has_artist"])
    formats = [dict(r) for r in conn.execute("SELECT * FROM formats ORDER BY sort_order, name")]
    for f in formats:
        f["physical"] = bool(f["physical"])
    links: dict[int, list[int]] = {}
    for r in conn.execute("SELECT field_id, format_id FROM field_formats"):
        links.setdefault(r["field_id"], []).append(r["format_id"])
    fields = []
    for r in conn.execute("SELECT * FROM fields ORDER BY sort_order, id"):
        f = dict(r)
        f["options"] = json.loads(f["options"])
        f["applies_all"] = bool(f["applies_all"])
        f["format_ids"] = sorted(links.get(f["id"], []))
        fields.append(f)
    return {"categories": categories, "formats": formats, "fields": fields}


def field_applies(field: dict, format_id: int) -> bool:
    return field["applies_all"] or format_id in field["format_ids"]


def clean_custom(fields: list[dict], format_id: int, custom: dict[str, Any] | None) -> dict[str, Any]:
    """Validate custom values against field definitions; drop unknown/inapplicable keys and blanks."""
    out: dict[str, Any] = {}
    custom = custom or {}
    for f in fields:
        if f["key"] not in custom or not field_applies(f, format_id):
            continue
        value = custom[f["key"]]
        if value is None or value == "" or value == []:
            continue
        t = f["type"]
        try:
            if t == "number":
                num = float(value)
                value = int(num) if num.is_integer() else num
            elif t == "boolean":
                value = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")
                if not value:
                    continue
            elif t == "multiselect":
                if isinstance(value, str):
                    value = [value]
                value = [str(v).strip() for v in value if str(v).strip()]
                if not value:
                    continue
            else:
                value = str(value).strip()
                if not value:
                    continue
        except (TypeError, ValueError):
            raise HTTPException(400, f"“{f['label']}” must be a {t}.")
        out[f["key"]] = value
    return out


# ------------------------------------------------------------------ items

ITEM_SELECT = """
SELECT i.id, i.title_id, i.format_id, i.barcode, i.box_set_id, i.notes, i.custom, i.added_by,
       i.source_ref, i.created_at, i.updated_at, i.deleted_at,
       t.name AS title, t.artist, t.year, t.category_id,
       b.name AS box_set_name, b.barcode AS box_set_barcode
FROM items i
JOIN titles t ON t.id = i.title_id
LEFT JOIN box_sets b ON b.id = i.box_set_id
"""


def serialize_item(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["custom"] = json.loads(d["custom"] or "{}")
    d["sort_title"] = text.sort_name(d["title"])
    return d


def fetch_items(conn: sqlite3.Connection, where: str = "i.deleted_at IS NULL", params: tuple = ()) -> list[dict]:
    rows = conn.execute(f"{ITEM_SELECT} WHERE {where}", params).fetchall()
    return [serialize_item(r) for r in rows]


def get_item(conn: sqlite3.Connection, item_id: int, include_deleted: bool = False) -> dict:
    where = "i.id = ?" if include_deleted else "i.id = ? AND i.deleted_at IS NULL"
    items = fetch_items(conn, where, (item_id,))
    if not items:
        raise HTTPException(404, "Item not found.")
    return items[0]


def _haystack(item: dict, formats_by_id: dict[int, dict]) -> str:
    parts = [item["title"], item.get("artist"), item.get("notes"), item.get("box_set_name"),
             formats_by_id.get(item["format_id"], {}).get("name")]
    for v in item["custom"].values():
        if isinstance(v, list):
            parts.extend(str(x) for x in v)
        elif not isinstance(v, bool):
            parts.append(str(v))
    if item.get("year"):
        parts.append(str(item["year"]))
    return text.search_norm(" ".join(p for p in parts if p))


def filter_items(items: list[dict], query: str | None, formats: list[dict]) -> list[dict]:
    """Return the items matching a free-text query (title, artist, barcode, notes, field values)."""
    if not query or not query.strip():
        return items
    formats_by_id = {f["id"]: f for f in formats}
    if text.looks_like_barcode_query(query):
        key = text.barcode_key(query)
        hits = [
            i for i in items
            if key and (
                text.barcode_key(i["barcode"]) == key
                or text.barcode_key(i.get("box_set_barcode")) == key
                or key in text.digits_only(i["barcode"])
            )
        ]
        if hits:
            return hits
    toks = text.tokens(query)
    if not toks:
        return items
    return [i for i in items if text.matches(_haystack(i, formats_by_id), toks)]


# ------------------------------------------------------------------ titles


def find_or_create_title(
    conn: sqlite3.Connection, name: str, category_id: int, year: int | None, artist: str | None
) -> int:
    """Reuse an existing title with the same name/category (and compatible year/artist), else create one."""
    name = name.strip()
    if not name:
        raise HTTPException(400, "Title is required.")
    key = text.match_key(name) or text.search_norm(name)
    rows = conn.execute(
        "SELECT * FROM titles WHERE category_id = ? AND match_key = ?", (category_id, key)
    ).fetchall()
    for r in rows:
        if year and r["year"] and r["year"] != year:
            continue
        if artist and r["artist"] and text.search_norm(artist) != text.search_norm(r["artist"]):
            continue
        return r["id"]
    ts = now()
    cur = conn.execute(
        "INSERT INTO titles (category_id, name, match_key, artist, year, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (category_id, name, key, (artist or "").strip() or None, year, ts, ts),
    )
    return cur.lastrowid


def delete_orphan_titles(conn: sqlite3.Connection) -> int:
    cur = conn.execute("DELETE FROM titles WHERE id NOT IN (SELECT DISTINCT title_id FROM items)")
    return cur.rowcount


def format_category(conn: sqlite3.Connection, format_id: int) -> int:
    row = conn.execute("SELECT category_id FROM formats WHERE id = ?", (format_id,)).fetchone()
    if row is None:
        raise HTTPException(400, "Unknown format.")
    return row["category_id"]
