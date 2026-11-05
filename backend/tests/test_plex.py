"""Plex sync, against canned answers shaped like a Plex Media Server's JSON."""

from __future__ import annotations

import sqlite3

import pytest

from app import lookup, plex
from conftest import fmt_id

SECTIONS = {"MediaContainer": {"Directory": [
    {"key": "1", "type": "movie", "title": "Movies"},
    {"key": "2", "type": "show", "title": "TV Shows"},
    {"key": "3", "type": "artist", "title": "Music"},
]}}


def movie(rk, title, year, res="1080"):
    return {"ratingKey": str(rk), "title": title, "year": year, "Media": [{"videoResolution": res}]}


class FakePlex:
    def __init__(self, movies, shows=None, seasons=None, error=None):
        self.movies, self.shows, self.seasons, self.error = movies, shows or [], seasons or [], error
        self.calls = []

    def __call__(self, url, headers=None):
        self.calls.append((url, headers))
        if self.error:
            raise self.error
        path = url.split("://", 1)[1].split("/", 1)[1]
        if path.startswith("library/sections?") or path == "library/sections":
            return SECTIONS
        if path.startswith("library/sections/1/all"):
            return {"MediaContainer": {"Metadata": self.movies}}
        if path.startswith("library/sections/2/all") and "type=2" in path:
            return {"MediaContainer": {"Metadata": self.shows}}
        if path.startswith("library/sections/2/all") and "type=3" in path:
            return {"MediaContainer": {"Metadata": self.seasons}}
        return {"MediaContainer": {"friendlyName": "Duffy Plex", "version": "1.41.0"}}


@pytest.fixture()
def fake(monkeypatch):
    def install(*args, **kw):
        f = FakePlex(*args, **kw)
        monkeypatch.setattr(plex, "fetch_json", f)
        return f
    return install


def setup_plex(client, meta, sections=("1", "2")):
    all_sections = {"1": {"key": "1", "title": "Movies", "type": "movie"}, "2": {"key": "2", "title": "TV Shows", "type": "show"}}
    return client.put("/api/admin/plex", json={
        "url": "http://192.168.1.20:32400/", "token": "plex-token-WXYZ", "format_id": fmt_id(meta, "Digital"),
        "sections": [all_sections[s] for s in sections],
    }).json()


def cat(meta, name):
    return next(c["id"] for c in meta["categories"] if c["name"] == name)


def test_settings_and_connection_test(client, meta, fake):
    cfg = setup_plex(client, meta)
    assert cfg["url"] == "http://192.168.1.20:32400" and cfg["token_set"] and cfg["token_hint"] == "…WXYZ"
    assert "plex-token-WXYZ" not in str(cfg) and cfg["configured"]
    f = fake([])
    r = client.post("/api/admin/plex/test").json()
    assert r["ok"] and "Duffy Plex" in r["message"]
    assert [s["title"] for s in r["sections"]] == ["Movies", "TV Shows"]  # music libraries aren't offered
    assert f.calls[0][1]["X-Plex-Token"] == "plex-token-WXYZ"

    fake([], error=lookup.SourceError("auth", "refused"))
    r = client.post("/api/admin/plex/test").json()
    assert not r["ok"] and "token" in r["message"]

    assert client.put("/api/admin/plex", json={"url": "192.168.1.20"}).status_code == 400


def test_first_sync_takes_over_digital(client, meta, fake):
    digital, ld, bd = fmt_id(meta, "Digital"), fmt_id(meta, "Laserdisc"), fmt_id(meta, "Blu-ray")
    ge = client.post("/api/items", json={"title": "Goldeneye", "year": 1995, "format_id": ld}).json()
    afo = client.post("/api/items", json={"title": "Air Force One", "year": 1997, "format_id": digital,
                                           "custom": {"resolution": "1080p"}}).json()
    old = client.post("/api/items", json={"title": "Old Movie", "year": 1980, "format_id": digital}).json()
    twd = client.post("/api/items", json={"title": "The Walking Dead - Season 8", "year": 2017, "format_id": bd,
                                           "category_id": cat(meta, "TV")}).json()
    setup_plex(client, meta)
    fake(
        [movie(10, "GoldenEye", 1995), movie(11, "Air Force One", 1997, "4k"), movie(12, "Brand New Film", 2024, "720")],
        shows=[{"ratingKey": "100", "title": "The Walking Dead", "year": 2010}],
        seasons=[{"ratingKey": "101", "parentRatingKey": "100", "parentTitle": "The Walking Dead", "index": 8},
                 {"ratingKey": "102", "parentRatingKey": "100", "parentTitle": "The Walking Dead", "index": 0}],
    )

    preview = client.post("/api/admin/plex/sync", json={"dry_run": True}).json()
    assert preview["counts"] == {"added": 3, "linked": 1, "updated": 1, "removed": 1}
    assert client.get("/api/trash").json() == []  # nothing changed yet

    r = client.post("/api/admin/plex/sync", json={"dry_run": False}).json()
    assert r["counts"] == preview["counts"] and r["plex_titles"] == 4  # specials (season 0) skipped

    # GoldenEye's Plex copy joined the Laserdisc title; Walking Dead S8 joined the TV Blu-ray despite the year
    assert {i["format_id"] for i in client.get(f"/api/titles/{ge['title_id']}").json()["items"]} == {ld, digital}
    s8 = client.get(f"/api/titles/{twd['title_id']}").json()
    assert {i["format_id"] for i in s8["items"]} == {bd, digital} and s8["category_id"] == cat(meta, "TV")
    # Air Force One was adopted (same item), resolution updated; Old Movie went to the trash
    assert client.get(f"/api/items/{afo['id']}").json()["custom"] == {"resolution": "4K"}
    assert [i["id"] for i in client.get("/api/trash").json()] == [old["id"]]
    new = [i for i in client.get("/api/items").json() if i["title"] == "Brand New Film"][0]
    assert new["custom"] == {"resolution": "Other"} and new["added_by"] == "Plex" and new["category_id"] == cat(meta, "Movies")

    cfg = client.get("/api/admin/plex").json()
    assert cfg["auto_sync"] is True and cfg["last_sync"]["counts"]["added"] == 3
    assert client.get("/api/meta").json()["plex_format_id"] == digital

    # nothing changed in Plex → nothing changes here
    again = client.post("/api/admin/plex/sync", json={"dry_run": False}).json()
    assert again["counts"] == {} and again["unchanged"] == 4


def test_removed_from_plex_then_back(client, meta, fake):
    setup_plex(client, meta, sections=("1",))
    f = fake([movie(10, "Speed", 1994), movie(11, "Twister", 1996)])
    client.post("/api/admin/plex/sync", json={"dry_run": False})
    f.movies = [movie(10, "Speed", 1994)]
    r = client.post("/api/admin/plex/sync", json={"dry_run": False}).json()
    assert r["counts"] == {"removed": 1} and client.get("/api/trash").json()[0]["title"] == "Twister"
    f.movies = [movie(10, "Speed", 1994), movie(11, "Twister", 1996)]
    r = client.post("/api/admin/plex/sync", json={"dry_run": False}).json()
    assert r["counts"] == {"restored": 1} and client.get("/api/trash").json() == []


def test_safety_guards(client, meta, fake, settings):
    setup_plex(client, meta, sections=("1",))
    f = fake([])
    r = client.post("/api/admin/plex/sync", json={"dry_run": False})
    assert r.status_code == 400 and "no titles" in r.json()["detail"]

    f.movies = [movie(i, f"Film {i}", 2000) for i in range(1, 26)]
    client.post("/api/admin/plex/sync", json={"dry_run": False})
    f.movies = f.movies[:1]  # e.g. a drive went offline
    conn = sqlite3.connect(settings.db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    r = plex.sync(conn, scheduled=True)
    conn.close()
    assert r["counts"] == {} and "removed none" in r["warnings"][0]
    assert client.get("/api/trash").json() == []
    # a manual sync does what it's told
    r = client.post("/api/admin/plex/sync", json={"dry_run": False}).json()
    assert r["counts"]["removed"] == 24


def test_add_screen_knows_plex_format_is_managed(client, meta):
    assert client.get("/api/meta").json()["plex_format_id"] is None
