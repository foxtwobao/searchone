"""Lazy runtime state shared by the admin UI and managed engines."""

from __future__ import annotations

import threading
import os

from .config import ControlConfig
from .crypto import SecretBox
from .db import Database
from .store import ControlStore


_LOCK = threading.Lock()
_CONFIG: ControlConfig | None = None
_DATABASE: Database | None = None
_STORE: ControlStore | None = None


def initialize_runtime() -> tuple[ControlConfig, Database, ControlStore]:
    global _CONFIG, _DATABASE, _STORE  # pylint: disable=global-statement
    if _CONFIG is not None and _DATABASE is not None and _STORE is not None:
        return _CONFIG, _DATABASE, _STORE
    with _LOCK:
        if _CONFIG is None:
            _CONFIG = ControlConfig.from_env()
            _DATABASE = Database(_CONFIG.database_path)
            _DATABASE.initialize(_CONFIG.admin_username, _CONFIG.admin_password)
            _STORE = ControlStore(_DATABASE, SecretBox(_CONFIG.master_key))
            for provider in _STORE.list_providers():
                if provider["configured"]:
                    continue
                env_secret = os.getenv(provider["env_name"], "").strip()
                if env_secret:
                    _STORE.update_provider(
                        provider["provider"], env_secret, provider["enabled"]
                    )
    assert _DATABASE is not None and _STORE is not None and _CONFIG is not None
    return _CONFIG, _DATABASE, _STORE


def get_config() -> ControlConfig:
    return initialize_runtime()[0]


def get_database() -> Database:
    return initialize_runtime()[1]


def get_store() -> ControlStore:
    return initialize_runtime()[2]


def provider_secret(env_name: str) -> tuple[bool, bool, str]:
    return get_store().get_provider_secret(env_name)
