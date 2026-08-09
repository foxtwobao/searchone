"""SQLite persistence for SearchOne control-plane state."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from werkzeug.security import generate_password_hash


PROVIDERS = (
    ("tavily", "Tavily", "TAVILY_API_KEY"),
    ("exa", "Exa", "EXA_API_KEY"),
    ("metaso", "秘塔", "METASO_API_KEY"),
    ("zhihu", "知乎 / TikHub", "TIKHUB_TOKEN"),
    ("minimax", "MiniMax TokenPlan", "MINIMAX_API_KEY"),
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    """Small SQLite connection and schema manager."""

    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self, admin_username: str, admin_password: str) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS admin_users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS client_keys (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    key_prefix TEXT NOT NULL,
                    key_ciphertext TEXT NOT NULL,
                    key_digest TEXT NOT NULL UNIQUE,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    allowed_engines TEXT NOT NULL DEFAULT '[]',
                    rpm_limit INTEGER NOT NULL DEFAULT 60,
                    daily_limit INTEGER NOT NULL DEFAULT 1000,
                    concurrency_limit INTEGER NOT NULL DEFAULT 4,
                    max_results INTEGER NOT NULL DEFAULT 10,
                    timeout_seconds REAL NOT NULL DEFAULT 20,
                    expires_at TEXT,
                    last_used_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS provider_credentials (
                    provider TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    env_name TEXT NOT NULL,
                    secret_ciphertext TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_test_status TEXT NOT NULL DEFAULT 'untested',
                    last_test_message TEXT NOT NULL DEFAULT '',
                    last_tested_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS proxies (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    scheme TEXT NOT NULL,
                    host TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    username_ciphertext TEXT NOT NULL DEFAULT '',
                    password_ciphertext TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    weight INTEGER NOT NULL DEFAULT 1,
                    channels TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'untested',
                    exit_ip TEXT NOT NULL DEFAULT '',
                    latency_ms INTEGER,
                    last_error TEXT NOT NULL DEFAULT '',
                    last_checked_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_key_id TEXT NOT NULL REFERENCES client_keys(id) ON DELETE CASCADE,
                    occurred_at TEXT NOT NULL,
                    engines TEXT NOT NULL DEFAULT '[]',
                    status_code INTEGER NOT NULL DEFAULT 0,
                    success INTEGER NOT NULL DEFAULT 0,
                    duration_ms INTEGER,
                    result_count INTEGER NOT NULL DEFAULT 0,
                    query_hash TEXT NOT NULL,
                    error_code TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_usage_key_time
                    ON usage_events(client_key_id, occurred_at);
                CREATE INDEX IF NOT EXISTS idx_usage_time ON usage_events(occurred_at);
                """
            )
            now = utc_now()
            connection.execute(
                """
                INSERT OR IGNORE INTO admin_users
                    (id, username, password_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    admin_username,
                    generate_password_hash(admin_password, method="scrypt"),
                    now,
                    now,
                ),
            )
            for provider, display_name, env_name in PROVIDERS:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO provider_credentials
                        (provider, display_name, env_name, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (provider, display_name, env_name, now),
                )

    def audit(
        self,
        actor: str,
        action: str,
        resource_type: str,
        resource_id: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO audit_events
                    (occurred_at, actor, action, resource_type, resource_id, detail)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now(),
                    actor,
                    action,
                    resource_type,
                    resource_id,
                    json.dumps(detail or {}),
                ),
            )
