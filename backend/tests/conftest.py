from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

HDR = {"X-Requested-With": "MediaTracker"}
ADMIN_PASSWORD = "correct-horse-battery"


@pytest.fixture()
def settings(tmp_path):
    return Settings(
        data_dir=tmp_path / "data",
        static_dir=tmp_path / "static",
        admin_username="admin",
        admin_password=ADMIN_PASSWORD,
        run_maintenance=False,
    )


@pytest.fixture()
def client(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        c.headers.update(HDR)
        r = c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
        assert r.status_code == 200, r.text
        yield c


@pytest.fixture()
def meta(client):
    return client.get("/api/meta").json()


def fmt_id(meta, name):
    return next(f["id"] for f in meta["formats"] if f["name"] == name)
