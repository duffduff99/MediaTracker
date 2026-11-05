# MediaTracker — specification (Phase 1)

What the app does, and why it's built the way it is. Decisions here come from the requirements discussion and from analysing the existing Jira data (2,287 rows).

## Goals

1. **Quick "do I own it?" check** on a phone at rummage sales and stores, by typing or by scanning a barcode.
2. Easy to add, edit and delete records.
3. Media types and columns are managed in the app, and columns can differ per media type.
4. See every format a title is owned in.
5. Overview dashboard, simple wish list, readable/printable CSV and Excel export.
6. Runs as a single Docker container on the home network, behind the existing reverse proxy and WireGuard. Password-protected, with household users.
7. Low maintenance (see [MAINTENANCE.md](MAINTENANCE.md)).

## Data model

```
Category (Movies, TV, Music, Games)  — decides which copies can be "the same title"; Music has an Artist
Format (Blu-ray, VHS, Record…)       — name, case colour, physical or digital; used by one or more
                                       categories (Blu-ray: Movies and TV), one of them its default
Title (the work: "GoldenEye", 1995)  — name, year (original release), artist (music), category
  └─ Item (a physical copy)          — format, barcode, box set, notes, custom column values
Box set (The James Bond Collection)  — name, barcode on the outer box; items point to it
Field (a custom column)              — label, type, options, which formats it applies to
Wish list entry                      — text, done
User                                 — username, name, role, password hash, preferences
```

- **"Other formats I own"** works because every copy belongs to a title. When you add a copy, the title box suggests existing titles in that category, and picking one links the copy. Typing a new name that exactly matches an existing title (ignoring case, punctuation, a leading "The/A/An", a leading "007", trailing edition words like "Extended", and bracketed qualifiers) links to it automatically, as long as the years match.
- A movie and its video game are in different categories, so they never link ("GoldenEye" the film vs. *GoldenEye: Rogue Agent*). The same goes for a film and a TV series with the same name.
- **The category belongs to the title.** A format can serve several categories, so TV seasons on Blu-ray don't need a separate "TV Blu-ray" format. The Add screen asks for the category only when the chosen format has more than one. The grid's **Change category…** moves selected titles, with all their copies, in one go. Edit title can change one title's category.
- If two different films end up linked (e.g. a remake), **Not the same title** on the title page splits a copy off. **Merge…** does the reverse.
- **Box sets**: each film is still its own title and item, so it's searchable on its own. The item shows "In box set: …" with a link, the title page says "Part of …", and the box set page lists every item in the set. Scanning the box set's barcode finds the set and everything in it.

## Columns

**Built-in (can't be removed):** Title, Artist (music categories only), Year, Format, Barcode, Box set, Notes. Plus Added / Added by.

**Configurable (seeded from the Jira fields actually in use; add, edit, reorder or delete in Settings → Columns):**

| Column | Type | Applies to |
|---|---|---|
| Condition | Dropdown: New / Great / Good / Poor | All physical formats |
| Edition | Text | Movie discs/tapes, games |
| Audio | Dropdown (the 11 values used in Jira) | Movie discs/tapes |
| Combo pack | Multiple choice: DVD, Blu-ray | Blu-ray, 4K, 3D, HD DVD |
| Aspect ratio | Dropdown: 4:3, 16:9 | Laserdisc, VHS |
| THX | Yes/No | Laserdisc, VHS |
| Catalog # | Text | Laserdisc, VHS, Record, CD, Cassette |
| Resolution | Dropdown: 4K, 1080p, Other | Digital |
| Max players | Number | Games |
| 3D support | Yes/No | Xbox 360 |
| Tags | Multiple choice: Steelbook, HDR, TV, Kinect, Re-scan barcode | All |

- Column types: text, long text, number, yes/no, dropdown, multiple choice, date.
- Renaming a dropdown option rewrites the existing values. Deleting a column deletes its values.
- Condition's options are ordered best → worst. The sticker colour follows that position: first is teal, last is red.
- The Search grid shows a column only if it applies to the formats in view. Each user can hide columns, and that choice is saved to their account.

**Not tracked (by request):** watched/unwatched, purchase price/date/place, location, photos, individual tracks.

## Screens

- **Overview**: search bar with scan button. Totals: items, unique titles, titles owned in 2+ formats, open wish list items. Items-by-format level meters (click one to filter the grid), a category split, recent additions, and a "physical media only" toggle.
- **Search**:
  - *By title* (the default on phones): results grouped by title with every copy's format, condition, box set and key details. Also shows matching box sets and wish-list entries. When there's no match it says "Not in your collection" and offers "Add to wish list" / "Add to collection".
  - *Grid* (the default on desktop): sortable columns, category and format filters, column picker, bulk delete, CSV/Excel export of the current view.
- **Title**: every copy across formats, edit title, merge, split, add another copy.
- **Add / edit item**: format, title with suggestions, year, artist (music), barcode with scanner, a warning if the barcode is already in the collection, box set (or create a new one), the columns for that format, notes, and "Save & add another".
- **Box sets**: a list, plus a detail page showing every item in the set.
- **Wish list**: a plain to-do list.
- **Trash**: deleted items are kept 30 days. Restore is for editors; deleting permanently is for admins.
- **Settings**: My account (password, light/dark/system), Columns, Media types, Users, Import & export (Jira import, export, backup download).

## Look and feel

The "Hi-Fi Rental" direction (option C from the design mockups):
- a modern layout with retro elements where they carry meaning: an amber display-window (VFD) search bar and counters, level-meter bars, format labels coloured like the real cases, and price-sticker condition badges;
- the Archivo (variable width) and VT323 fonts, bundled in the image, not loaded from Google;
- light and dark mode, following the device unless the user picks one;
- per the design feedback, no "title spotlight" panel on the Overview, and the totals appear only once (on the cards, not repeated in the search bar).

## Security

- Every page and API call requires sign-in. Passwords are hashed with Argon2id. Sessions are random tokens in an HttpOnly, SameSite=Lax cookie, marked Secure behind HTTPS, and stored only as a SHA-256 hash.
- Roles: Viewer (read and export), Editor (change data), Admin (users, columns, media types, import, permanent delete).
- Sign-in throttling: 8 failures in 15 minutes per username or per device locks out for 15 minutes.
- Requests that change data must carry a custom header, which blocks cross-site request forgery. The app also sends strict security headers (CSP, no framing, nosniff).
- The container runs as a non-root user. On first start the admin password is random and only appears in the container log.
- Intended to be reached over HTTPS through the reverse proxy and over WireGuard, not exposed directly to the internet.

## Export

- **CSV**: the current grid view (filters and visible columns), UTF-8 with BOM so Excel opens it correctly.
- **Excel**:
  - a Summary sheet, an "All items" sheet, and one sheet per format containing only that format's columns;
  - a styled, frozen, filterable header row and striped rows;
  - set up to print landscape, one page wide, repeating the header, with page numbers.

## Barcode lookup (added after Phase 1)

When a barcode is scanned or entered on the Add screen, the server looks it up and suggests details. The person reviews the suggestion before saving. The sources depend on the category of the chosen format:

| Category | Sources, in order | What gets filled in |
|---|---|---|
| Music (categories with an Artist) | MusicBrainz, then Discogs (if a token is set) | Album title, artist, original release year, Catalog # |
| Movies / TV | UPCitemdb product name, cleaned up, then TMDB (if a key is set) | Title (with "Season N" kept for TV), original release year, Edition, Steelbook tag, Combo pack |
| Games | UPCitemdb product name, cleaned up | Title |

- **Picking the best match:** music releases whose media matches the chosen format (CD, vinyl, cassette) are preferred. The year is the album's *first* release, from the MusicBrainz release group or the Discogs master release.
- **Cleaning product names:** "GoldenEye (Blu-ray Disc, 2015)" → "GoldenEye", "Halo 3 - Xbox 360" → "Halo 3", "Disney Frozen …" → "Frozen". Format, platform and edition words are removed, and a few studio names are dropped (Disney, Pixar, DreamWorks, Marvel Studios). Words that can be part of a real title are kept ("Universal Soldier").
- **Format check:** if the product name mentions a different format from the one chosen (a DVD scanned as Blu-ray), the app warns.
- **Linking:** if the suggested title already exists in the collection, the app offers to link the new copy to it.
- **Cache:** source answers are cached in the database (found: 90 days, not found: 7 days), and errors aren't cached.
- **Keys:** optional, managed by admins in Settings → Barcode lookup, and never sent back to the browser (only the last 4 characters are shown). They can also come from environment variables.
- **Hosts contacted:** musicbrainz.org, api.discogs.com, api.upcitemdb.com, api.themoviedb.org.

## Plex sync (added after Phase 1)

Plex is the source of truth for one format, normally Digital. An admin enters the Plex address and token, picks Movie and TV libraries, and runs a Preview before the first **Sync now**. After that it syncs every hour.

- Each movie becomes one copy. Each TV season becomes one copy titled "Show - Season N", which matches physical season titles. Specials (season 0) are skipped.
- A new Plex copy links to a title already in the collection with the same name (movies: year within 1; seasons: by name only), else a title is created in Movies or TV.
- Existing copies of the format that match a Plex title are adopted. This is how the first sync takes over the Jira "Digital" items.
- Copies whose title left Plex, and copies of the format that never came from Plex, go to the trash (restorable for 30 days). A title that comes back is restored.
- Resolution (4K / 1080p / Other) is filled in for movies from Plex's media info.
- **Safety:** if Plex returns no titles, nothing changes. An automatic sync won't remove more than a quarter of the copies (or 20, whichever is more) in one go; it reports instead.
- The token is stored like the lookup keys: write-only, last 4 characters shown. The server talks to Plex's local API (default port 32400).

## Phase 2 (not built yet)

- **Offline search.** A read-only copy of the collection cached on the phone, for stores with no signal.
- Cover art.
