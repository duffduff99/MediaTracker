# MediaTracker

A self-hosted app for tracking a physical media collection — VHS, Laserdisc, Blu-ray, 4K, records, CDs, cassettes, video games — built for one job above all: **standing in a thrift store and finding out in two seconds whether you already own something.**

- **"Do I already own it?" search** by title, artist or barcode, with a camera barcode scanner on your phone. Results are grouped by title, so you see every format you own at once (GoldenEye → Blu-ray in the Bond box set, Laserdisc).
- **Configurable grid** with sortable, show/hide columns. Columns only appear for the formats they apply to (Max players for games, Aspect ratio for Laserdisc/VHS…).
- **Your own columns**: add, rename, reorder or delete columns, and edit dropdown options (e.g. Condition) — all in the app.
- **Media types** (formats and categories) managed in the app, each with its case colour.
- **Box sets**: each film stays searchable on its own and links to the set; the set page lists everything in it.
- **Overview** dashboard, **wish list** (a simple to-do list), **trash** with 30-day restore.
- **Export** to CSV or a print-ready Excel workbook (one sheet per format).
- **Jira import** for the existing collection, with automatic clean-up (see [docs/IMPORT.md](docs/IMPORT.md)).
- **Sign-in** with Admin / Editor / Viewer roles. Light and dark mode. Installable on a phone as an app (PWA).

## Running it

You need Docker, and a reverse proxy that serves it over **HTTPS** (browsers only allow the camera and "install as app" on HTTPS).

```bash
mkdir mediatracker && cd mediatracker
curl -O https://raw.githubusercontent.com/duffduff99/MediaTracker/main/docker-compose.yml
docker compose up -d
docker compose logs mediatracker | grep -A2 "First start"
```

The last command prints the generated **admin password**. Sign in as `admin`, then change it under **Settings → My account**. Point your reverse proxy at port 8080.

Full setup, updating, backups and troubleshooting: **[docs/MAINTENANCE.md](docs/MAINTENANCE.md)**.

## Documentation

| | |
|---|---|
| [docs/MAINTENANCE.md](docs/MAINTENANCE.md) | Install, update, back up, restore, troubleshoot — what you need to run it long-term |
| [docs/SPEC.md](docs/SPEC.md) | What the app does and the decisions behind it |
| [docs/IMPORT.md](docs/IMPORT.md) | Importing from Jira and what the import cleans up |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Code layout and how to run it locally, if you ever want to change something |

## Tech

One container: a Python ([FastAPI](https://fastapi.tiangolo.com/)) API that also serves a React front end. Data lives in a single SQLite file in the `/data` volume, with automatic nightly backups beside it. No separate database server.
