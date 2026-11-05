# Development

You don't need this to run the app. It's for making changes.

## Layout

```
backend/                 Python API (FastAPI) — also serves the built front end
  app/main.py            app setup, security headers, static file serving
  app/db.py              SQLite connection, schema migrations, first-run seed data
  app/security.py        passwords, sessions, roles, sign-in throttling
  app/services.py        shared queries: items, search, title matching
  app/text.py            title normalisation and barcode helpers
  app/routes/            API endpoints (auth/users, settings, collection, data)
  app/exporter.py        CSV and Excel export
  app/importer_jira.py   Jira CSV import
  app/maintenance.py     nightly backup, trash purge
  tests/                 pytest suite
frontend/                React + TypeScript (Vite)
  src/pages/             one file per screen
  src/components/        layout, scanner, shared UI
  src/styles.css         the whole theme (light and dark tokens at the top)
  public/                PWA manifest, service worker, icons
Dockerfile               two-stage build: front end, then the Python image
.github/workflows/       tests on every PR; image published to ghcr.io from main
```

## Running locally

```bash
# API on :8080, with data in ./data
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
MT_DATA_DIR=../data MT_ADMIN_PASSWORD=dev-password-123 uvicorn app.main:app --reload --port 8080

# front end with hot reload on :5173 (proxies /api to :8080)
cd frontend
npm install
npm run dev
```

## Tests

```bash
cd backend && pytest -q        # API, import and export tests
cd frontend && npm run build   # type-check + production build
```

## Changing the database schema

Add a new SQL string to the end of `MIGRATIONS` in `backend/app/db.py`. Never edit an existing one. It runs once, on the next start; the migration number is stored in SQLite's `user_version`.

## Releasing

Merge to `main`. GitHub Actions runs the tests and publishes `ghcr.io/duffduff99/mediatracker:latest` (plus a `sha-…` tag). Pushing a tag like `v1.2.0` also publishes `1.2.0`.
