"""Settings → Plex: connection, library choice, and running the sync."""

from __future__ import annotations

import json
import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import lookup, plex
from ..db import tx
from ..security import get_db, require

router = APIRouter(prefix="/api/admin/plex")


def _public(conn: sqlite3.Connection) -> dict:
    cfg = plex.settings(conn)
    token = cfg.pop("token")
    cfg["token_set"] = bool(token)
    cfg["token_hint"] = f"…{token[-4:]}" if len(token) > 8 else ("set" if token else None)
    cfg["configured"] = plex.configured({**cfg, "token": token})
    return cfg


@router.get("")
def get_plex(_=Depends(require("admin")), conn: sqlite3.Connection = Depends(get_db)):
    return _public(conn)


class Section(BaseModel):
    key: str = Field(max_length=40)
    title: str = Field(max_length=200)
    type: str = Field(pattern="^(movie|show)$")


class PlexIn(BaseModel):
    url: str | None = Field(default=None, max_length=300)
    token: str | None = Field(default=None, max_length=300)  # "" removes it
    format_id: int | None = None
    sections: list[Section] | None = None
    auto_sync: bool | None = None


@router.put("")
def update_plex(body: PlexIn, _=Depends(require("admin")), conn: sqlite3.Connection = Depends(get_db)):
    if body.url is not None and body.url.strip() and not re.match(r"^https?://[^\s/]+", body.url.strip()):
        raise HTTPException(400, "The address should look like http://192.168.1.20:32400")
    if body.format_id is not None and not conn.execute("SELECT 1 FROM formats WHERE id = ?", (body.format_id,)).fetchone():
        raise HTTPException(400, "Unknown format.")
    with tx(conn):
        if body.url is not None:
            lookup.set_setting(conn, "plex_url", body.url.strip().rstrip("/") or None)
        if body.token is not None:
            lookup.set_setting(conn, "plex_token", body.token.strip() or None)
        if body.format_id is not None:
            lookup.set_setting(conn, "plex_format_id", str(body.format_id))
        if body.sections is not None:
            lookup.set_setting(conn, "plex_sections", json.dumps([s.model_dump() for s in body.sections]) if body.sections else None)
        if body.auto_sync is not None:
            lookup.set_setting(conn, "plex_auto_sync", "1" if body.auto_sync else "0")
    return _public(conn)


@router.post("/test")
def test_plex(_=Depends(require("admin")), conn: sqlite3.Connection = Depends(get_db)):
    cfg = plex.settings(conn)
    if not (cfg["url"] and cfg["token"]):
        return {"ok": False, "message": "Save the Plex address and token first."}
    try:
        info = plex.server_info(cfg)
        sections = plex.list_sections(cfg)
    except plex.PlexError as e:
        return {"ok": False, "message": str(e)}
    name = info.get("name") or "Plex"
    return {"ok": True, "message": f"Connected to {name}" + (f" (version {info['version']})" if info.get("version") else "") + ".",
            "sections": sections}


class SyncIn(BaseModel):
    dry_run: bool = True


@router.post("/sync")
def run_sync(body: SyncIn, _=Depends(require("admin")), conn: sqlite3.Connection = Depends(get_db)):
    try:
        return plex.sync(conn, dry_run=body.dry_run)
    except plex.PlexError as e:
        raise HTTPException(400, str(e))
