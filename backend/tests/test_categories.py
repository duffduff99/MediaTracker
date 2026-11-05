"""A format can serve several categories (Blu-ray for Movies and TV); the category belongs to the title."""

from __future__ import annotations

from conftest import fmt_id


def cat_id(meta, name):
    return next(c["id"] for c in meta["categories"] if c["name"] == name)


def test_tv_category_and_shared_formats(meta):
    assert [c["name"] for c in meta["categories"]] == ["Movies", "TV", "Music", "Games"]
    tv, movies = cat_id(meta, "TV"), cat_id(meta, "Movies")
    blu = next(f for f in meta["formats"] if f["name"] == "Blu-ray")
    assert blu["category_id"] == movies and blu["category_ids"] == [movies, tv]  # default first
    record = next(f for f in meta["formats"] if f["name"] == "Record")
    assert tv not in record["category_ids"]


def test_category_comes_from_choice_or_default(client, meta):
    tv, movies = cat_id(meta, "TV"), cat_id(meta, "Movies")
    show = client.post("/api/items", json={"title": "The Walking Dead - Season 8", "format_id": fmt_id(meta, "Blu-ray"),
                                            "category_id": tv}).json()
    film = client.post("/api/items", json={"title": "Air Force One", "format_id": fmt_id(meta, "Blu-ray")}).json()
    assert show["category_id"] == tv and film["category_id"] == movies

    # same name in Movies and TV are different titles
    tv_doc = client.post("/api/items", json={"title": "Planet Earth", "format_id": fmt_id(meta, "Blu-ray"), "category_id": tv}).json()
    film_doc = client.post("/api/items", json={"title": "Planet Earth", "format_id": fmt_id(meta, "DVD")}).json()
    assert tv_doc["title_id"] != film_doc["title_id"]

    # a second copy linked to the TV title stays in TV, whatever its format's default
    again = client.post("/api/items", json={"title_id": show["title_id"], "format_id": fmt_id(meta, "4K Blu-ray")}).json()
    assert again["category_id"] == tv

    r = client.post("/api/items", json={"title": "Rumours", "format_id": fmt_id(meta, "Record"), "category_id": tv})
    assert r.status_code == 400 and "isn't set up for TV" in r.json()["detail"]


def test_change_category_in_bulk_and_on_title(client, meta):
    tv, music = cat_id(meta, "TV"), cat_id(meta, "Music")
    a = client.post("/api/items", json={"title": "Seinfeld - Season 2", "format_id": fmt_id(meta, "DVD")}).json()
    b = client.post("/api/items", json={"title_id": a["title_id"], "format_id": fmt_id(meta, "VHS")}).json()
    c = client.post("/api/items", json={"title": "Halo 3", "format_id": fmt_id(meta, "Xbox 360")}).json()
    r = client.post("/api/titles/change-category", json={"item_ids": [a["id"], b["id"], c["id"]], "category_id": tv}).json()
    assert r["moved"] == 1 and len(r["skipped"]) == 1 and "Xbox 360" in r["skipped"][0]
    assert client.get(f"/api/titles/{a['title_id']}").json()["category_id"] == tv

    r = client.put(f"/api/titles/{a['title_id']}", json={"name": "Seinfeld - Season 2", "category_id": music})
    assert r.status_code == 400
    stats = client.get("/api/stats").json()
    assert {s["category_id"]: s["count"] for s in stats["by_category"]}[tv] == 2


def test_format_categories_edit_rules(client, meta):
    tv, movies = cat_id(meta, "TV"), cat_id(meta, "Movies")
    blu = next(f for f in meta["formats"] if f["name"] == "Blu-ray")
    client.post("/api/items", json={"title": "Lost - Season 1", "format_id": blu["id"], "category_id": tv})
    body = {"name": "Blu-ray", "category_id": movies, "category_ids": [movies], "color": blu["color"], "physical": True,
            "sort_order": blu["sort_order"]}
    r = client.put(f"/api/formats/{blu['id']}", json=body)
    assert r.status_code == 409 and "TV item" in r.json()["detail"]

    record = next(f for f in meta["formats"] if f["name"] == "Record")
    r = client.put(f"/api/formats/{record['id']}", json={**body, "name": "Record", "category_id": record["category_id"],
                                                          "category_ids": [record["category_id"], tv], "color": record["color"]})
    assert tv in next(f for f in r.json()["formats"] if f["name"] == "Record")["category_ids"]

    # reordering from an older client (no category_ids) keeps the extra categories
    client.put(f"/api/formats/{blu['id']}", json={**body, "category_ids": [], "sort_order": 3})
    assert tv in next(f for f in client.get("/api/meta").json()["formats"] if f["name"] == "Blu-ray")["category_ids"]

    assert client.delete(f"/api/categories/{tv}").status_code == 409
