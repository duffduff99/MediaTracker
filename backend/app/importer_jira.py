"""One-time import of the Jira "Media Tracking" CSV export.

Run it from the app (Settings → Import) or the command line:

    python -m app.importer_jira path/to/Jira.csv            # dry run, prints the report
    python -m app.importer_jira path/to/Jira.csv --commit   # actually import

The import is safe to re-run: rows already imported (matched by Jira issue
key) are skipped. A dry run performs the whole import inside a transaction
and rolls it back, so its report is exactly what a real import would do.

What it cleans up (see docs/IMPORT.md for the reasoning):
* "Mask, The" becomes "The Mask"; trailing "(Widescreen)"-style qualifiers
  move to Edition (or Notes); "[REPLACE]"/"(BAD?)" markers move to Notes.
* Copies of the same title in different formats are linked to one title,
  using the cleaned name plus year (copies more than 10 years apart are
  treated as different films, e.g. Footloose 1984 vs 2011), plus the
  "Relates" links made in Jira.
* Barcodes: Excel-mangled values like 7.86936E+11 are cleared and tagged
  "Re-scan barcode"; 11-digit UPCs get their lost leading zero back;
  14-digit values with a 2-digit add-on keep the main 12 digits;
  non-numeric values such as "LV 1180" move to Catalog #.
* Jira "Collection" issues become box sets; their child issues are linked.
* Watched/Unwatched/Replace statuses are not imported.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from . import text
from .db import now, tx
from .services import delete_orphan_titles, find_or_create_title, load_meta

TYPE_MAP = {
    "digital": "Digital",
    "blu-ray": "Blu-ray",
    "laserdisc": "Laserdisc",
    "vhs": "VHS",
    "hd-dvd": "HD DVD",
    "xbox 360 game": "Xbox 360",
    "4k blu-ray": "4K Blu-ray",
    "xbox original game": "Xbox",
    "3d blu-ray": "3D Blu-ray",
    "playstation 3 game": "PlayStation 3",
    "dvd": "DVD",
    "gamecube game": "GameCube",
}
COLLECTION_TYPE = "collection"
RESCAN_TAG = "Re-scan barcode"
YEAR_GAP = 10
LIST_CAP = 400

_MARKER = re.compile(r"\s*[\[(]\s*(replace|bad\??)\s*[\])]\s*", re.IGNORECASE)
_TRAILING_PARENS = re.compile(r"\s*\(([^()]*)\)\s*$")
_INVERTED_ARTICLE = re.compile(r"^(.+?),\s+(The|A|An)\b(.*)$")
_SCI = re.compile(r"^\d+(\.\d+)?[eE]\+\d+$")
_JIRA_COMMENT = re.compile(r"^[^;]*;[^;]*;(.*)$", re.DOTALL)


class Report:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.lists: dict[str, list] = defaultdict(list)
        self.warnings: list[str] = []

    def add(self, name: str, entry: Any) -> None:
        self.counts[name] += 1
        if len(self.lists[name]) < LIST_CAP:
            self.lists[name].append(entry)

    def as_dict(self) -> dict:
        return {"counts": dict(self.counts), "lists": dict(self.lists), "warnings": self.warnings}


# ------------------------------------------------------------------ cleaning helpers


def clean_title(raw: str) -> tuple[str, list[str], list[str]]:
    """Return (clean title, qualifiers, markers)."""
    s = re.sub(r"\s+", " ", raw).strip()
    markers = [m.group(1).upper() for m in _MARKER.finditer(s)]
    s = _MARKER.sub(" ", s).strip()
    qualifiers: list[str] = []
    while True:
        m = _TRAILING_PARENS.search(s)
        if not m or m.start() == 0:
            break
        qualifiers.insert(0, m.group(1).strip())
        s = s[: m.start()].strip()
    m = _INVERTED_ARTICLE.match(s)
    if m:
        s = f"{m.group(2)} {m.group(1).strip()}{m.group(3)}".strip()
    s = re.sub(r"\s+", " ", s)
    return s, [q for q in qualifiers if q], markers


def parse_barcode(raw: str) -> dict:
    """Classify a Jira barcode value."""
    s = (raw or "").strip()
    if not s or s.upper() in ("N/A", "NA", "NONE", "-"):
        return {"kind": "empty"}
    if _SCI.match(s):
        return {"kind": "rescan", "raw": s}
    if re.fullmatch(r"\d+", s):
        if len(s) == 11 and text.upc_a_valid("0" + s):
            return {"kind": "barcode", "value": "0" + s, "fix": "leading_zero"}
        if len(s) in (8, 12, 13):
            return {"kind": "barcode", "value": s}
        if len(s) == 14 and text.upc_a_valid(s[:12]):
            return {"kind": "barcode", "value": s[:12], "fix": "addon", "addon": s[12:]}
        if len(s) in (11, 14):
            return {"kind": "barcode", "value": s, "fix": "unverified"}
        return {"kind": "catalog", "value": s}
    return {"kind": "catalog", "value": s}


def parse_year(raw: str) -> int | None:
    try:
        y = int(float(raw))
    except (TypeError, ValueError):
        return None
    return y if 1800 <= y <= 2200 else None


def parse_created(raw: str) -> str:
    try:
        dt = datetime.strptime(raw.strip(), "%d/%b/%y %I:%M %p").replace(tzinfo=timezone.utc)
        return dt.isoformat(timespec="seconds")
    except (ValueError, AttributeError):
        return now()


class _Rows:
    """Access CSV columns by header name; Jira repeats headers for multi-value fields."""

    def __init__(self, header: list[str]):
        self.idx: dict[str, list[int]] = defaultdict(list)
        for i, h in enumerate(header):
            self.idx[h.strip()].append(i)

    def has(self, name: str) -> bool:
        return name in self.idx

    def all(self, row: list[str], name: str) -> list[str]:
        return [row[i].strip() for i in self.idx.get(name, []) if i < len(row) and row[i].strip()]

    def one(self, row: list[str], name: str) -> str:
        vals = self.all(row, name)
        return vals[0] if vals else ""


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[Any, Any] = {}

    def find(self, x: Any) -> Any:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: Any, b: Any) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


# ------------------------------------------------------------------ main entry point


def run_import(conn: sqlite3.Connection, data: bytes, commit: bool) -> dict:
    report = Report()
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = data.decode("cp1252")
    reader = csv.reader(io.StringIO(content))
    try:
        header = next(reader)
    except StopIteration:
        raise ValueError("The file is empty.")
    cols = _Rows(header)
    for required in ("Summary", "Issue key", "Issue Type"):
        if not cols.has(required):
            raise ValueError(f"This doesn't look like a Jira export: no “{required}” column.")
    rows = [r for r in reader if any(c.strip() for c in r)]
    report.counts["rows"] = len(rows)

    conn.execute("BEGIN IMMEDIATE")
    try:
        _do_import(conn, cols, rows, report)
        delete_orphan_titles(conn)
        conn.execute("COMMIT" if commit else "ROLLBACK")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    result = report.as_dict()
    result["committed"] = commit
    return result


def _do_import(conn: sqlite3.Connection, cols: _Rows, rows: list[list[str]], report: Report) -> None:
    meta = load_meta(conn)
    formats = {f["name"].lower(): f for f in meta["formats"]}
    categories = {c["name"].lower(): c for c in meta["categories"]}
    fields = {f["key"]: f for f in meta["fields"]}
    existing_refs = {r[0] for r in conn.execute("SELECT source_ref FROM items WHERE source_ref IS NOT NULL")}
    new_options: dict[str, list[str]] = defaultdict(list)

    def get_format(issue_type: str) -> dict:
        name = TYPE_MAP.get(issue_type.lower(), issue_type.strip())
        f = formats.get(name.lower())
        if f is None:
            cat_name = "games" if "game" in issue_type.lower() else "movies"
            cat = categories.get(cat_name) or next(iter(categories.values()))
            cur = conn.execute(
                "INSERT INTO formats (category_id, name, color, physical, sort_order) VALUES (?, ?, '#55504A', 1, 99)",
                (cat["id"], name),
            )
            f = {"id": cur.lastrowid, "name": name, "category_id": cat["id"], "physical": True}
            formats[name.lower()] = f
            report.add("formats_created", name)
        return f

    def applies(key: str, format_id: int) -> bool:
        f = fields.get(key)
        return bool(f) and (f["applies_all"] or format_id in f["format_ids"])

    def ensure_option(key: str, value: str) -> None:
        f = fields.get(key)
        if f and f["type"] in ("select", "multiselect") and value not in f["options"]:
            f["options"].append(value)
            new_options[key].append(value)

    # ---- pass 1: parse rows
    box_rows: dict[str, dict] = {}
    records: list[dict] = []
    for row in rows:
        key = cols.one(row, "Issue key")
        issue_type = cols.one(row, "Issue Type")
        raw_title = cols.one(row, "Summary")
        if not key or not raw_title:
            report.warnings.append(f"Skipped a row with no issue key or summary: {row[:2]}")
            continue
        if issue_type.lower() == COLLECTION_TYPE:
            name, quals, _ = clean_title(raw_title)
            if quals:
                name = f"{name} ({', '.join(quals)})"
            box_rows[key] = {"key": key, "name": name, "description": cols.one(row, "Description")}
            continue
        if f"jira:{key}" in existing_refs:
            report.add("skipped_already_imported", key)
            continue

        fmt = get_format(issue_type)
        title, qualifiers, markers = clean_title(raw_title)
        notes: list[str] = []
        custom: dict[str, Any] = {}

        def put(field_key: str, value: Any, label: str) -> None:
            if value in (None, "", []):
                return
            if applies(field_key, fmt["id"]):
                custom[field_key] = value
            else:
                shown = ", ".join(value) if isinstance(value, list) else ("Yes" if value is True else value)
                notes.append(f"{label}: {shown}")

        # barcode / catalog number
        bc = parse_barcode(cols.one(row, "Custom field (Barcode)"))
        barcode = None
        if bc["kind"] == "rescan":
            custom.setdefault("tags", []).append(RESCAN_TAG)
            notes.append(f"Barcode was corrupted in Jira ({bc['raw']}); scan it again.")
            report.add("barcodes_need_rescan", f"{title} [{fmt['name']}] — {bc['raw']}")
        elif bc["kind"] == "barcode":
            barcode = bc["value"]
            if bc.get("fix") == "leading_zero":
                report.add("barcodes_leading_zero_restored", f"{title} [{fmt['name']}] → {barcode}")
            elif bc.get("fix") == "addon":
                notes.append(f"Barcode add-on digits: {bc['addon']}")
                report.add("barcodes_addon_trimmed", f"{title} [{fmt['name']}] → {barcode} (+{bc['addon']})")
            elif bc.get("fix") == "unverified":
                report.add("barcodes_unverified", f"{title} [{fmt['name']}] — {barcode}")
        elif bc["kind"] == "catalog":
            put("catalog_number", bc["value"], "Catalog/ID")
            report.add("catalog_numbers_moved", f"{title} [{fmt['name']}] — {bc['value']}")

        # qualifiers and markers from the title
        edition = cols.one(row, "Custom field (Edition)")
        if qualifiers:
            q = ", ".join(qualifiers)
            if not edition and applies("edition", fmt["id"]):
                edition = q
            else:
                notes.append(f"From Jira title: ({q})")
        for mk in markers:
            notes.append(f"Jira title marker: {mk}")
        if raw_title.strip() != title:
            report.add("titles_cleaned", f"{raw_title.strip()} → {title}" + (f" | edition: {edition}" if qualifiers else ""))

        # custom fields
        put("edition", edition, "Edition")
        audio = cols.one(row, "Custom field (Audio)")
        if audio:
            ensure_option("audio", audio) if applies("audio", fmt["id"]) else None
            put("audio", audio, "Audio")
        combo = []
        for v in cols.all(row, "Custom field (Additional Formats)"):
            v = "Blu-ray" if v.lower() == "blu-ray" else v
            if v not in combo:
                combo.append(v)
                if applies("combo_pack", fmt["id"]):
                    ensure_option("combo_pack", v)
        put("combo_pack", combo, "Also includes")
        aspect = cols.one(row, "Custom field (Aspect Ratio)")
        if aspect and applies("aspect_ratio", fmt["id"]):
            ensure_option("aspect_ratio", aspect)
        put("aspect_ratio", aspect, "Aspect ratio")
        if cols.one(row, "Custom field (Certification)").upper() == "THX":
            put("thx", True, "THX")
        res = cols.one(row, "Custom field (Resolution)")
        if res:
            res = "4K" if res.lower() == "4k" else res
            if applies("resolution", fmt["id"]):
                ensure_option("resolution", res)
            put("resolution", res, "Resolution")
        players = re.match(r"\s*(\d+)", cols.one(row, "Custom field (Max Player Count)"))
        if players:
            put("max_players", int(players.group(1)), "Max players")
        if cols.one(row, "Custom field (3D Support)").lower() == "yes":
            put("support_3d", True, "3D support")
        labels = cols.all(row, "Labels")
        if labels:
            tags = custom.get("tags", [])
            for lab in labels:
                if lab not in tags:
                    tags.append(lab)
            for t in tags:
                ensure_option("tags", t)
            custom["tags"] = tags
        elif "tags" in custom:
            ensure_option("tags", RESCAN_TAG)

        desc = cols.one(row, "Description")
        if desc:
            notes.insert(0, desc)
        for c in cols.all(row, "Comment"):
            m = _JIRA_COMMENT.match(c)
            notes.append((m.group(1) if m else c).strip())

        status = cols.one(row, "Status")
        if status:
            report.counts[f"status_ignored:{status}"] += 1

        records.append({
            "key": key,
            "title": title,
            "match_key": text.match_key(title) or text.search_norm(title),
            "category_id": fmt["category_id"],
            "format_id": fmt["id"],
            "format": fmt["name"],
            "year": parse_year(cols.one(row, "Custom field (Year)")),
            "barcode": barcode,
            "custom": custom,
            "notes": "\n".join(n for n in notes if n) or None,
            "created_at": parse_created(cols.one(row, "Created")),
            "added_by": cols.one(row, "Creator") or cols.one(row, "Reporter") or None,
            "parent": cols.one(row, "Parent key") or None,
            "relates": cols.all(row, "Inward issue link (Relates)") + cols.all(row, "Outward issue link (Relates)"),
        })

    for key, values in new_options.items():
        conn.execute("UPDATE fields SET options = ? WHERE key = ?", (json.dumps(fields[key]["options"]), key))
        for v in values:
            report.add("options_added", f"{fields[key]['label']}: {v}")

    # ---- pass 2: decide which copies are the same title
    uf = _UnionFind()
    by_key: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for r in records:
        by_key[(r["category_id"], r["match_key"])].append(r)
        uf.find(r["key"])
    for group in by_key.values():
        dated = sorted((r for r in group if r["year"]), key=lambda r: r["year"])
        clusters: list[list[dict]] = []
        for r in dated:
            if clusters and r["year"] - clusters[-1][0]["year"] <= YEAR_GAP:
                clusters[-1].append(r)
            else:
                clusters.append([r])
        undated = [r for r in group if not r["year"]]
        if undated:
            if clusters:
                max(clusters, key=len).extend(undated)
            else:
                clusters.append(undated)
        for cl in clusters:
            for r in cl[1:]:
                uf.union(cl[0]["key"], r["key"])
        if len(clusters) > 1:
            report.add("same_name_kept_separate", " / ".join(
                f"{cl[0]['title']} ({cl[0]['year'] or '?'}): {', '.join(sorted({x['format'] for x in cl}))}" for cl in clusters
            ))
    rec_by_key = {r["key"]: r for r in records}
    for r in records:
        for other in r["relates"]:
            o = rec_by_key.get(other)
            if o and o["category_id"] == r["category_id"] and uf.find(o["key"]) != uf.find(r["key"]):
                uf.union(r["key"], o["key"])
                report.add("linked_by_jira_relates", f"{r['title']} [{r['format']}] ↔ {o['title']} [{o['format']}]")

    clusters_by_root: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        clusters_by_root[uf.find(r["key"])].append(r)

    # ---- pass 3: box sets
    box_ids: dict[str, int] = {}
    for key, b in box_rows.items():
        name, desc = b["name"], b["description"]
        barcode = None
        m = re.search(r"barcode:\s*([\d\s-]{8,})", desc or "", re.IGNORECASE)
        if m:
            barcode = text.digits_only(m.group(1))
            desc = (desc[: m.start()] + desc[m.end():]).strip()
        row = conn.execute("SELECT id FROM box_sets WHERE name = ?", (name,)).fetchone()
        if row:
            box_ids[key] = row["id"]
            continue
        ts = now()
        cur = conn.execute(
            "INSERT INTO box_sets (name, barcode, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (name, barcode, desc or None, ts, ts),
        )
        box_ids[key] = cur.lastrowid
        report.add("box_sets_created", name)

    # ---- pass 4: titles and items
    titles_before = conn.execute("SELECT COUNT(*) FROM titles").fetchone()[0]
    for cluster in clusters_by_root.values():
        names = Counter(r["title"] for r in cluster)
        best = sorted(names.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0]))[0][0]
        years = sorted({r["year"] for r in cluster if r["year"]})
        year = years[0] if years else None
        if len(years) > 1:
            report.add("year_differences_merged", f"{best}: {', '.join(map(str, years))} → {year} ({', '.join(sorted({r['format'] for r in cluster}))})")
        title_id = find_or_create_title(conn, best, cluster[0]["category_id"], year, None)
        formats_seen = {r["format_id"] for r in cluster}
        if len(formats_seen) > 1:
            report.counts["titles_in_multiple_formats"] += 1
        for r in cluster:
            box_id = box_ids.get(r["parent"]) if r["parent"] else None
            if r["parent"] and box_id is None:
                report.warnings.append(f"{r['key']} has parent {r['parent']}, which isn't a Collection issue in this file.")
            conn.execute(
                """INSERT INTO items (title_id, format_id, barcode, box_set_id, notes, custom, added_by, source_ref,
                                      created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (title_id, r["format_id"], r["barcode"], box_id, r["notes"], json.dumps(r["custom"]),
                 r["added_by"], f"jira:{r['key']}", r["created_at"], r["created_at"]),
            )
            report.counts["items_created"] += 1
    report.counts["titles_created"] = conn.execute("SELECT COUNT(*) FROM titles").fetchone()[0] - titles_before

    # ---- pass 5: suggest box sets nobody marked (several titles sharing one barcode)
    shared: dict[str, set[str]] = defaultdict(set)
    for r in records:
        if r["barcode"] and not r["parent"]:
            shared[r["barcode"]].add(r["title"])
    for code, titles in sorted(shared.items(), key=lambda kv: -len(kv[1])):
        if len(titles) > 1:
            report.add("possible_box_sets", f"{code}: {', '.join(sorted(titles))}")


if __name__ == "__main__":  # pragma: no cover - command-line use
    import argparse
    import os
    from pathlib import Path

    from .db import connect, migrate

    parser = argparse.ArgumentParser(description="Import a Jira CSV export into MediaTracker.")
    parser.add_argument("csv_path")
    parser.add_argument("--commit", action="store_true", help="actually write (default is a dry run)")
    parser.add_argument("--db", default=os.path.join(os.environ.get("MT_DATA_DIR", "/data"), "mediatracker.db"))
    args = parser.parse_args()
    migrate(Path(args.db))
    conn = connect(Path(args.db))
    result = run_import(conn, Path(args.csv_path).read_bytes(), commit=args.commit)
    json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
    print()
