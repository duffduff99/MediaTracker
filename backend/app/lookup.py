"""Barcode lookups: fill in title/artist/year from free online databases.

Which sources are used depends on the category of the format picked on the Add screen:

* Music (categories with an Artist):  MusicBrainz → Discogs (needs a token)
* Everything else:                    UPCitemdb (product name) → TMDB (needs a key; movies/TV only)

Results are suggestions; the person reviews them before saving. Raw source answers are
cached in the database (found: 90 days, not found: 7 days) so re-scanning the same item
doesn't use up the free UPCitemdb allowance (about 100 lookups a day).

Hosts contacted (allow these in a firewall):
    musicbrainz.org, api.discogs.com, api.upcitemdb.com, api.themoviedb.org
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from . import text
from .db import now

USER_AGENT = "MediaTracker/1.1 ( https://github.com/duffduff99/MediaTracker )"
TIMEOUT = 8
HOSTS = ["musicbrainz.org", "api.discogs.com", "api.upcitemdb.com", "api.themoviedb.org"]

# ------------------------------------------------------------------ settings (API keys)

SETTING_KEYS = {
    "tmdb_api_key": {
        "label": "TMDB API key",
        "env": "MT_TMDB_API_KEY",
        "help": "Free for personal use. Create an account at themoviedb.org, then Settings → API. "
                "Either the 'API Key' or the 'API Read Access Token' works.",
        "url": "https://www.themoviedb.org/settings/api",
    },
    "discogs_token": {
        "label": "Discogs personal access token",
        "env": "MT_DISCOGS_TOKEN",
        "help": "Free. Create a Discogs account, then Settings → Developers → Generate new token.",
        "url": "https://www.discogs.com/settings/developers",
    },
    "upcitemdb_key": {
        "label": "UPCitemdb key (paid plans only)",
        "env": "MT_UPCITEMDB_KEY",
        "help": "Optional. Without a key the free tier is used (about 100 lookups a day).",
        "url": "https://www.upcitemdb.com/wp/docs/main/development/plan/",
    },
}
LOOKUPS_ENABLED = "lookups_enabled"


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    if row and row["value"]:
        return row["value"]
    env = SETTING_KEYS.get(key, {}).get("env")
    return (os.environ.get(env) or None) if env else None


def set_setting(conn: sqlite3.Connection, key: str, value: str | None) -> None:
    if value is None or value == "":
        conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))
    else:
        conn.execute(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, now()),
        )


def lookups_enabled(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (LOOKUPS_ENABLED,)).fetchone()
    return row is None or row["value"] != "0"


# ------------------------------------------------------------------ HTTP


class SourceError(Exception):
    """A source could not answer. ``status`` is one of: unreachable, rate_limited, auth, error."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def http_get_json(url: str, headers: dict[str, str] | None = None) -> Any:
    """GET a JSON document. Returns None for 404. Raises SourceError for anything else that isn't 2xx."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        if e.code == 429:
            raise SourceError("rate_limited", "Too many lookups for now; try again later.")
        if e.code in (401, 403):
            raise SourceError("auth", "The service refused the request (check the API key).")
        if e.code == 400:
            return None  # e.g. UPCitemdb answers 400 for a barcode it considers invalid
        raise SourceError("error", f"The service answered HTTP {e.code}.")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise SourceError("unreachable", f"Couldn't reach the service ({reason}). Is the host allowed through your firewall?")
    except ValueError:
        raise SourceError("error", "The service sent a response that isn't JSON.")


# Swappable in tests.
fetch_json: Callable[[str, dict[str, str] | None], Any] = http_get_json

_mb_lock = threading.Lock()
_mb_last = [0.0]


def _musicbrainz_get(url: str) -> Any:
    """MusicBrainz allows about one request per second per client."""
    with _mb_lock:
        wait = 1.1 - (time.monotonic() - _mb_last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            return fetch_json(url, None)
        finally:
            _mb_last[0] = time.monotonic()


# ------------------------------------------------------------------ cache


FOUND_TTL = timedelta(days=90)
NOT_FOUND_TTL = timedelta(days=7)


def _cached(conn: sqlite3.Connection, source: str, query: str, refresh: bool,
            fetch: Callable[[], list[dict]]) -> tuple[list[dict], bool]:
    """Return (results, from_cache). Errors are raised, never cached."""
    if not refresh:
        row = conn.execute("SELECT * FROM lookup_cache WHERE source = ? AND query = ?", (source, query)).fetchone()
        if row:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(row["fetched_at"])
            if age < (FOUND_TTL if row["status"] == "found" else NOT_FOUND_TTL):
                return json.loads(row["result"]), True
    results = fetch()
    conn.execute(
        "INSERT INTO lookup_cache (source, query, status, result, fetched_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(source, query) DO UPDATE SET status = excluded.status, result = excluded.result, fetched_at = excluded.fetched_at",
        (source, query, "found" if results else "not_found", json.dumps(results), now()),
    )
    return results, False


# ------------------------------------------------------------------ barcodes


def barcode_variants(code: str) -> list[str]:
    """The same product as UPC-A (12 digits) and EAN-13 (13 digits, leading 0)."""
    d = text.digits_only(code)
    out = [d]
    if len(d) == 12:
        out.append("0" + d)
    elif len(d) == 13 and d.startswith("0"):
        out.append(d[1:])
    return out


# ------------------------------------------------------------------ format keywords

_FMT_PATTERNS = {
    "4k": r"\b4k\b|ultra\s*hd|\buhd\b",
    "3d": r"\b3d\b",
    "hd dvd": r"\bhd[\s-]?dvd\b",
    "blu-ray": r"blu[\s-]?ray|bluray",
    "dvd": r"(?<!hd )(?<!hd-)\bdvd\b",
    "vhs": r"\bvhs\b",
    "laserdisc": r"laser\s*disc",
    "cd": r"\bcd\b|compact disc",
    "vinyl": r"\bvinyl\b|\blp\b|\b(7|10|12)\s*(\"|inch|in\b)",
    "cassette": r"cassette|\bmc\b",
}


def format_kind(format_name: str) -> str | None:
    """Map one of your format names to a keyword family (e.g. "4K Blu-ray" → "4k")."""
    n = format_name.lower()
    if "4k" in n or "uhd" in n:
        return "4k"
    if "3d" in n:
        return "3d"
    if "hd dvd" in n or "hd-dvd" in n:
        return "hd dvd"
    for kind in ("blu-ray", "dvd", "vhs", "laserdisc", "cassette"):
        if kind in n or kind.replace("-", "") in n:
            return kind
    if n in ("cd", "compact disc") or n.startswith("cd"):
        return "cd"
    if "record" in n or "vinyl" in n or n == "lp":
        return "vinyl"
    return None


def mentioned_formats(product: str) -> set[str]:
    s = product.lower()
    found = {k for k, p in _FMT_PATTERNS.items() if re.search(p, s)}
    # "Blu-ray 3D" mentions both; "HD DVD" shouldn't count as DVD (handled by the lookbehind)
    return found


# ------------------------------------------------------------------ product-name clean-up (UPCitemdb)

_NOISE_WORDS = [
    r"4k\s*ultra\s*hd", r"ultra\s*hd", r"\buhd\b", r"\b4k\b", r"blu[\s-]?ray\s*3d", r"3d\s*blu[\s-]?ray",
    r"blu[\s-]?ray(\s*disc)?", r"bluray", r"\bhd[\s-]?dvd\b", r"\bdvd\b", r"\bvhs\b", r"laser\s*disc",
    r"digital\s*(copy|hd|code)", r"\+\s*digital\b", r"\bdigital\b(?=\s*[\])+])", r"ultraviolet",
    r"wide\s*screen(\s*edition)?", r"full\s*screen(\s*edition)?", r"steel\s*book", r"combo\s*pack",
    r"region\s*\d", r"\bntsc\b", r"\bpal\b",
    r"xbox\s*one", r"xbox\s*360", r"\bxbox\b", r"playstation\s*\d", r"\bps\d\b", r"nintendo\s*gamecube",
    r"gamecube", r"\bwii\s*u\b", r"\bwii\b", r"nintendo\s*switch", r"nintendo",
]
_PLATFORM_OR_FORMAT = re.compile("|".join(_NOISE_WORDS) + r"|\bedition\b|\bseason\b(?!\s*\d)|\d{4}|disc|\bbonus\b", re.IGNORECASE)
_EDITION = re.compile(
    r"(\b(special|collector'?s|anniversary|limited|deluxe|ultimate|definitive|criterion|platinum|"
    r"extended|unrated|theatrical|director'?s|masterpiece|diamond|signature)\b[^,()\[\]+]*?\b(edition|cut|collection)\b"
    r"|\bunrated\b|\bextended\b|\bdirector'?s cut\b|\bsteelbook\b)",
    re.IGNORECASE,
)


_STUDIO_PREFIX = re.compile(
    # Only names that are branding, never part of a real title ("Universal Soldier" must survive).
    r"^(walt\s+)?(disney(\s*[-/]?\s*pixar)?'?s?|pixar'?s?|dreamworks'?|marvel\s+studios'?)\s*[:\-–]?\s+(?=\S)",
    re.IGNORECASE,
)
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
             "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12}


def split_season(title: str) -> tuple[str, int | None]:
    """"The Mandalorian: The Complete Third Season" → ("The Mandalorian", 3)."""
    m = re.search(r"\s*[-–:,]?\s*(the\s+)?(complete\s+)?(season|series)\s+(\d+)\b.*$", title, re.I)
    if m:
        return title[: m.start()].strip(), int(m.group(4))
    m = re.search(r"\s*[-–:,]?\s*(the\s+)?(complete\s+)?(" + "|".join(_ORDINALS) + r")\s+(season|series)\b.*$", title, re.I)
    if m:
        return title[: m.start()].strip(), _ORDINALS[m.group(3).lower()]
    return title, None


def clean_product_title(raw: str) -> str:
    """Turn a store product name into a plain title.

    "Air Force One [Blu-ray]" → "Air Force One"; "Halo 3 - Xbox 360" → "Halo 3";
    "Jurassic Park 4K Ultra HD + Blu-ray + Digital" → "Jurassic Park".
    """
    s = re.sub(r"\s+", " ", raw or "").strip()

    # bracketed qualifiers: drop ones that name a format/platform/edition/year
    def drop_bracket(m: re.Match) -> str:
        inner = m.group(0)[1:-1]
        return " " if (_PLATFORM_OR_FORMAT.search(inner) or _EDITION.search(inner)) else m.group(0)

    s = re.sub(r"\([^()]*\)|\[[^\[\]]*\]|\{[^{}]*\}", drop_bracket, s)
    # trailing " - Xbox 360" / " | Blu-ray" segments
    parts = re.split(r"\s+[-–|]\s+", s)
    while len(parts) > 1 and _PLATFORM_OR_FORMAT.search(parts[-1]) and not re.search(r"[a-z]{3,}", re.sub(_PLATFORM_OR_FORMAT, "", parts[-1]), re.I):
        parts.pop()
    while len(parts) > 1 and _PLATFORM_OR_FORMAT.search(parts[0]) and not re.search(r"[a-z]{3,}", re.sub(_PLATFORM_OR_FORMAT, "", parts[0]), re.I):
        parts.pop(0)
    s = " - ".join(parts)
    # loose format words
    for w in _NOISE_WORDS:
        s = re.sub(w, " ", s, flags=re.IGNORECASE)
    s = _EDITION.sub(" ", s)
    s = re.sub(r"\s*\+\s*(\+\s*)*", " ", s)  # "+ +" left over from "4K + Blu-ray + Digital"
    s = re.sub(r"\s+", " ", s).strip(" -–|:,/+.&")
    s = _STUDIO_PREFIX.sub("", s).strip()
    return s or (raw or "").strip()


def detect_edition(raw: str) -> str | None:
    m = _EDITION.search(raw or "")
    if not m:
        return None
    ed = m.group(0).strip()
    return None if ed.lower() == "steelbook" else ed[:1].upper() + ed[1:]


def detect_combo(raw: str, chosen_kind: str | None) -> list[str]:
    """Other formats in the package, e.g. a 4K disc whose name mentions "+ Blu-ray"."""
    s = (raw or "").lower()
    out: list[str] = []
    if chosen_kind not in mentioned_formats(s):
        return out  # the name doesn't mention the chosen format, so don't guess about the package
    if chosen_kind == "4k":
        if re.search(_FMT_PATTERNS["blu-ray"], s):
            out.append("Blu-ray")
    if chosen_kind == "3d":
        rest = re.sub(r"blu[\s-]?ray\s*3d|3d\s*blu[\s-]?ray", " ", s)
        if re.search(_FMT_PATTERNS["blu-ray"], rest):
            out.append("Blu-ray")
    if chosen_kind in ("4k", "3d", "blu-ray", "hd dvd") and re.search(_FMT_PATTERNS["dvd"], s):
        out.append("DVD")
    return out


# ------------------------------------------------------------------ sources


def musicbrainz(conn: sqlite3.Connection, barcode: str, refresh: bool) -> tuple[list[dict], bool]:
    def fetch() -> list[dict]:
        variants = barcode_variants(barcode)
        query = "barcode:(" + " OR ".join(variants) + ")"
        url = "https://musicbrainz.org/ws/2/release/?" + urllib.parse.urlencode({"query": query, "fmt": "json", "limit": 10})
        data = _musicbrainz_get(url) or {}
        out = []
        for r in data.get("releases", []):
            artist = "".join(
                (ac.get("name") or (ac.get("artist") or {}).get("name") or "") + (ac.get("joinphrase") or "")
                for ac in r.get("artist-credit", [])
            ).strip()
            labels = r.get("label-info") or []
            media = r.get("media") or []
            out.append({
                "title": r.get("title"),
                "artist": artist or None,
                "year": _year(r.get("date")),
                "catalog_number": next((li.get("catalog-number") for li in labels if li.get("catalog-number")), None),
                "label": next(((li.get("label") or {}).get("name") for li in labels if li.get("label")), None),
                "media": ", ".join(m.get("format") for m in media if m.get("format")) or None,
                "country": r.get("country"),
                "release_group": (r.get("release-group") or {}).get("id"),
                "score": r.get("score"),
                "url": f"https://musicbrainz.org/release/{r.get('id')}" if r.get("id") else None,
            })
        return out

    return _cached(conn, "musicbrainz", text.digits_only(barcode), refresh, fetch)


def musicbrainz_first_year(conn: sqlite3.Connection, release_group: str, refresh: bool) -> int | None:
    def fetch() -> list[dict]:
        data = _musicbrainz_get(f"https://musicbrainz.org/ws/2/release-group/{urllib.parse.quote(release_group)}?fmt=json") or {}
        y = _year(data.get("first-release-date"))
        return [{"year": y}] if y else []

    rows, _ = _cached(conn, "musicbrainz-rg", release_group, refresh, fetch)
    return rows[0]["year"] if rows else None


def discogs(conn: sqlite3.Connection, barcode: str, token: str, refresh: bool) -> tuple[list[dict], bool]:
    headers = {"Authorization": f"Discogs token={token}"}

    def fetch() -> list[dict]:
        results: list[dict] = []
        for variant in barcode_variants(barcode):
            url = "https://api.discogs.com/database/search?" + urllib.parse.urlencode(
                {"barcode": variant, "type": "release", "per_page": 10}
            )
            data = fetch_json(url, headers) or {}
            results = data.get("results") or []
            if results:
                break
        out = []
        for r in results:
            artist, _, title = (r.get("title") or "").partition(" - ")
            if not title:
                artist, title = "", artist
            artist = re.sub(r"\s\(\d+\)$", "", artist.strip()).rstrip("*").strip()
            out.append({
                "title": title.strip() or None,
                "artist": artist or None,
                "year": _year(r.get("year")),
                "catalog_number": (r.get("catno") or "").strip() or None,
                "label": (r.get("label") or [None])[0],
                "media": ", ".join(r.get("format") or []) or None,
                "country": r.get("country"),
                "master_id": r.get("master_id") or None,
                "url": f"https://www.discogs.com/release/{r.get('id')}" if r.get("id") else None,
            })
        return out

    return _cached(conn, "discogs", text.digits_only(barcode), refresh, fetch)


def discogs_master_year(conn: sqlite3.Connection, master_id: int, token: str, refresh: bool) -> int | None:
    def fetch() -> list[dict]:
        data = fetch_json(f"https://api.discogs.com/masters/{int(master_id)}", {"Authorization": f"Discogs token={token}"}) or {}
        y = _year(data.get("year"))
        return [{"year": y}] if y else []

    rows, _ = _cached(conn, "discogs-master", str(master_id), refresh, fetch)
    return rows[0]["year"] if rows else None


def upcitemdb(conn: sqlite3.Connection, barcode: str, key: str | None, refresh: bool) -> tuple[list[dict], bool]:
    def fetch() -> list[dict]:
        code = text.digits_only(barcode)
        if key:
            data = fetch_json(f"https://api.upcitemdb.com/prod/v1/lookup?upc={code}", {"user_key": key, "key_type": "3scale"})
        else:
            data = fetch_json(f"https://api.upcitemdb.com/prod/trial/lookup?upc={code}", None)
        data = data or {}
        if data.get("code") not in (None, "OK"):
            if data.get("code") in ("TOO_FAST", "EXCEED_LIMIT"):
                raise SourceError("rate_limited", "Daily free lookups used up; try again tomorrow.")
            return []
        return [
            {"product": it.get("title"), "brand": it.get("brand"), "category": it.get("category")}
            for it in data.get("items") or [] if it.get("title")
        ]

    return _cached(conn, "upcitemdb", text.digits_only(barcode), refresh, fetch)


def tmdb(conn: sqlite3.Connection, title: str, key: str, refresh: bool) -> tuple[list[dict], bool]:
    if key.startswith("eyJ"):  # v4 "API Read Access Token" (a JWT)
        headers: dict[str, str] | None = {"Authorization": f"Bearer {key}"}
        auth: dict[str, str] = {}
    else:  # v3 "API Key"
        headers, auth = None, {"api_key": key}

    def fetch() -> list[dict]:
        out = []
        for kind, name_key, date_key in (("movie", "title", "release_date"), ("tv", "name", "first_air_date")):
            url = f"https://api.themoviedb.org/3/search/{kind}?" + urllib.parse.urlencode(
                {"query": title, "include_adult": "false", "language": "en-US", "page": 1, **auth}
            )
            data = fetch_json(url, headers) or {}
            for r in (data.get("results") or [])[:8]:
                out.append({
                    "title": r.get(name_key),
                    "original_title": r.get("original_title") or r.get("original_name"),
                    "year": _year(r.get(date_key)),
                    "kind": kind,
                    "popularity": r.get("popularity") or 0,
                    "url": f"https://www.themoviedb.org/{kind}/{r.get('id')}" if r.get("id") else None,
                })
            if any(text.match_key(o["title"]) == text.match_key(title) for o in out):
                break  # good movie match; skip the TV search
        return out

    return _cached(conn, "tmdb", text.search_norm(title), refresh, fetch)


def check_credentials(source: str, key: str) -> tuple[bool, str]:
    """Used by Settings → Barcode lookup → Test."""
    try:
        if source == "tmdb_api_key":
            if key.startswith("eyJ"):
                data = fetch_json("https://api.themoviedb.org/3/authentication", {"Authorization": f"Bearer {key}"})
            else:
                data = fetch_json("https://api.themoviedb.org/3/authentication?" + urllib.parse.urlencode({"api_key": key}), None)
            return bool(data and data.get("success")), "TMDB accepted the key." if data and data.get("success") else "TMDB didn't accept the key."
        if source == "discogs_token":
            data = fetch_json("https://api.discogs.com/oauth/identity", {"Authorization": f"Discogs token={key}"})
            if data and data.get("username"):
                return True, f"Discogs accepted the token (account: {data['username']})."
            return False, "Discogs didn't accept the token."
        return False, "This key can't be tested here; try a barcode instead."
    except SourceError as e:
        return False, e.message


# ------------------------------------------------------------------ the lookup


def _year(value: Any) -> int | None:
    m = re.match(r"\s*(\d{4})", str(value or ""))
    if not m:
        return None
    y = int(m.group(1))
    return y if 1800 <= y <= 2200 else None


def _attempt(attempts: list[dict], source: str, status: str, message: str = "", cached: bool = False) -> None:
    attempts.append({"source": source, "status": status, "message": message, "cached": cached})


def _music_rank(kind: str | None, media: str | None) -> int:
    m = (media or "").lower()
    if not kind or not m:
        return 0
    want = {"cd": ["cd"], "vinyl": ["vinyl", '"', "lp"], "cassette": ["cassette"]}.get(kind, [])
    return 1 if any(w in m for w in want) else 0


def lookup(conn: sqlite3.Connection, meta: dict, barcode: str, format_id: int, refresh: bool = False) -> dict:
    code = text.digits_only(barcode)
    fmt = next((f for f in meta["formats"] if f["id"] == format_id), None)
    if fmt is None:
        raise ValueError("Unknown format.")
    category = next(c for c in meta["categories"] if c["id"] == fmt["category_id"])
    kind = format_kind(fmt["name"])
    applies = {f["key"]: f for f in meta["fields"] if f["applies_all"] or fmt["id"] in f["format_ids"]}
    attempts: list[dict] = []
    result: dict[str, Any] = {"barcode": code, "suggestion": None, "candidates": [], "product_name": None,
                              "warnings": [], "attempts": attempts, "existing_titles": []}
    if len(code) < 6:
        result["warnings"].append("That doesn't look like a barcode.")
        return result

    candidates: list[dict] = []

    if category["has_artist"]:
        # ---------------- music
        releases: list[dict] = []
        source = "MusicBrainz"
        try:
            releases, cached = musicbrainz(conn, code, refresh)
            _attempt(attempts, "MusicBrainz", "found" if releases else "not_found", cached=cached)
            source = "MusicBrainz"
        except SourceError as e:
            _attempt(attempts, "MusicBrainz", e.status, e.message)
        if not releases:
            token = get_setting(conn, "discogs_token")
            if not token:
                _attempt(attempts, "Discogs", "skipped", "No Discogs token set (Settings → Barcode lookup).")
            else:
                try:
                    releases, cached = discogs(conn, code, token, refresh)
                    _attempt(attempts, "Discogs", "found" if releases else "not_found", cached=cached)
                    source = "Discogs"
                except SourceError as e:
                    _attempt(attempts, "Discogs", e.status, e.message)
        releases = sorted(releases, key=lambda r: (_music_rank(kind, r.get("media")), r.get("score") or 0), reverse=True)
        for r in releases[:5]:
            custom = {}
            if r.get("catalog_number") and "catalog_number" in applies:
                custom["catalog_number"] = r["catalog_number"]
            detail = " · ".join(x for x in (r.get("media"), r.get("label"), r.get("country"), str(r["year"]) if r.get("year") else None) if x)
            candidates.append({"title": r.get("title"), "artist": r.get("artist"), "year": r.get("year"),
                               "custom": custom, "source": source, "url": r.get("url"), "detail": detail})
        if candidates:
            # Year means original release year: ask for the first release of the album.
            best = releases[0]
            try:
                if source == "MusicBrainz" and best.get("release_group"):
                    first = musicbrainz_first_year(conn, best["release_group"], refresh)
                elif source == "Discogs" and best.get("master_id"):
                    first = discogs_master_year(conn, best["master_id"], get_setting(conn, "discogs_token") or "", refresh)
                else:
                    first = None
                if first:
                    candidates[0]["year"] = first
            except SourceError:
                pass  # keep this release's own year
    else:
        # ---------------- movies, TV, games: product name first
        products: list[dict] = []
        try:
            products, cached = upcitemdb(conn, code, get_setting(conn, "upcitemdb_key"), refresh)
            _attempt(attempts, "UPCitemdb", "found" if products else "not_found", cached=cached)
        except SourceError as e:
            _attempt(attempts, "UPCitemdb", e.status, e.message)
        if products:
            product = products[0]["product"]
            result["product_name"] = product
            title = clean_product_title(product)
            custom: dict[str, Any] = {}
            edition = detect_edition(product)
            if edition and "edition" in applies:
                custom["edition"] = edition
            if re.search(r"steel\s*book", product, re.I) and "tags" in applies and "Steelbook" in applies["tags"]["options"]:
                custom["tags"] = ["Steelbook"]
            combo = [c for c in detect_combo(product, kind) if "combo_pack" in applies and c in applies["combo_pack"]["options"]]
            if combo:
                custom["combo_pack"] = combo
            mentioned = mentioned_formats(product)
            if kind and mentioned and kind not in mentioned and not (kind == "3d" and "blu-ray" in mentioned):
                result["warnings"].append(
                    f"The product name mentions {', '.join(sorted(mentioned)).upper()}, not {fmt['name']}. Check the format."
                )
            base = {"title": title, "artist": None, "year": None, "custom": custom, "source": "UPCitemdb",
                    "url": None, "detail": product}
            is_games = "game" in category["name"].lower()
            key = None if is_games else get_setting(conn, "tmdb_api_key")
            if is_games:
                pass
            elif not key:
                _attempt(attempts, "TMDB", "skipped", "No TMDB key set (Settings → Barcode lookup), so the year isn't filled in.")
            else:
                # "The Mandalorian - Season 3": search for the show, then put the season back
                query, season = split_season(title)
                suffix = f" - Season {season}" if season else ""
                try:
                    films, cached = tmdb(conn, query, key, refresh)
                    _attempt(attempts, "TMDB", "found" if films else "not_found", cached=cached)
                    exact = [f for f in films if text.match_key(f["title"]) == text.match_key(query)
                             or text.match_key(f.get("original_title")) == text.match_key(query)]
                    exact.sort(key=lambda f: f["popularity"], reverse=True)
                    for f in exact[:4]:
                        candidates.append({**base, "title": f["title"] + suffix, "year": f["year"], "source": "TMDB",
                                           "url": f["url"], "detail": f"{'TV series' if f['kind'] == 'tv' else 'Film'}"
                                           + (f" · {f['year']}" if f["year"] else "") + f" · from “{product}”"})
                    if not exact:
                        for f in sorted(films, key=lambda f: f["popularity"], reverse=True)[:3]:
                            candidates.append({**base, "title": f["title"] + suffix, "year": f["year"], "source": "TMDB",
                                               "url": f["url"], "detail": f"Possible match · from “{product}”"})
                        candidates.insert(0, base)
                except SourceError as e:
                    _attempt(attempts, "TMDB", e.status, e.message)
            if not candidates:
                candidates.append(base)

    result["candidates"] = candidates
    result["suggestion"] = candidates[0] if candidates else None

    # Titles you already own in this category with the same name → offer to link.
    seen: set[int] = set()
    for c in candidates[:3]:
        if not c.get("title"):
            continue
        rows = conn.execute(
            "SELECT * FROM titles WHERE category_id = ? AND match_key = ?",
            (category["id"], text.match_key(c["title"]) or text.search_norm(c["title"])),
        ).fetchall()
        for r in rows:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            fmts = [x[0] for x in conn.execute(
                "SELECT DISTINCT f.name FROM items i JOIN formats f ON f.id = i.format_id "
                "WHERE i.title_id = ? AND i.deleted_at IS NULL", (r["id"],))]
            if fmts:
                result["existing_titles"].append({"id": r["id"], "name": r["name"], "year": r["year"],
                                                  "artist": r["artist"], "category_id": r["category_id"], "formats": fmts})
    return result
