"""Barcode lookup tests. The HTTP layer is replaced with canned responses shaped like each
service's documented JSON, so these run offline."""

from __future__ import annotations

import pytest

from app import lookup
from app.lookup import SourceError, clean_product_title, detect_combo, detect_edition, split_season
from conftest import fmt_id


class FakeWeb:
    """Answers fetch_json by URL substring; records every call."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[tuple[str, dict | None]] = []

    def __call__(self, url, headers=None):
        self.calls.append((url, headers))
        for needle, answer in self.routes.items():
            if needle in url:
                if isinstance(answer, Exception):
                    raise answer
                return answer
        return None

    def hits(self, needle: str) -> int:
        return sum(1 for u, _ in self.calls if needle in u)


@pytest.fixture()
def web(monkeypatch):
    def install(routes):
        fake = FakeWeb(routes)
        monkeypatch.setattr(lookup, "fetch_json", fake)
        monkeypatch.setattr(lookup.time, "sleep", lambda s: None)  # skip MusicBrainz pacing
        return fake

    return install


MB_RUMOURS = {
    "releases": [
        {
            "id": "rel-vinyl", "score": 100, "title": "Rumours", "date": "1977-02-04", "country": "US",
            "artist-credit": [{"name": "Fleetwood Mac", "artist": {"name": "Fleetwood Mac"}}],
            "label-info": [{"catalog-number": "BSK 3010", "label": {"name": "Warner Bros. Records"}}],
            "media": [{"format": "12\" Vinyl"}], "release-group": {"id": "rg-1"},
        },
        {
            "id": "rel-cd", "score": 100, "title": "Rumours", "date": "1987", "country": "US",
            "artist-credit": [{"name": "Fleetwood Mac", "joinphrase": ""}],
            "label-info": [{"catalog-number": "3010-2", "label": {"name": "Warner Bros. Records"}}],
            "media": [{"format": "CD"}], "release-group": {"id": "rg-1"},
        },
    ]
}


def test_music_from_musicbrainz_prefers_matching_media(client, meta, web):
    fake = web({"/ws/2/release/?": MB_RUMOURS, "/ws/2/release-group/rg-1": {"first-release-date": "1977-02-04"}})
    r = client.get("/api/lookup", params={"barcode": "075992731324", "format_id": fmt_id(meta, "CD")}).json()
    s = r["suggestion"]
    assert (s["title"], s["artist"], s["year"], s["source"]) == ("Rumours", "Fleetwood Mac", 1977, "MusicBrainz")
    assert s["custom"] == {"catalog_number": "3010-2"}  # the CD pressing, not the LP
    assert "barcode%3A%28075992731324+OR+0075992731324%29" in fake.calls[0][0]  # UPC and EAN forms


def test_music_falls_back_to_discogs_only_with_token(client, meta, web):
    web({"/ws/2/release/?": {"releases": []}})
    r = client.get("/api/lookup", params={"barcode": "075992731324", "format_id": fmt_id(meta, "Record")}).json()
    assert r["suggestion"] is None
    assert [(a["source"], a["status"]) for a in r["attempts"]] == [("MusicBrainz", "not_found"), ("Discogs", "skipped")]

    client.put("/api/admin/integrations", json={"values": {"discogs_token": "tok-123456789"}})
    fake = web({
        "/ws/2/release/?": {"releases": []},
        "api.discogs.com/database/search": {"results": [{
            "id": 9, "title": "Nirvana (2) - Nevermind", "year": "1991", "format": ["Cassette", "Album"],
            "label": ["DGC"], "catno": "DGCC-24425", "master_id": 13814,
        }]},
        "api.discogs.com/masters/13814": {"year": 1991},
    })
    r = client.get("/api/lookup", params={"barcode": "720642442548", "format_id": fmt_id(meta, "Cassette"), "refresh": True}).json()
    s = r["suggestion"]
    assert (s["title"], s["artist"], s["year"], s["source"]) == ("Nevermind", "Nirvana", 1991, "Discogs")
    assert s["custom"] == {"catalog_number": "DGCC-24425"}
    assert all(h == {"Authorization": "Discogs token=tok-123456789"} for u, h in fake.calls if "discogs" in u)


UPC_GOLDENEYE = {"code": "OK", "total": 1, "items": [{"title": "GoldenEye (Blu-ray Disc, 2015)", "brand": "MGM"}]}
TMDB_GOLDENEYE = {"results": [
    {"id": 710, "title": "GoldenEye", "original_title": "GoldenEye", "release_date": "1995-11-16", "popularity": 30},
    {"id": 99, "title": "GoldenEye: The Making Of", "release_date": "2006-01-01", "popularity": 1},
]}


def test_movie_with_tmdb_links_to_existing_title(client, meta, web):
    existing = client.post("/api/items", json={"title": "Goldeneye", "year": 1995, "format_id": fmt_id(meta, "Laserdisc")}).json()
    client.put("/api/admin/integrations", json={"values": {"tmdb_api_key": "abcdef0123456789"}})
    fake = web({"api.upcitemdb.com/prod/trial/lookup": UPC_GOLDENEYE, "api.themoviedb.org/3/search/movie": TMDB_GOLDENEYE})
    r = client.get("/api/lookup", params={"barcode": "883904346708", "format_id": fmt_id(meta, "Blu-ray")}).json()
    s = r["suggestion"]
    assert (s["title"], s["year"], s["source"]) == ("GoldenEye", 1995, "TMDB")
    assert r["product_name"] == "GoldenEye (Blu-ray Disc, 2015)"
    assert r["existing_titles"][0]["id"] == existing["title_id"]
    assert "api_key=abcdef0123456789" in next(u for u, _ in fake.calls if "themoviedb" in u)
    assert fake.hits("search/tv") == 0  # an exact film match skips the TV search


def test_tmdb_read_access_token_uses_bearer_header(client, meta, web):
    client.put("/api/admin/integrations", json={"values": {"tmdb_api_key": "eyJhbGciOiJIUzI1NiJ9.x.y"}})
    fake = web({"upcitemdb": UPC_GOLDENEYE, "search/movie": TMDB_GOLDENEYE})
    client.get("/api/lookup", params={"barcode": "883904346708", "format_id": fmt_id(meta, "Blu-ray")})
    url, headers = next(c for c in fake.calls if "themoviedb" in c[0])
    assert "api_key" not in url and headers == {"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.x.y"}


def test_movie_without_tmdb_key_uses_cleaned_product_name(client, meta, web):
    web({"upcitemdb": {"code": "OK", "items": [{"title": "Jurassic Park 4K Ultra HD + Blu-ray + Digital [Steelbook]"}]}})
    r = client.get("/api/lookup", params={"barcode": "025192387760", "format_id": fmt_id(meta, "4K Blu-ray")}).json()
    s = r["suggestion"]
    assert (s["title"], s["year"]) == ("Jurassic Park", None)
    assert s["custom"] == {"tags": ["Steelbook"], "combo_pack": ["Blu-ray"]}
    assert ("TMDB", "skipped") in [(a["source"], a["status"]) for a in r["attempts"]]


def test_format_mismatch_warning_and_games_skip_tmdb(client, meta, web):
    client.put("/api/admin/integrations", json={"values": {"tmdb_api_key": "abcdef0123456789"}})
    web({"upcitemdb": {"code": "OK", "items": [{"title": "The Dark Knight (Widescreen Edition) DVD"}]}})
    r = client.get("/api/lookup", params={"barcode": "012569593282", "format_id": fmt_id(meta, "Blu-ray")}).json()
    assert r["warnings"] and "DVD" in r["warnings"][0]

    fake = web({"upcitemdb": {"code": "OK", "items": [{"title": "Halo 3 - Xbox 360"}]}})
    r = client.get("/api/lookup", params={"barcode": "882224446530", "format_id": fmt_id(meta, "Xbox 360")}).json()
    assert r["suggestion"]["title"] == "Halo 3"
    assert fake.hits("themoviedb") == 0


def test_tv_season(client, meta, web):
    client.put("/api/admin/integrations", json={"values": {"tmdb_api_key": "abcdef0123456789"}})
    web({
        "upcitemdb": {"code": "OK", "items": [{"title": "The Mandalorian: The Complete Third Season (Blu-ray)"}]},
        "search/movie": {"results": []},
        "search/tv": {"results": [{"id": 82856, "name": "The Mandalorian", "first_air_date": "2019-11-12", "popularity": 50}]},
    })
    r = client.get("/api/lookup", params={"barcode": "786936899306", "format_id": fmt_id(meta, "Blu-ray")}).json()
    assert (r["suggestion"]["title"], r["suggestion"]["year"]) == ("The Mandalorian - Season 3", 2019)


def test_cache_and_errors(client, meta, web):
    fake = web({"upcitemdb": UPC_GOLDENEYE})
    params = {"barcode": "883904346708", "format_id": fmt_id(meta, "Blu-ray")}
    client.get("/api/lookup", params=params)
    second = client.get("/api/lookup", params=params).json()
    assert fake.hits("upcitemdb") == 1 and second["attempts"][0]["cached"] is True
    client.get("/api/lookup", params={**params, "refresh": True})
    assert fake.hits("upcitemdb") == 2

    web({"upcitemdb": SourceError("rate_limited", "Too many")})
    r = client.get("/api/lookup", params={"barcode": "111111111117", "format_id": fmt_id(meta, "Blu-ray")}).json()
    assert r["suggestion"] is None and r["attempts"][0]["status"] == "rate_limited"
    web({"upcitemdb": {"code": "OK", "items": [{"title": "Speed [Blu-ray]"}]}})  # errors weren't cached
    r = client.get("/api/lookup", params={"barcode": "111111111117", "format_id": fmt_id(meta, "Blu-ray")}).json()
    assert r["suggestion"]["title"] == "Speed"


def test_integrations_settings_are_admin_only_and_never_return_keys(client, settings, web):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from conftest import HDR

    r = client.put("/api/admin/integrations", json={"values": {"discogs_token": "secret-token-ABCD"}}).json()
    discogs = next(k for k in r["keys"] if k["key"] == "discogs_token")
    assert discogs["set"] and discogs["hint"] == "…ABCD"
    assert "secret-token-ABCD" not in str(r)
    assert set(r["hosts"]) == {"musicbrainz.org", "api.discogs.com", "api.upcitemdb.com", "api.themoviedb.org"}

    client.post("/api/users", json={"username": "ed", "display_name": "Ed", "role": "editor", "password": "editor-pass-123"})
    with TestClient(create_app(settings)) as ed:
        ed.headers.update(HDR)
        ed.post("/api/auth/login", json={"username": "ed", "password": "editor-pass-123"})
        assert ed.get("/api/admin/integrations").status_code == 403

    client.put("/api/admin/integrations", json={"lookups_enabled": False})
    assert client.get("/api/meta").json()["lookups_enabled"] is False
    assert client.get("/api/lookup", params={"barcode": "883904346708", "format_id": 1}).status_code == 409

    web({"api.discogs.com/oauth/identity": {"username": "travis"}})
    assert client.post("/api/admin/integrations/test", json={"key": "discogs_token"}).json() == {
        "ok": True, "message": "Discogs accepted the token (account: travis)."}


@pytest.mark.parametrize("raw,title", [
    ("Air Force One [Blu-ray]", "Air Force One"),
    ("Halo 3 - Xbox 360", "Halo 3"),
    ("Jurassic Park 4K Ultra HD + Blu-ray + Digital", "Jurassic Park"),
    ("The Dark Knight (Widescreen Edition) (2008) DVD", "The Dark Knight"),
    ("(500) Days of Summer [Blu-ray]", "(500) Days of Summer"),
    ("Disney Frozen Blu-ray + DVD + Digital Copy Combo Pack", "Frozen"),
    ("Universal Soldier (DVD)", "Universal Soldier"),
    ("Super Smash Bros Melee - Nintendo GameCube", "Super Smash Bros Melee"),
    ("The Lord of the Rings: The Fellowship of the Ring Extended Edition Blu-ray",
     "The Lord of the Rings: The Fellowship of the Ring"),
])
def test_clean_product_title(raw, title):
    assert clean_product_title(raw) == title


def test_edition_combo_and_season_helpers():
    assert detect_edition("Fellowship of the Ring Extended Edition Blu-ray") == "Extended Edition"
    assert detect_edition("Air Force One [Blu-ray]") is None
    assert detect_combo("Up (Blu-ray/DVD Combo)", "blu-ray") == ["DVD"]
    assert detect_combo("Air Force One [Blu-ray]", "4k") == []  # name doesn't mention 4K: don't guess
    assert split_season("The Walking Dead - Season 8") == ("The Walking Dead", 8)
    assert split_season("Seinfeld: The Complete Second Season") == ("Seinfeld", 2)
