"""Keep one format (normally "Digital") in step with what's on a Plex Media Server.

Movies become one copy each; TV shows become one copy per season, titled
"Show - Season N" so they link to physical seasons with the same name.

Each synced copy remembers its Plex item in ``items.source_ref`` ("plex:<ratingKey>").
A sync:

* adds copies for new Plex titles, linking them to titles you already own,
* adopts existing copies of the synced format that match a Plex title (the
  first sync takes over the old Jira "Digital" items this way),
* moves copies to the trash when their title is no longer in Plex, including
  copies of the synced format that never came from Plex (Plex owns that format),
* restores copies from the trash when the title comes back,
* fills in Resolution (4K / 1080p / Other) for movies.

Safety: nothing changes if Plex returns no titles, and an automatic (hourly) sync
won't remove more than a quarter of the synced copies at once; it reports instead.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import urllib.parse
from collections import defaultdict
from typing import Any, Callable

from . import lookup, text
from .db import now
from .services import load_meta

log = logging.getLogger("mediatracker")

REF_PREFIX = "plex:"
LIST_CAP = 300
_lock = threading.Lock()

# Swappable in tests.
fetch_json: Callable[[str, dict[str, str] | None], Any] = lookup.http_get_json


class PlexError(Exception):
    pass


# ------------------------------------------------------------------ settings


def settings(conn: sqlite3.Connection) -> dict:
    get = lambda k: lookup.get_setting(conn, k)  # noqa: E731
    try:
        sections = json.loads(get("plex_sections") or "[]")
    except ValueError:
        sections = []
    try:
        last = json.loads(get("plex_last_sync") or "null")
    except ValueError:
        last = None
    fmt = get("plex_format_id")
    return {
        "url": get("plex_url") or "",
        "token": get("plex_token") or "",
        "sections": sections,
        "format_id": int(fmt) if fmt and fmt.isdigit() else None,
        "auto_sync": get("plex_auto_sync") == "1",
        "last_sync": last,
    }


def configured(cfg: dict) -> bool:
    return bool(cfg["url"] and cfg["token"] and cfg["sections"] and cfg["format_id"])


# ------------------------------------------------------------------ Plex API


def _get(cfg: dict, path: str, params: dict | None = None) -> dict:
    url = cfg["url"].rstrip("/") + path + ("?" + urllib.parse.urlencode(params) if params else "")
    headers = {"X-Plex-Token": cfg["token"], "X-Plex-Product": "MediaTracker", "X-Plex-Client-Identifier": "mediatracker"}
    try:
        data = fetch_json(url, headers)
    except lookup.SourceError as e:
        msg = {
            "auth": "Plex refused the token. Check it in Settings → Plex.",
            "unreachable": f"Couldn't reach Plex at {cfg['url']}. Check the address, and that this server can reach it.",
        }.get(e.status, f"Plex error: {e.message}")
        raise PlexError(msg)
    if data is None:
        raise PlexError(f"Plex answered 'not found' for {path}.")
    return data.get("MediaContainer") or {}


def server_info(cfg: dict) -> dict:
    root = _get(cfg, "/")
    return {"name": root.get("friendlyName"), "version": root.get("version")}


def list_sections(cfg: dict) -> list[dict]:
    mc = _get(cfg, "/library/sections")
    return [
        {"key": str(d.get("key")), "title": d.get("title"), "type": d.get("type")}
        for d in mc.get("Directory") or []
        if d.get("type") in ("movie", "show")
    ]


_RES_RANK = {"4k": 4, "2160": 4, "1080": 3, "720": 2, "576": 1, "480": 1, "sd": 0}


def _resolution(meta: dict) -> str | None:
    best = None
    for m in meta.get("Media") or []:
        r = str(m.get("videoResolution") or "").lower()
        if r in _RES_RANK and (best is None or _RES_RANK[r] > _RES_RANK[best]):
            best = r
    if best is None:
        return None
    return "4K" if _RES_RANK[best] == 4 else "1080p" if best == "1080" else "Other"


def fetch_entries(cfg: dict) -> list[dict]:
    """Every movie and TV season in the selected libraries."""
    entries: list[dict] = []
    for sec in cfg["sections"]:
        key, kind = sec.get("key"), sec.get("type")
        if kind == "movie":
            for m in _get(cfg, f"/library/sections/{key}/all", {"type": 1}).get("Metadata") or []:
                if not m.get("ratingKey") or not m.get("title"):
                    continue
                entries.append({"ref": f"{REF_PREFIX}{m['ratingKey']}", "kind": "movie", "title": m["title"],
                                "year": _int(m.get("year")), "resolution": _resolution(m), "library": sec.get("title")})
        elif kind == "show":
            shows = _get(cfg, f"/library/sections/{key}/all", {"type": 2}).get("Metadata") or []
            show_by_key = {str(s.get("ratingKey")): s for s in shows}
            seasons = _get(cfg, f"/library/sections/{key}/all", {"type": 3}).get("Metadata") or []
            if shows and not seasons:  # older servers: ask each show for its seasons
                for s in shows:
                    for se in _get(cfg, f"/library/metadata/{s['ratingKey']}/children").get("Metadata") or []:
                        seasons.append({**se, "parentRatingKey": s["ratingKey"], "parentTitle": s.get("title")})
            for se in seasons:
                idx = _int(se.get("index"))
                if not idx or not se.get("ratingKey"):  # skip "Specials" (season 0)
                    continue
                show = show_by_key.get(str(se.get("parentRatingKey")), {})
                name = se.get("parentTitle") or show.get("title")
                if not name:
                    continue
                entries.append({"ref": f"{REF_PREFIX}{se['ratingKey']}", "kind": "season", "title": f"{name} - Season {idx}",
                                "year": _int(show.get("year")) or _int(se.get("parentYear")), "resolution": None,
                                "library": sec.get("title")})
    return entries


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ sync


def _years_ok(a: int | None, b: int | None) -> bool:
    return not a or not b or abs(a - b) <= 1


def sync(conn: sqlite3.Connection, dry_run: bool = False, scheduled: bool = False) -> dict:
    if not _lock.acquire(blocking=False):
        raise PlexError("A Plex sync is already running.")
    try:
        return _sync(conn, dry_run, scheduled)
    finally:
        _lock.release()


def _sync(conn: sqlite3.Connection, dry_run: bool, scheduled: bool) -> dict:
    cfg = settings(conn)
    if not configured(cfg):
        raise PlexError("Plex isn't set up yet: add the address, token, libraries and format in Settings → Plex.")
    meta = load_meta(conn)
    fmt = next((f for f in meta["formats"] if f["id"] == cfg["format_id"]), None)
    if fmt is None:
        raise PlexError("The format chosen for Plex no longer exists.")

    entries = fetch_entries(cfg)
    if not entries:
        raise PlexError("Plex returned no titles from the selected libraries, so nothing was changed.")

    cats = {c["name"].lower(): c["id"] for c in meta["categories"]}
    allowed = fmt["category_ids"]
    movie_cat = cats.get("movies") if cats.get("movies") in allowed else fmt["category_id"]
    tv_cat = cats.get("tv") if cats.get("tv") in allowed else movie_cat
    res_field = next((f for f in meta["fields"] if f["key"] == "resolution"
                      and (f["applies_all"] or fmt["id"] in f["format_ids"])), None)

    report: dict[str, Any] = {"dry_run": dry_run, "plex_titles": len(entries), "format": fmt["name"],
                              "counts": defaultdict(int), "lists": defaultdict(list), "warnings": []}

    def note(kind: str, line: str) -> None:
        report["counts"][kind] += 1
        if len(report["lists"][kind]) < LIST_CAP:
            report["lists"][kind].append(line)

    rows = conn.execute(
        "SELECT i.*, t.name AS title, t.match_key, t.year AS title_year, t.category_id "
        "FROM items i JOIN titles t ON t.id = i.title_id WHERE i.format_id = ?",
        (fmt["id"],),
    ).fetchall()
    by_ref = {r["source_ref"]: r for r in rows if (r["source_ref"] or "").startswith(REF_PREFIX)}
    unclaimed: dict[str, list[sqlite3.Row]] = defaultdict(list)  # live copies not (yet) tied to Plex
    for r in rows:
        if r["deleted_at"] is None and not (r["source_ref"] or "").startswith(REF_PREFIX):
            unclaimed[r["match_key"]].append(r)

    ts = now()
    conn.execute("BEGIN IMMEDIATE")
    try:
        seen: set[str] = set()
        for e in entries:
            if e["ref"] in seen:
                continue
            seen.add(e["ref"])
            label = f"{e['title']}" + (f" ({e['year']})" if e["year"] else "")
            custom_res = e["resolution"] if res_field and e["resolution"] in res_field["options"] else None
            key = text.match_key(e["title"]) or text.search_norm(e["title"])
            # Seasons are matched by name only: "Show - Season 8" is specific already, and a physical
            # season's year is often the season's own year, not the show's first-air year that Plex gives.
            match_year = None if e["kind"] == "season" else e["year"]

            item = by_ref.get(e["ref"])
            if item is None:
                # adopt an existing copy of this format with the same title (e.g. an old Jira "Digital" item)
                cands = [r for r in unclaimed.get(key, []) if _years_ok(r["title_year"], match_year)]
                if cands:
                    item = cands[0]
                    unclaimed[key].remove(item)
                    conn.execute("UPDATE items SET source_ref = ?, updated_at = ? WHERE id = ?", (e["ref"], ts, item["id"]))
                    note("linked", label)
            if item is not None:
                if item["deleted_at"] is not None:
                    conn.execute("UPDATE items SET deleted_at = NULL, updated_at = ? WHERE id = ?", (ts, item["id"]))
                    note("restored", label)
                if custom_res:
                    custom = json.loads(item["custom"] or "{}")
                    if custom.get("resolution") != custom_res:
                        custom["resolution"] = custom_res
                        conn.execute("UPDATE items SET custom = ?, updated_at = ? WHERE id = ?", (json.dumps(custom), ts, item["id"]))
                        note("updated", f"{label}: {custom_res}")
                continue

            # new: link to a title you already own (same name, close year), else create one
            natural = tv_cat if e["kind"] == "season" else movie_cat
            titles = conn.execute(
                f"SELECT * FROM titles WHERE match_key = ? AND category_id IN ({','.join('?' * len(allowed))})",
                (key, *allowed),
            ).fetchall()
            titles = sorted((t for t in titles if _years_ok(t["year"], match_year)), key=lambda t: t["category_id"] != natural)
            if titles:
                title_id = titles[0]["id"]
            else:
                cur = conn.execute(
                    "INSERT INTO titles (category_id, name, match_key, artist, year, created_at, updated_at) VALUES (?, ?, ?, NULL, ?, ?, ?)",
                    (natural, e["title"], key, e["year"], ts, ts),
                )
                title_id = cur.lastrowid
            conn.execute(
                "INSERT INTO items (title_id, format_id, custom, added_by, source_ref, created_at, updated_at) VALUES (?, ?, ?, 'Plex', ?, ?, ?)",
                (title_id, fmt["id"], json.dumps({"resolution": custom_res} if custom_res else {}), e["ref"], ts, ts),
            )
            note("added", label + (" → linked to a title you own" if titles else ""))

        # remove: Plex copies whose title left Plex, and copies of this format that never came from Plex
        to_remove = [r for ref, r in by_ref.items() if ref not in seen and r["deleted_at"] is None]
        to_remove += [r for group in unclaimed.values() for r in group]
        live = sum(1 for r in rows if r["deleted_at"] is None)
        if scheduled and len(to_remove) > max(20, live // 4):
            report["warnings"].append(
                f"This automatic sync would have removed {len(to_remove)} of {live} {fmt['name']} items, so it removed none. "
                "If that's expected, run Sync now in Settings → Plex."
            )
        else:
            for r in to_remove:
                conn.execute("UPDATE items SET deleted_at = ?, updated_at = ? WHERE id = ?", (ts, ts, r["id"]))
                note("removed", f"{r['title']}" + (f" ({r['title_year']})" if r["title_year"] else ""))

        report["unchanged"] = len(seen) - sum(report["counts"].get(k, 0) for k in ("added", "linked", "restored"))
        report["counts"] = dict(report["counts"])
        report["lists"] = dict(report["lists"])
        if dry_run:
            conn.execute("ROLLBACK")
        else:
            summary = {"at": ts, "scheduled": scheduled, "plex_titles": len(entries), "counts": report["counts"],
                       "warnings": report["warnings"]}
            lookup.set_setting(conn, "plex_last_sync", json.dumps(summary))
            if not scheduled and lookup.get_setting(conn, "plex_auto_sync") is None:
                lookup.set_setting(conn, "plex_auto_sync", "1")  # turn hourly sync on after the first real sync
            conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return report


def scheduled_sync(conn: sqlite3.Connection) -> None:
    """Called hourly by the maintenance loop."""
    cfg = settings(conn)
    if not (configured(cfg) and cfg["auto_sync"]):
        return
    try:
        r = sync(conn, scheduled=True)
        log.info("Plex sync: %s", r["counts"] or "no changes")
    except PlexError as e:
        log.warning("Plex sync skipped: %s", e)
        lookup.set_setting(conn, "plex_last_sync", json.dumps({"at": now(), "scheduled": True, "error": str(e)}))
