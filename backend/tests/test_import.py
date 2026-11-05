from __future__ import annotations

import csv
import io

from app.importer_jira import clean_title, parse_barcode
from conftest import fmt_id

HEADER = [
    "Summary", "Issue key", "Issue Type", "Status", "Creator", "Created", "Labels", "Labels", "Description",
    "Inward issue link (Relates)", "Outward issue link (Relates)", "Custom field (3D Support)",
    "Custom field (Additional Formats)", "Custom field (Additional Formats)", "Custom field (Aspect Ratio)",
    "Custom field (Audio)", "Custom field (Barcode)", "Custom field (Barcode)", "Custom field (Certification)",
    "Custom field (Edition)", "Custom field (Max Player Count)", "Custom field (Resolution)", "Custom field (Year)",
    "Comment", "Parent key",
]


def row(summary, key, itype, **kw):
    values = {h: "" for h in HEADER}
    values.update({"Summary": summary, "Issue key": key, "Issue Type": itype, "Status": kw.pop("status", "Unwatched"),
                   "Creator": kw.pop("creator", "Travis Duffy"), "Created": "10/Jun/23 12:32 AM"})
    mapping = {
        "barcode": "Custom field (Barcode)", "year": "Custom field (Year)", "audio": "Custom field (Audio)",
        "aspect": "Custom field (Aspect Ratio)", "cert": "Custom field (Certification)",
        "edition": "Custom field (Edition)", "players": "Custom field (Max Player Count)",
        "resolution": "Custom field (Resolution)", "comment": "Comment", "parent": "Parent key",
        "outward": "Outward issue link (Relates)", "description": "Description",
    }
    for k, v in kw.items():
        if k == "labels":
            continue
        values[mapping[k]] = v
    out = [values[h] for h in HEADER]
    labels = kw.get("labels", [])
    for i, lab in enumerate(labels[:2]):
        out[HEADER.index("Labels") + i] = lab
    return out


def addl(r, *formats):
    i = HEADER.index("Custom field (Additional Formats)")
    for n, f in enumerate(formats):
        r[i + n] = f
    return r


ROWS = [
    row("Air Force One", "MEDIA-10", "Blu-Ray", barcode="043396269514", year="1997.0",
        audio="Dolby Digital (Surround)", outward="MEDIA-12"),
    row("Air Force One", "MEDIA-11", "VHS", barcode="43396317734", year="1997.0"),
    row("Air Force One", "MEDIA-12", "Laserdisc", barcode="43396718869", year="1997.0", cert="THX", aspect="4:3",
        comment="20/Aug/24 1:53 PM;5a28;This release has laser rot", status="Watched"),
    row("Toy Story", "MEDIA-13", "Laserdisc", barcode="7.86936E+11", year="1995.0"),
    row("Mask, The", "MEDIA-14", "Laserdisc", barcode="LV 1180", year="1994.0"),
    row("The Mask", "MEDIA-15", "VHS", year="1995.0"),
    row("Footloose", "MEDIA-16", "Blu-Ray", year="2011.0"),
    row("Footloose", "MEDIA-17", "Digital", year="1984.0", resolution="4k", status="Replace"),
    row("Men in Black (Widescreen)", "MEDIA-18", "VHS", year="1997.0"),
    addl(row("[REPLACE] Knocked Up (Unrated)", "MEDIA-19", "Blu-Ray", year="2007.0"), "DVD"),
    row("The James Bond Collection", "MEDIA-20", "Collection", description="Barcode: 883904346708"),
    row("Goldeneye", "MEDIA-21", "Blu-Ray", year="1995.0", parent="MEDIA-20", barcode="883904346708",
        labels=["Steelbook"]),
    row("Halo 2", "MEDIA-22", "Xbox Original Game", players="4 Player", year="2004.0", creator="Collin Duffy"),
    row("The Heat", "MEDIA-23", "Blu-Ray", barcode="02454386624480", year="2013.0"),
    row("Back To the Future", "MEDIA-24", "Blu-Ray", barcode="191329144671", year="1985.0"),
    row("Back to the Future Part II", "MEDIA-25", "Blu-Ray", barcode="191329144671", year="1989.0"),
    row("Walking Dead, The - Season 8", "MEDIA-26", "Blu-Ray", year="2017.0", labels=["TV"]),
]


def csv_bytes(rows=ROWS) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HEADER)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def test_clean_title():
    assert clean_title("Mask, The") == ("The Mask", [], [])
    assert clean_title("Expendables, The: 3 Film Collection") == ("The Expendables: 3 Film Collection", [], [])
    assert clean_title("[REPLACE] Knocked Up (Unrated)") == ("Knocked Up", ["Unrated"], ["REPLACE"])
    assert clean_title("Robocop  (BAD?)") == ("Robocop", [], ["BAD?"])
    assert clean_title("Monsters, Inc") == ("Monsters, Inc", [], [])
    assert clean_title("(500) Days of Summer") == ("(500) Days of Summer", [], [])


def test_match_key_rules():
    from app.text import match_key

    assert match_key("007: GoldenEye") == match_key("Goldeneye") == "goldeneye"
    assert match_key("The Hobbit - An Unexpected Journey Extended") == match_key("The Hobbit: An Unexpected Journey")
    assert match_key("Men in Black (Widescreen)") == match_key("Men in Black")
    assert match_key("Logan Lucky") != match_key("Logan")
    assert match_key("Extended") == "extended"  # never strips a title down to nothing


def test_parse_barcode():
    assert parse_barcode("7.86936E+11")["kind"] == "rescan"
    assert parse_barcode("43396317734") == {"kind": "barcode", "value": "043396317734", "fix": "leading_zero"}
    assert parse_barcode("02454386624480")["value"] == "024543866244"
    assert parse_barcode("LV 1180") == {"kind": "catalog", "value": "LV 1180"}
    assert parse_barcode("N/A") == {"kind": "empty"}
    assert parse_barcode("80196")["kind"] == "catalog"


def _upload(client, commit):
    return client.post(
        "/api/import/jira", params={"commit": str(commit).lower()},
        files={"file": ("Jira.csv", csv_bytes(), "text/csv")},
    )


def test_dry_run_changes_nothing(client):
    r = _upload(client, False)
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["committed"] is False
    assert report["counts"]["items_created"] == 16
    assert client.get("/api/items").json() == []


def test_import(client, meta):
    report = _upload(client, True).json()
    c = report["counts"]
    assert c["items_created"] == 16
    assert c["tv_category"] == 1
    assert c["box_sets_created"] == 1
    assert c["barcodes_need_rescan"] == 1
    assert c["barcodes_leading_zero_restored"] == 2
    assert c["barcodes_addon_trimmed"] == 1
    assert c["catalog_numbers_moved"] == 1
    assert any("191329144671" in s for s in report["lists"]["possible_box_sets"])

    items = client.get("/api/items").json()
    by_key = {i["source_ref"]: i for i in items}

    # Air Force One: three formats, one title, cleaned fields
    afo = [by_key[f"jira:MEDIA-{n}"] for n in (10, 11, 12)]
    assert len({i["title_id"] for i in afo}) == 1
    assert afo[1]["barcode"] == "043396317734"
    assert afo[2]["custom"] == {"thx": True, "aspect_ratio": "4:3"}
    assert "laser rot" in afo[2]["notes"]

    # The Mask: "Mask, The" and "The Mask" are one title; catalog number moved
    assert by_key["jira:MEDIA-14"]["title"] == "The Mask"
    assert by_key["jira:MEDIA-14"]["title_id"] == by_key["jira:MEDIA-15"]["title_id"]
    assert by_key["jira:MEDIA-14"]["custom"]["catalog_number"] == "LV 1180"

    # Footloose 1984 vs 2011 stay separate titles
    assert by_key["jira:MEDIA-16"]["title_id"] != by_key["jira:MEDIA-17"]["title_id"]
    assert by_key["jira:MEDIA-17"]["custom"] == {"resolution": "4K"}

    # Corrupted barcode cleared and tagged
    toy = by_key["jira:MEDIA-13"]
    assert toy["barcode"] is None and toy["custom"]["tags"] == ["Re-scan barcode"]

    # Title qualifiers and markers
    ku = by_key["jira:MEDIA-19"]
    assert ku["title"] == "Knocked Up"
    assert ku["custom"]["edition"] == "Unrated"
    assert ku["custom"]["combo_pack"] == ["DVD"]
    assert "REPLACE" in ku["notes"]
    assert by_key["jira:MEDIA-18"]["custom"]["edition"] == "Widescreen"

    # Box set
    ge = by_key["jira:MEDIA-21"]
    assert ge["box_set_name"] == "The James Bond Collection"
    assert ge["box_set_barcode"] == "883904346708"
    assert ge["custom"]["tags"] == ["Steelbook"]

    # Game fields, creator kept
    halo = by_key["jira:MEDIA-22"]
    assert halo["custom"] == {"max_players": 4} and halo["added_by"] == "Collin Duffy"
    assert halo["format_id"] == fmt_id(meta, "Xbox")

    # Jira's "TV" label puts the item in the TV category (and keeps the tag)
    wd = by_key["jira:MEDIA-26"]
    assert wd["title"] == "The Walking Dead - Season 8" and wd["custom"]["tags"] == ["TV"]
    assert wd["category_id"] == next(c["id"] for c in meta["categories"] if c["name"] == "TV")

    # Re-running skips everything already imported
    again = _upload(client, True).json()
    assert again["counts"].get("items_created", 0) == 0
    assert again["counts"]["skipped_already_imported"] == 16
