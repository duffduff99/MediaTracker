# Importing from Jira

**Where:** Settings → Import & export → Import from Jira (admins only).

1. In Jira, export the project's issues to CSV with **all fields**. The importer needs at least the `Summary`, `Issue key` and `Issue Type` columns, and uses the `Custom field (…)` columns.
2. Choose the file and press **Preview**. The whole import runs and is then rolled back, so the report shows exactly what a real import would do. Nothing is saved.
3. Open each section of the report to check the details, then press **Import**.

Running it again is safe: rows already imported (matched by Jira issue key) are skipped.

It can also be run from the command line in the container:

```bash
docker exec mediatracker python -m app.importer_jira /data/Jira.csv            # preview
docker exec mediatracker python -m app.importer_jira /data/Jira.csv --commit   # import
```

(Copy the CSV into the `data` folder first.)

## What it does with your data

Numbers in brackets are from the export analysed on 5 Nov 2026 (2,287 rows).

| Jira | MediaTracker |
|---|---|
| Issue Type | Format: `Blu-Ray` → Blu-ray, `HD-DVD` → HD DVD, `Xbox Original Game` → Xbox, `PlayStation 3 Game` → PlayStation 3, `GameCube Game` → GameCube, etc. An unknown type creates a new format |
| Issue Type `Collection` | A **box set** (8). Child issues (`Parent key`) are linked to it. A `Barcode: …` line in the description becomes the set's barcode |
| Summary | Title, cleaned up (below) |
| Year | Title year (original release) |
| Barcode | Barcode, cleaned up (below) |
| Audio, Edition, Aspect Ratio, Max Player Count, Resolution, 3D Support | The matching columns |
| Additional Formats | Combo pack |
| Certification = THX | THX = Yes |
| Labels | Tags |
| Description, Comment | Notes |
| Creator | "Added by" |
| Created | "Added" date |
| Status (Watched / Unwatched / Replace) | **Not imported**, as agreed |
| Attachment | Not imported (there was 1) |

A value that doesn't fit a column for that format (e.g. Resolution on one 4K Blu-ray) goes into Notes rather than being lost.

### Title clean-up (341 titles)

- **"Mask, The" → "The Mask"** (also "A" and "An"). Sorting and search ignore the leading article anyway.
- Trailing qualifiers like **"(Widescreen)", "(Unrated)" or "(Box Set)"** move to the **Edition** column. If Edition already had a value, they go to Notes.
- Markers like **"[REPLACE]" and "(BAD?)"** are removed from the title and noted in Notes ("Jira title marker: REPLACE").

### Linking copies of the same title (281 titles end up in 2+ formats)

Copies in the same category are the same title when their names match, ignoring:
- case and punctuation;
- a leading "The/A/An";
- a leading "007";
- trailing edition words ("Extended", "Director's Cut"…);
- bracketed qualifiers.

**Years:** copies of one name more than **10 years** apart are treated as **different films**. This keeps remakes apart: Footloose 1984/2011, The Karate Kid, Cheaper by the Dozen, A Christmas Carol and so on (23 cases, all listed in the report). Copies within 10 years are linked, and the earliest year is kept (29 cases, listed). This is a heuristic. Two things in your data to check after importing:

- *Lawrence of Arabia* (Digital 1962, Laserdisc 1989) is kept separate because the Laserdisc's year is its release year. Fix it with **Merge…** on either title page.
- *Pitch Perfect* (Digital 2012 and 2017) is linked; the 2017 one is probably *Pitch Perfect 3*. Fix it with **Not the same title** on the copy.

Your Jira "Relates" links are also used. In this export every one of them was already caught by the name matching.

### Barcode clean-up

| Problem | Count | What happens |
|---|---|---|
| Corrupted into scientific notation, e.g. `7.86936E+11` (Excel did this during the June 2023 bulk load; the real digits are gone in Jira too) | 47 | Barcode left empty, tagged **Re-scan barcode**, the original noted. Filter the grid by that tag to find them |
| 11 digits: the leading zero was lost (Excel again) | 184 | Zero restored; each is now a valid UPC |
| 14 digits: a UPC plus a 2-digit add-on | 19 | The main 12 digits kept (that's what a scanner reads); add-on noted |
| Not a barcode at all: Laserdisc/VHS catalog numbers like `LV 1180`, `ID1568` | 48 | Moved to **Catalog #** |
| `N/A` | 16 | Left empty |
| Kept, but the check digit doesn't validate (probably typos) | 6 | Listed in the report so you can re-scan them |

### Possible box sets you didn't mark

Titles that share one barcode but have no Jira parent are listed in the report, but not changed. Your data has 8, for example:
- 18 DC animated Batman films (one barcode);
- the Back to the Future trilogy;
- Sister Act 1 & 2.

To make one a set:
1. Create the box set (**Box sets → New box set**).
2. Edit each item and pick the set.
