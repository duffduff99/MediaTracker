"""Application entry point: builds the FastAPI app and serves the built front end."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from .config import Settings
from .db import connect, migrate, now
from .maintenance import loop as maintenance_loop
from .routes import auth, collection, data, settings as settings_routes
from .security import LoginThrottle, hash_password

log = logging.getLogger("mediatracker")

CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "MediaTracker"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; font-src 'self'; "
        "worker-src 'self'; manifest-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(self), microphone=(), geolocation=()",
}


def bootstrap_admin(settings: Settings) -> None:
    """On first start (no users yet) create the admin account and log its password."""
    conn = connect(settings.db_path)
    try:
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            return
        password = settings.admin_password or secrets.token_urlsafe(12)
        conn.execute(
            "INSERT INTO users (username, display_name, password_hash, role, created_at) VALUES (?, ?, ?, 'admin', ?)",
            (settings.admin_username, settings.admin_username.capitalize(), hash_password(password), now()),
        )
        if settings.admin_password:
            log.warning("Created admin user '%s' with the password from MT_ADMIN_PASSWORD.", settings.admin_username)
        else:
            banner = "=" * 64
            log.warning(
                "\n%s\n  First start: created admin user '%s'\n  Password: %s\n"
                "  Sign in and change it under Settings → My account.\n%s",
                banner, settings.admin_username, password, banner,
            )
    finally:
        conn.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        migrate(settings.db_path)
        bootstrap_admin(settings)
        task = asyncio.create_task(maintenance_loop(settings)) if settings.run_maintenance else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="MediaTracker", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.throttle = LoginThrottle()
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and request.method not in SAFE_METHODS:
            if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
                return JSONResponse({"detail": "Missing request header."}, status_code=403)
        response: Response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    app.include_router(auth.router)
    app.include_router(settings_routes.router)
    app.include_router(collection.router)
    app.include_router(data.router)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "DELETE"])
    def api_not_found(rest: str):
        return JSONResponse({"detail": "Not found."}, status_code=404)

    static_dir: Path = settings.static_dir.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        index = static_dir / "index.html"
        if not index.exists():
            return JSONResponse({"detail": "Front end not built. Run `npm run build` in frontend/."}, status_code=404)
        candidate = (static_dir / path).resolve()
        if path and candidate.is_file() and static_dir in candidate.parents:
            if path.startswith("assets/"):
                headers = {"Cache-Control": "public, max-age=31536000, immutable"}
            else:
                headers = {"Cache-Control": "no-cache"}
            return FileResponse(candidate, headers=headers)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
