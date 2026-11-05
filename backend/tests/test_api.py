from __future__ import annotations

import io

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.main import create_app
from conftest import ADMIN_PASSWORD, HDR, fmt_id


def test_requires_login_and_csrf_header(settings):
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/meta").status_code == 401
        r = c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
        assert r.status_code == 403  # no X-Requested-With header
        r = c.post("/api/auth/login", json={"username": "admin", "password": "nope"}, headers=HDR)
        assert r.status_code == 401
        r = c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}, headers=HDR)
        assert r.status_code == 200
        assert c.get("/api/auth/me").json()["role"] == "admin"


def test_login_throttle(settings):
    with TestClient(create_app(settings)) as c:
        c.headers.update(HDR)
        for _ in range(8):
            c.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        r = c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
        assert r.status_code == 429


def test_viewer_is_read_only(client, settings, meta):
    r = client.post("/api/users", json={"username": "kid", "display_name": "Kid", "role": "viewer", "password": "viewer-pass-123"})
    assert r.status_code == 200
    with TestClient(create_app(settings)) as v:
        v.headers.update(HDR)
        assert v.post("/api/auth/login", json={"username": "kid", "password": "viewer-pass-123"}).status_code == 200
        assert v.get("/api/items").status_code == 200
        r = v.post("/api/items", json={"title": "X", "format_id": fmt_id(meta, "VHS")})
        assert r.status_code == 403
        assert v.post("/api/wishlist", json={"text": "x"}).status_code == 403


def test_cross_format_linking_and_search(client, meta):
    bd = client.post("/api/items", json={
        "title": "GoldenEye", "year": 1995, "format_id": fmt_id(meta, "Blu-ray"),
        "barcode": "883904346708", "custom": {"condition": "Great", "max_players": 4},
    }).json()
    assert bd["custom"] == {"condition": "Great"}  # max_players doesn't apply to Blu-ray
    ld = client.post("/api/items", json={"title": "goldeneye", "year": 1995, "format_id": fmt_id(meta, "Laserdisc")}).json()
    assert ld["title_id"] == bd["title_id"]
    game = client.post("/api/items", json={"title": "GoldenEye: Rogue Agent", "year": 2004, "format_id": fmt_id(meta, "Xbox")}).json()
    assert game["title_id"] != bd["title_id"]

    res = client.get("/api/search", params={"q": "goldeneye"}).json()
    assert [t["name"] for t in res["titles"]] == ["GoldenEye", "GoldenEye: Rogue Agent"]
    assert len(res["titles"][0]["items"]) == 2

    # a phone may scan the 13-digit EAN form of a 12-digit UPC
    res = client.get("/api/search", params={"q": "0883904346708"}).json()
    assert res["total_items"] == 1

    title = client.get(f"/api/titles/{bd['title_id']}").json()
    assert {i["format_id"] for i in title["items"]} == {fmt_id(meta, "Blu-ray"), fmt_id(meta, "Laserdisc")}


def test_articles_ignored_in_matching(client, meta):
    a = client.post("/api/items", json={"title": "The Mask", "format_id": fmt_id(meta, "VHS")}).json()
    b = client.post("/api/items", json={"title": "Mask", "format_id": fmt_id(meta, "DVD")}).json()
    assert a["title_id"] == b["title_id"]
    assert client.get("/api/search", params={"q": "mask"}).json()["total_titles"] == 1


def test_trash_and_restore(client, meta):
    item = client.post("/api/items", json={"title": "Tightrope", "format_id": fmt_id(meta, "VHS")}).json()
    assert client.delete(f"/api/items/{item['id']}").status_code == 200
    assert client.get("/api/items").json() == []
    assert [i["id"] for i in client.get("/api/trash").json()] == [item["id"]]
    client.post(f"/api/trash/{item['id']}/restore")
    assert len(client.get("/api/items").json()) == 1


def test_field_options_rename_and_delete(client, meta):
    item = client.post("/api/items", json={"title": "Alien", "format_id": fmt_id(meta, "Laserdisc"),
                                            "custom": {"condition": "Great"}}).json()
    cond = next(f for f in meta["fields"] if f["key"] == "condition")
    r = client.put(f"/api/fields/{cond['id']}", json={
        "label": "Condition", "options": ["Mint", "Excellent", "Good", "Poor"],
        "renames": {"Great": "Excellent"}, "applies_all": False, "format_ids": cond["format_ids"],
    })
    assert r.status_code == 200
    assert client.get(f"/api/items/{item['id']}").json()["custom"]["condition"] == "Excellent"
    client.delete(f"/api/fields/{cond['id']}")
    assert client.get(f"/api/items/{item['id']}").json()["custom"] == {}


def test_custom_field_create(client, meta):
    r = client.post("/api/fields", json={"label": "Speed (RPM)", "type": "select", "options": ["33", "45", "78"],
                                         "applies_all": False, "format_ids": [fmt_id(meta, "Record")]})
    field = next(f for f in r.json()["fields"] if f["label"] == "Speed (RPM)")
    assert field["key"] == "speed_rpm"
    item = client.post("/api/items", json={"title": "Rumours", "artist": "Fleetwood Mac",
                                            "format_id": fmt_id(meta, "Record"), "custom": {"speed_rpm": "33"}}).json()
    assert item["custom"] == {"speed_rpm": "33"}
    assert item["artist"] == "Fleetwood Mac"


def test_box_set(client, meta):
    box = client.post("/api/boxsets", json={"name": "The James Bond Collection", "barcode": "883904346708"}).json()
    for name in ("Dr. No", "Goldfinger"):
        client.post("/api/items", json={"title": name, "format_id": fmt_id(meta, "Blu-ray"), "box_set_id": box["id"]})
    detail = client.get(f"/api/boxsets/{box['id']}").json()
    assert len(detail["items"]) == 2
    res = client.get("/api/search", params={"q": "883904346708"}).json()
    assert res["box_sets"][0]["name"] == "The James Bond Collection"
    assert res["total_titles"] == 2


def test_export(client, meta):
    client.post("/api/items", json={"title": "Alien", "year": 1979, "format_id": fmt_id(meta, "Laserdisc"),
                                     "custom": {"condition": "Good", "aspect_ratio": "16:9"}})
    client.post("/api/items", json={"title": "Halo", "format_id": fmt_id(meta, "Xbox"), "custom": {"max_players": 4}})
    csv_text = client.get("/api/export.csv").content.decode("utf-8-sig")
    assert csv_text.splitlines()[0].startswith("Title,")
    wb = load_workbook(io.BytesIO(client.get("/api/export.xlsx").content))
    assert wb.sheetnames == ["Summary", "All items", "Laserdisc", "Xbox"]
    headers = [c.value for c in wb["Xbox"][1]]
    assert "Max players" in headers and "Aspect ratio" not in headers


def test_wishlist(client):
    w = client.post("/api/wishlist", json={"text": "Jaws on Laserdisc"}).json()
    client.put(f"/api/wishlist/{w['id']}", json={"done": True})
    assert client.get("/api/wishlist").json()[0]["done"] == 1
    assert client.get("/api/search", params={"q": "jaws"}).json()["wishlist"] == []


def test_spa_fallback(settings):
    settings.static_dir.mkdir(parents=True)
    (settings.static_dir / "index.html").write_text("<html>app</html>")
    with TestClient(create_app(settings)) as c:
        assert c.get("/search").text == "<html>app</html>"
        assert c.get("/api/nope").status_code == 404
        assert c.get("/../etc/passwd").text == "<html>app</html>"
