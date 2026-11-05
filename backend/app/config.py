"""Runtime settings, read from environment variables.

Every setting has a sensible default so the container runs with no
configuration beyond a mounted /data volume.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("MT_DATA_DIR", "/data")))
    static_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("MT_STATIC_DIR", Path(__file__).resolve().parent.parent / "static")
        )
    )
    backup_keep: int = field(default_factory=lambda: _int("MT_BACKUP_KEEP", 14))
    trash_days: int = field(default_factory=lambda: _int("MT_TRASH_DAYS", 30))
    session_days: int = field(default_factory=lambda: _int("MT_SESSION_DAYS", 30))
    admin_username: str = field(default_factory=lambda: os.environ.get("MT_ADMIN_USERNAME", "admin"))
    admin_password: str | None = field(default_factory=lambda: os.environ.get("MT_ADMIN_PASSWORD") or None)
    run_maintenance: bool = field(
        default_factory=lambda: os.environ.get("MT_RUN_MAINTENANCE", "1") not in ("0", "false", "no")
    )

    @property
    def db_path(self) -> Path:
        return self.data_dir / "mediatracker.db"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"
