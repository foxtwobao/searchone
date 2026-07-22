"""Runtime configuration for the SearchOne control plane."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ControlConfig:
    """Validated environment-backed control-plane configuration."""

    database_path: Path
    master_key: str
    session_secret: str
    admin_username: str
    admin_password: str
    proxy_direct_fallback: bool

    @classmethod
    def from_env(cls) -> "ControlConfig":
        database_path = Path(
            os.getenv(
                "SEARCHONE_DATABASE_PATH",
                REPO_ROOT / "config" / "searchone" / "data" / "searchone.db",
            )
        ).expanduser()
        config = cls(
            database_path=database_path,
            master_key=os.getenv("SEARCHONE_MASTER_KEY", ""),
            session_secret=os.getenv("SEARCHONE_SESSION_SECRET", ""),
            admin_username=os.getenv("SEARCHONE_ADMIN_USERNAME", "admin").strip()
            or "admin",
            admin_password=os.getenv("SEARCHONE_ADMIN_PASSWORD", ""),
            proxy_direct_fallback=os.getenv("SEARCHONE_PROXY_DIRECT_FALLBACK", "1")
            not in {"0", "false", "False"},
        )
        config.validate()
        config.database_path.parent.mkdir(parents=True, exist_ok=True)
        return config

    def validate(self) -> None:
        missing = [
            name
            for name, value in (
                ("SEARCHONE_MASTER_KEY", self.master_key),
                ("SEARCHONE_SESSION_SECRET", self.session_secret),
                ("SEARCHONE_ADMIN_PASSWORD", self.admin_password),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                f"missing SearchOne runtime secrets: {', '.join(missing)}"
            )
