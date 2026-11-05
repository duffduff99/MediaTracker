"""Barcode lookup endpoint and the admin settings for its optional API keys."""

from __future__ import annotations

import os
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import lookup
from ..db import tx
from ..security import get_db, require
from ..services import load_meta

router = APIRouter(prefix="/api")


@router.get("/lookup")
def barcode_lookup(
    barcode: str,
    format_id: int,
    category_id: int | None = None,
    refresh: bool = False,
    _=Depends(require("editor")),
    conn: sqlite3.Connection = Depends(get_db),
):
    if not lookup.lookups_enabled(conn):
        raise HTTPException(409, "Barcode lookups are turned off (Settings → Barcode lookup).")
    try:
        return lookup.lookup(conn, load_meta(conn), barcode, format_id, refresh=refresh, category_id=category_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


def _status(conn: sqlite3.Connection) -> dict:
    keys = []
    for key, info in lookup.SETTING_KEYS.items():
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        stored = row["value"] if row else None
        from_env = not stored and bool(os.environ.get(info["env"]))
        value = stored or (os.environ.get(info["env"]) if from_env else None)
        keys.append({
            "key": key,
            "label": info["label"],
            "help": info["help"],
            "url": info["url"],
            "env": info["env"],
            "set": bool(value),
            "from_env": from_env,
            "hint": f"…{value[-4:]}" if value and len(value) > 8 else ("set" if value else None),
        })
    return {"lookups_enabled": lookup.lookups_enabled(conn), "keys": keys, "hosts": lookup.HOSTS}


@router.get("/admin/integrations")
def get_integrations(_=Depends(require("admin")), conn: sqlite3.Connection = Depends(get_db)):
    return _status(conn)


class IntegrationsIn(BaseModel):
    lookups_enabled: bool | None = None
    values: dict[str, str] = Field(default_factory=dict)  # key -> new value ("" removes it)


@router.put("/admin/integrations")
def update_integrations(body: IntegrationsIn, _=Depends(require("admin")), conn: sqlite3.Connection = Depends(get_db)):
    unknown = set(body.values) - set(lookup.SETTING_KEYS)
    if unknown:
        raise HTTPException(400, f"Unknown setting: {', '.join(sorted(unknown))}")
    with tx(conn):
        if body.lookups_enabled is not None:
            lookup.set_setting(conn, lookup.LOOKUPS_ENABLED, "1" if body.lookups_enabled else "0")
        for key, value in body.values.items():
            value = value.strip()
            if len(value) > 2000:
                raise HTTPException(400, "That value is too long.")
            lookup.set_setting(conn, key, value or None)
    return _status(conn)


class TestIn(BaseModel):
    key: str


@router.post("/admin/integrations/test")
def test_integration(body: TestIn, _=Depends(require("admin")), conn: sqlite3.Connection = Depends(get_db)):
    if body.key not in lookup.SETTING_KEYS:
        raise HTTPException(400, "Unknown setting.")
    value = lookup.get_setting(conn, body.key)
    if not value:
        return {"ok": False, "message": "No key is set."}
    ok, message = lookup.check_credentials(body.key, value)
    return {"ok": ok, "message": message}


@router.post("/admin/lookup-cache/clear")
def clear_cache(_=Depends(require("admin")), conn: sqlite3.Connection = Depends(get_db)):
    cur = conn.execute("DELETE FROM lookup_cache")
    return {"ok": True, "count": cur.rowcount}
