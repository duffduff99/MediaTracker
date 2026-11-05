"""SQLite access, schema migrations and first-run seed data.

The whole database is one file (``/data/mediatracker.db``). Schema changes
are plain SQL strings in ``MIGRATIONS``; each runs once, in order, and the
number applied is stored in SQLite's ``user_version``.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path) -> sqlite3.Connection:
    # autocommit mode (we use explicit transactions); a connection is used by one request at a time,
    # but FastAPI may run a dependency and its endpoint on different worker threads
    conn = sqlite3.connect(path, timeout=10, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


class tx:
    """``with tx(conn):`` runs the block in one transaction (rolled back on error)."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        self.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        return False


MIGRATIONS: list[str] = [
    # 1 — initial schema
    """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        display_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('admin', 'editor', 'viewer')),
        prefs TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        last_login_at TEXT
    );
    CREATE TABLE sessions (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    );
    CREATE TABLE categories (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE COLLATE NOCASE,
        has_artist INTEGER NOT NULL DEFAULT 0,
        sort_order INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE formats (
        id INTEGER PRIMARY KEY,
        category_id INTEGER NOT NULL REFERENCES categories(id),
        name TEXT NOT NULL UNIQUE COLLATE NOCASE,
        color TEXT NOT NULL DEFAULT '#55504A',
        physical INTEGER NOT NULL DEFAULT 1,
        sort_order INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE titles (
        id INTEGER PRIMARY KEY,
        category_id INTEGER NOT NULL REFERENCES categories(id),
        name TEXT NOT NULL,
        match_key TEXT NOT NULL,
        artist TEXT,
        year INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX ix_titles_match ON titles(category_id, match_key);
    CREATE TABLE box_sets (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        barcode TEXT,
        notes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE items (
        id INTEGER PRIMARY KEY,
        title_id INTEGER NOT NULL REFERENCES titles(id),
        format_id INTEGER NOT NULL REFERENCES formats(id),
        barcode TEXT,
        box_set_id INTEGER REFERENCES box_sets(id) ON DELETE SET NULL,
        notes TEXT,
        custom TEXT NOT NULL DEFAULT '{}',
        added_by TEXT,
        source_ref TEXT UNIQUE,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        deleted_at TEXT
    );
    CREATE INDEX ix_items_title ON items(title_id);
    CREATE INDEX ix_items_format ON items(format_id);
    CREATE INDEX ix_items_box_set ON items(box_set_id);
    CREATE TABLE fields (
        id INTEGER PRIMARY KEY,
        key TEXT NOT NULL UNIQUE,
        label TEXT NOT NULL,
        type TEXT NOT NULL CHECK (type IN ('text', 'longtext', 'number', 'boolean', 'select', 'multiselect', 'date')),
        options TEXT NOT NULL DEFAULT '[]',
        applies_all INTEGER NOT NULL DEFAULT 1,
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE TABLE field_formats (
        field_id INTEGER NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
        format_id INTEGER NOT NULL REFERENCES formats(id) ON DELETE CASCADE,
        PRIMARY KEY (field_id, format_id)
    );
    CREATE TABLE wishlist (
        id INTEGER PRIMARY KEY,
        text TEXT NOT NULL,
        done INTEGER NOT NULL DEFAULT 0,
        added_by TEXT,
        created_at TEXT NOT NULL,
        done_at TEXT
    );
    """,
    # 2 — settings managed in the app (API keys for barcode lookups) and a cache of lookup results
    """
    CREATE TABLE app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE lookup_cache (
        source TEXT NOT NULL,
        query TEXT NOT NULL,
        status TEXT NOT NULL,
        result TEXT NOT NULL,
        fetched_at TEXT NOT NULL,
        PRIMARY KEY (source, query)
    );
    """,
]


# ------------------------------------------------------------------ seed data

SEED_CATEGORIES = [("Movies", 0), ("Music", 1), ("Games", 0)]

# (name, category, colour of the real-world case, physical?)
SEED_FORMATS = [
    ("Blu-ray", "Movies", "#1E5AA8", 1),
    ("4K Blu-ray", "Movies", "#18171A", 1),
    ("3D Blu-ray", "Movies", "#163F75", 1),
    ("HD DVD", "Movies", "#8E1B1B", 1),
    ("DVD", "Movies", "#55504A", 1),
    ("Laserdisc", "Movies", "#C9CCD1", 1),
    ("VHS", "Movies", "#6B4A2B", 1),
    ("Digital", "Movies", "#8A857D", 0),
    ("Record", "Music", "#232323", 1),
    ("CD", "Music", "#A9B1BA", 1),
    ("Cassette", "Music", "#9A4F16", 1),
    ("Xbox", "Games", "#107C10", 1),
    ("Xbox 360", "Games", "#3A7D1E", 1),
    ("PlayStation 3", "Games", "#2E3A87", 1),
    ("GameCube", "Games", "#4B3F9E", 1),
]

_MOVIE_DISCS = ["Blu-ray", "4K Blu-ray", "3D Blu-ray", "HD DVD", "DVD", "Laserdisc", "VHS"]
_GAMES = ["Xbox", "Xbox 360", "PlayStation 3", "GameCube"]
_PHYSICAL = [f[0] for f in SEED_FORMATS if f[3]]

AUDIO_OPTIONS = [
    "Dolby Digital (Surround)", "Dolby Surround (Analog)", "DTS-HD Master Audio", "Stereo",
    "Dolby Atmos", "AC3 RF", "Dolby TrueHD", "Mono", "DTS-X", "Surround PCM", "DTS-HD 5.1",
]

# (key, label, type, options, formats or None for "all formats")
SEED_FIELDS = [
    ("condition", "Condition", "select", ["New", "Great", "Good", "Poor"], _PHYSICAL),
    ("edition", "Edition", "text", [], _MOVIE_DISCS + _GAMES),
    ("audio", "Audio", "select", AUDIO_OPTIONS, _MOVIE_DISCS),
    ("combo_pack", "Combo pack", "multiselect", ["DVD", "Blu-ray"], ["Blu-ray", "4K Blu-ray", "3D Blu-ray", "HD DVD"]),
    ("aspect_ratio", "Aspect ratio", "select", ["4:3", "16:9"], ["Laserdisc", "VHS"]),
    ("thx", "THX", "boolean", [], ["Laserdisc", "VHS"]),
    ("catalog_number", "Catalog #", "text", [], ["Laserdisc", "VHS", "Record", "CD", "Cassette"]),
    ("resolution", "Resolution", "select", ["4K", "1080p", "Other"], ["Digital"]),
    ("max_players", "Max players", "number", [], _GAMES),
    ("support_3d", "3D support", "boolean", [], ["Xbox 360"]),
    ("tags", "Tags", "multiselect", ["Steelbook", "HDR", "TV", "Kinect", "Re-scan barcode"], None),
]


def seed(conn: sqlite3.Connection) -> None:
    ts = now()
    cat_ids: dict[str, int] = {}
    for i, (name, has_artist) in enumerate(SEED_CATEGORIES):
        cur = conn.execute(
            "INSERT INTO categories (name, has_artist, sort_order) VALUES (?, ?, ?)", (name, has_artist, i)
        )
        cat_ids[name] = cur.lastrowid
    fmt_ids: dict[str, int] = {}
    for i, (name, cat, color, physical) in enumerate(SEED_FORMATS):
        cur = conn.execute(
            "INSERT INTO formats (category_id, name, color, physical, sort_order) VALUES (?, ?, ?, ?, ?)",
            (cat_ids[cat], name, color, physical, i),
        )
        fmt_ids[name] = cur.lastrowid
    for i, (key, label, ftype, options, formats) in enumerate(SEED_FIELDS):
        cur = conn.execute(
            "INSERT INTO fields (key, label, type, options, applies_all, sort_order, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (key, label, ftype, json.dumps(options), 1 if formats is None else 0, i, ts),
        )
        for fname in formats or []:
            conn.execute(
                "INSERT INTO field_formats (field_id, format_id) VALUES (?, ?)", (cur.lastrowid, fmt_ids[fname])
            )


def migrate(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for index in range(version, len(MIGRATIONS)):
            with tx(conn):
                # executescript() would commit mid-way, so run statements one by one
                for statement in _split_sql(MIGRATIONS[index]):
                    conn.execute(statement)
                if index == 0:
                    seed(conn)
                conn.execute(f"PRAGMA user_version = {index + 1}")
    finally:
        conn.close()


def _split_sql(script: str) -> list[str]:
    return [s.strip() for s in script.split(";") if s.strip()]
