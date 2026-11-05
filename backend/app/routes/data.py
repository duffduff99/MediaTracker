"""Export (CSV/Excel), the Jira import, and on-demand backup download."""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

from .. import exporter
from ..importer_jira import run_import
from ..maintenance import snapshot
from ..security import current_user, get_db, require
from ..services import fetch_items, filter_items, load_meta

router = APIRouter(prefix="/api")

MAX_IMPORT_BYTES = 20 * 1024 * 1024


def _selected_items(conn, q, format_id, category_id):
    meta = load_meta(conn)
    items = fetch_items(conn)
    if format_id:
        items = [i for i in items if i["format_id"] in format_id]
    if category_id:
        items = [i for i in items if i["category_id"] == category_id]
    items = filter_items(items, q, meta["formats"])
    items.sort(key=lambda i: (i["sort_title"], i["year"] or 0, i["format_id"]))
    return meta, items


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d")


@router.get("/export.csv")
def export_csv(
    q: str | None = None,
    format_id: list[int] = Query(default=[]),
    category_id: int | None = None,
    columns: str | None = None,
    _=Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    meta, items = _selected_items(conn, q, format_id, category_id)
    cols = exporter.pick_columns(meta, columns.split(",") if columns else None)
    return Response(
        exporter.to_csv(items, cols),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="mediatracker-{_stamp()}.csv"'},
    )


@router.get("/export.xlsx")
def export_xlsx(
    q: str | None = None,
    format_id: list[int] = Query(default=[]),
    category_id: int | None = None,
    _=Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    meta, items = _selected_items(conn, q, format_id, category_id)
    return Response(
        exporter.to_xlsx(items, meta),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="mediatracker-{_stamp()}.xlsx"'},
    )


@router.post("/import/jira")
def import_jira(
    file: UploadFile = File(...),
    commit: bool = False,
    _=Depends(require("admin")),
    conn: sqlite3.Connection = Depends(get_db),
):
    data = file.file.read(MAX_IMPORT_BYTES + 1)
    if len(data) > MAX_IMPORT_BYTES:
        raise HTTPException(413, "That file is too large (20 MB max).")
    try:
        return run_import(conn, data, commit=commit)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/admin/backup")
def download_backup(request: Request, _=Depends(require("admin"))):
    settings = request.app.state.settings
    with tempfile.TemporaryDirectory() as d:
        path = snapshot(settings.db_path, Path(d) / "backup.db")
        data = path.read_bytes()
    return Response(
        data,
        media_type="application/vnd.sqlite3",
        headers={"Content-Disposition": f'attachment; filename="mediatracker-backup-{_stamp()}.db"'},
    )
