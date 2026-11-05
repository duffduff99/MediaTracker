"""Nightly housekeeping: database snapshot, trash purge, expired sessions.

Runs once at start-up and then hourly; each job only does work when due.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Settings
from .db import connect, tx
from .services import delete_orphan_titles

log = logging.getLogger("mediatracker")


def snapshot(db_path: Path, target: Path) -> Path:
    """Write a consistent copy of the live database (safe while the app is running)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    tmp.replace(target)
    return target


def nightly(settings: Settings) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    target = settings.backup_dir / f"mediatracker-{today}.db"
    if not target.exists():
        snapshot(settings.db_path, target)
        log.info("Backup written: %s", target)
    backups = sorted(settings.backup_dir.glob("mediatracker-*.db"))
    for old in backups[: max(0, len(backups) - settings.backup_keep)]:
        old.unlink(missing_ok=True)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.trash_days)).isoformat(timespec="seconds")
    conn = connect(settings.db_path)
    try:
        with tx(conn):
            purged = conn.execute(
                "DELETE FROM items WHERE deleted_at IS NOT NULL AND deleted_at < ?", (cutoff,)
            ).rowcount
            delete_orphan_titles(conn)
            conn.execute("DELETE FROM sessions WHERE expires_at < ?", (datetime.now(timezone.utc).isoformat(timespec="seconds"),))
        if purged:
            log.info("Purged %d item(s) from the trash", purged)
    finally:
        conn.close()


def plex_hourly(settings: Settings) -> None:
    from . import plex  # imported here to keep start-up light

    conn = connect(settings.db_path)
    try:
        plex.scheduled_sync(conn)
    finally:
        conn.close()


async def loop(settings: Settings) -> None:
    while True:
        try:
            await asyncio.to_thread(nightly, settings)
        except Exception:  # keep the loop alive; the error is logged
            log.exception("Maintenance job failed")
        try:
            await asyncio.to_thread(plex_hourly, settings)
        except Exception:
            log.exception("Plex sync failed")
        await asyncio.sleep(3600)
