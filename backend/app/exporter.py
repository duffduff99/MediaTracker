"""CSV and Excel export.

The Excel workbook is laid out for reading and printing: a summary sheet,
an "All items" sheet, then one sheet per format with only the columns that
apply to that format. Every sheet has a styled, frozen, filterable header
and is set to print landscape, one page wide, with the header repeated.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from typing import Any, Callable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .services import field_applies

Column = tuple[str, str, Callable[[dict], Any]]  # key, label, getter

INK = "18171A"
PAPER = "F5F2EC"


def _fmt_value(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else ""
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return v


def all_columns(meta: dict) -> list[Column]:
    fmt = {f["id"]: f for f in meta["formats"]}
    cat = {c["id"]: c for c in meta["categories"]}
    cols: list[Column] = [
        ("title", "Title", lambda i: i["title"]),
        ("artist", "Artist", lambda i: i.get("artist")),
        ("year", "Year", lambda i: i.get("year")),
        ("format", "Format", lambda i: fmt.get(i["format_id"], {}).get("name")),
        ("category", "Category", lambda i: cat.get(i["category_id"], {}).get("name")),
        ("barcode", "Barcode", lambda i: i.get("barcode")),
        ("box_set", "Box set", lambda i: i.get("box_set_name")),
        ("notes", "Notes", lambda i: i.get("notes")),
    ]
    for f in meta["fields"]:
        cols.append((f["key"], f["label"], (lambda key: lambda i: i["custom"].get(key))(f["key"])))
    cols += [
        ("added_by", "Added by", lambda i: i.get("added_by")),
        ("created_at", "Added", lambda i: (i.get("created_at") or "")[:10]),
    ]
    return cols


def pick_columns(meta: dict, keys: list[str] | None) -> list[Column]:
    cols = all_columns(meta)
    if not keys:
        return cols
    by_key = {c[0]: c for c in cols}
    return [by_key[k] for k in keys if k in by_key]


def to_csv(items: list[dict], columns: list[Column]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c[1] for c in columns])
    for i in items:
        w.writerow([_fmt_value(c[2](i)) for c in columns])
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM so Excel detects UTF-8


# ------------------------------------------------------------------ Excel


def _sheet_name(name: str, used: set[str]) -> str:
    base = re.sub(r"[\[\]:*?/\\]", "-", name)[:31] or "Sheet"
    candidate, n = base, 2
    while candidate.lower() in used:
        suffix = f" ({n})"
        candidate, n = base[: 31 - len(suffix)] + suffix, n + 1
    used.add(candidate.lower())
    return candidate


def _style_sheet(ws, columns: list[Column], rows: list[list[Any]], title: str) -> None:
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor=INK)
    stripe = PatternFill("solid", fgColor=PAPER)
    ws.append([c[1] for c in columns])
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")
    for r in rows:
        ws.append(r)
    wrap_cols = set()
    for idx, col in enumerate(columns, start=1):
        values = [len(str(r[idx - 1])) for r in rows[:2000]] or [0]
        width = min(max(len(col[1]), max(values)) + 2, 50)
        if col[0] == "title":
            width = max(width, 24)
        ws.column_dimensions[get_column_letter(idx)].width = max(width, 6)
        if col[0] == "notes" or max(values) > 50:
            wrap_cols.add(idx)
    for row_idx in range(2, len(rows) + 2):
        if row_idx % 2 == 0:
            for cell in ws[row_idx]:
                cell.fill = stripe
        for idx in wrap_cols:
            ws.cell(row=row_idx, column=idx).alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[1].height = 20
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{len(rows) + 1}"
    ws.print_title_rows = "1:1"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_options.gridLines = False
    ws.oddHeader.left.text = f"MediaTracker — {title}"
    ws.oddHeader.right.text = "&D"
    ws.oddFooter.center.text = "Page &P of &N"


def to_xlsx(items: list[dict], meta: dict) -> bytes:
    fmt = {f["id"]: f for f in meta["formats"]}
    cat = {c["id"]: c for c in meta["categories"]}
    cols = all_columns(meta)
    custom_keys = {f["key"]: f for f in meta["fields"]}
    used: set[str] = set()
    wb = Workbook()

    # Summary
    ws = wb.active
    ws.title = _sheet_name("Summary", used)
    ws["A1"] = "MediaTracker export"
    ws["A1"].font = Font(bold=True, size=16)
    ws["A2"] = f"Created {datetime.now().strftime('%d %b %Y %H:%M')}"
    ws["A4"], ws["B4"] = "Items", len(items)
    ws["A5"], ws["B5"] = "Titles", len({i["title_id"] for i in items})
    ws["A7"], ws["B7"], ws["C7"] = "Format", "Category", "Items"
    for c in ws[7]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=INK)
    counts: dict[int, int] = {}
    for i in items:
        counts[i["format_id"]] = counts.get(i["format_id"], 0) + 1
    r = 8
    for fid, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        ws.cell(row=r, column=1, value=fmt.get(fid, {}).get("name"))
        ws.cell(row=r, column=2, value=cat.get(fmt.get(fid, {}).get("category_id"), {}).get("name"))
        ws.cell(row=r, column=3, value=n)
        r += 1
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 10

    any_artist = any(i.get("artist") for i in items)

    def keep_system(key: str, sheet_items: list[dict]) -> bool:
        if key == "artist":
            return any(i.get("artist") for i in sheet_items)
        if key == "box_set":
            return any(i.get("box_set_name") for i in sheet_items)
        return True

    # All items: system columns + fields that apply to at least half of the exported items
    def share(field: dict) -> float:
        if not items:
            return 0
        return sum(1 for i in items if field_applies(field, i["format_id"])) / len(items)

    all_cols = [
        c for c in cols
        if (c[0] not in custom_keys and (c[0] != "artist" or any_artist) and keep_system(c[0], items))
        or (c[0] in custom_keys and share(custom_keys[c[0]]) >= 0.5)
    ]
    ws = wb.create_sheet(_sheet_name("All items", used))
    _style_sheet(ws, all_cols, [[_fmt_value(c[2](i)) for c in all_cols] for i in items], "All items")

    # One sheet per format
    for f in meta["formats"]:
        sheet_items = [i for i in items if i["format_id"] == f["id"]]
        if not sheet_items:
            continue
        sheet_cols = [
            c for c in cols
            if c[0] not in ("format", "category")
            and (c[0] not in custom_keys or field_applies(custom_keys[c[0]], f["id"]))
            and (c[0] in custom_keys or keep_system(c[0], sheet_items))
            and not (c[0] == "barcode" and not f["physical"])
        ]
        ws = wb.create_sheet(_sheet_name(f["name"], used))
        _style_sheet(ws, sheet_cols, [[_fmt_value(c[2](i)) for c in sheet_cols] for i in sheet_items], f["name"])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
