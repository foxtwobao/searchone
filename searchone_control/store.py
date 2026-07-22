"""High-level persistence operations for the SearchOne control plane."""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from werkzeug.security import check_password_hash

from .crypto import SecretBox, query_digest, secret_digest
from .db import Database, utc_now


def _json_list(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _row_dict(row: Any) -> dict[str, Any]:
    return dict(row) if row is not None else {}


class ControlStore:  # pylint: disable=too-many-public-methods
    """CRUD, authentication, quota, and audit operations."""

    def __init__(self, database: Database, secret_box: SecretBox):
        self.database = database
        self.secret_box = secret_box

    def verify_admin(self, username: str, password: str) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT password_hash FROM admin_users WHERE username = ?", (username,)
            ).fetchone()
        return bool(row and check_password_hash(row["password_hash"], password))

    def list_clients(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT client_keys.*,
                       COUNT(usage_events.id) AS total_requests,
                       SUM(CASE WHEN usage_events.success = 1 THEN 1 ELSE 0 END) AS successful_requests
                FROM client_keys
                LEFT JOIN usage_events ON usage_events.client_key_id = client_keys.id
                GROUP BY client_keys.id
                ORDER BY client_keys.created_at DESC
                """
            ).fetchall()
        return [self._client_public(row) for row in rows]

    def get_client(self, client_id: str, reveal: bool = False) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM client_keys WHERE id = ?", (client_id,)
            ).fetchone()
        if row is None:
            return None
        result = self._client_public(row)
        if reveal:
            result["key"] = self.secret_box.decrypt(row["key_ciphertext"])
        return result

    def create_client(self, payload: dict[str, Any]) -> dict[str, Any]:
        client_id = str(uuid.uuid4())
        api_key = "sone_" + secrets.token_urlsafe(30)
        now = utc_now()
        values = self._client_values(payload)
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO client_keys (
                    id, name, key_prefix, key_ciphertext, key_digest, enabled,
                    allowed_engines, rpm_limit, daily_limit, concurrency_limit,
                    max_results, timeout_seconds, expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    client_id,
                    values["name"],
                    api_key[:13],
                    self.secret_box.encrypt(api_key),
                    secret_digest(api_key),
                    int(values["enabled"]),
                    json.dumps(values["allowed_engines"]),
                    values["rpm_limit"],
                    values["daily_limit"],
                    values["concurrency_limit"],
                    values["max_results"],
                    values["timeout_seconds"],
                    values["expires_at"],
                    now,
                    now,
                ),
            )
        result = self.get_client(client_id, reveal=True)
        assert result is not None
        return result

    def update_client(
        self, client_id: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        values = self._client_values(payload)
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE client_keys SET
                    name = ?, enabled = ?, allowed_engines = ?, rpm_limit = ?,
                    daily_limit = ?, concurrency_limit = ?, max_results = ?,
                    timeout_seconds = ?, expires_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    values["name"],
                    int(values["enabled"]),
                    json.dumps(values["allowed_engines"]),
                    values["rpm_limit"],
                    values["daily_limit"],
                    values["concurrency_limit"],
                    values["max_results"],
                    values["timeout_seconds"],
                    values["expires_at"],
                    utc_now(),
                    client_id,
                ),
            )
        return self.get_client(client_id, reveal=True) if cursor.rowcount else None

    def rotate_client_key(self, client_id: str) -> dict[str, Any] | None:
        api_key = "sone_" + secrets.token_urlsafe(30)
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE client_keys
                SET key_prefix = ?, key_ciphertext = ?, key_digest = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    api_key[:13],
                    self.secret_box.encrypt(api_key),
                    secret_digest(api_key),
                    utc_now(),
                    client_id,
                ),
            )
        return self.get_client(client_id, reveal=True) if cursor.rowcount else None

    def delete_client(self, client_id: str) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM client_keys WHERE id = ?", (client_id,)
            )
        return bool(cursor.rowcount)

    def authenticate_client(self, api_key: str) -> dict[str, Any] | None:
        digest = secret_digest(api_key)
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM client_keys WHERE key_digest = ? AND enabled = 1",
                (digest,),
            ).fetchone()
        if row is None:
            return None
        client = self._client_public(row)
        expires_at = client.get("expires_at")
        if expires_at:
            try:
                if datetime.fromisoformat(expires_at) <= datetime.now(UTC):
                    return None
            except ValueError:
                return None
        return client

    def quota_counts(self, client_id: str) -> tuple[int, int]:
        now = datetime.now(UTC)
        minute_cutoff = (now - timedelta(minutes=1)).isoformat(timespec="seconds")
        day_cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        with self.database.connect() as connection:
            minute_count = connection.execute(
                "SELECT COUNT(*) FROM usage_events WHERE client_key_id = ? AND occurred_at >= ?",
                (client_id, minute_cutoff),
            ).fetchone()[0]
            day_count = connection.execute(
                "SELECT COUNT(*) FROM usage_events WHERE client_key_id = ? AND occurred_at >= ?",
                (client_id, day_cutoff),
            ).fetchone()[0]
        return int(minute_count), int(day_count)

    def reserve_usage(self, client_id: str, query: str, engines: list[str]) -> int:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO usage_events
                    (client_key_id, occurred_at, engines, query_hash)
                VALUES (?, ?, ?, ?)
                """,
                (client_id, utc_now(), json.dumps(engines), query_digest(query)),
            )
            connection.execute(
                "UPDATE client_keys SET last_used_at = ? WHERE id = ?",
                (utc_now(), client_id),
            )
            return int(cursor.lastrowid)

    def finalize_usage(
        self,
        usage_id: int,
        *,
        status_code: int,
        success: bool,
        duration_ms: int,
        result_count: int,
        error_code: str = "",
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE usage_events SET status_code = ?, success = ?, duration_ms = ?,
                    result_count = ?, error_code = ? WHERE id = ?
                """,
                (
                    status_code,
                    int(success),
                    duration_ms,
                    result_count,
                    error_code,
                    usage_id,
                ),
            )

    def list_providers(self, reveal: bool = True) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM provider_credentials ORDER BY display_name"
            ).fetchall()
        result = []
        for row in rows:
            item = _row_dict(row)
            item["enabled"] = bool(item["enabled"])
            item["configured"] = bool(item["secret_ciphertext"])
            item["secret"] = (
                self.secret_box.decrypt(item.pop("secret_ciphertext")) if reveal else ""
            )
            result.append(item)
        return result

    def update_provider(
        self, provider: str, secret: str, enabled: bool
    ) -> dict[str, Any] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT secret_ciphertext FROM provider_credentials WHERE provider = ?",
                (provider,),
            ).fetchone()
            if row is None:
                return None
            encrypted = (
                self.secret_box.encrypt(secret) if secret else row["secret_ciphertext"]
            )
            connection.execute(
                """
                UPDATE provider_credentials SET secret_ciphertext = ?, enabled = ?,
                    last_test_status = 'untested', last_test_message = '', updated_at = ?
                WHERE provider = ?
                """,
                (encrypted, int(enabled), utc_now(), provider),
            )
        return next(
            (item for item in self.list_providers() if item["provider"] == provider),
            None,
        )

    def get_provider_secret(self, env_name: str) -> tuple[bool, bool, str]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT enabled, secret_ciphertext FROM provider_credentials WHERE env_name = ?",
                (env_name,),
            ).fetchone()
        if row is None:
            return False, False, ""
        return (
            True,
            bool(row["enabled"]),
            self.secret_box.decrypt(row["secret_ciphertext"]),
        )

    def update_provider_test(self, provider: str, status: str, message: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE provider_credentials SET last_test_status = ?, last_test_message = ?,
                    last_tested_at = ?, updated_at = ? WHERE provider = ?
                """,
                (status, message[:300], utc_now(), utc_now(), provider),
            )

    def list_proxies(self, reveal: bool = True) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM proxies ORDER BY created_at DESC"
            ).fetchall()
        result = []
        for row in rows:
            item = _row_dict(row)
            item["enabled"] = bool(item["enabled"])
            item["channels"] = _json_list(item["channels"])
            username = self.secret_box.decrypt(item.pop("username_ciphertext"))
            password = self.secret_box.decrypt(item.pop("password_ciphertext"))
            item["username"] = username if reveal else ""
            item["password"] = password if reveal else ""
            item["configured_auth"] = bool(username or password)
            result.append(item)
        return result

    def get_proxy(self, proxy_id: str, reveal: bool = True) -> dict[str, Any] | None:
        return next(
            (item for item in self.list_proxies(reveal) if item["id"] == proxy_id), None
        )

    def save_proxy(
        self, payload: dict[str, Any], proxy_id: str | None = None
    ) -> dict[str, Any]:
        now = utc_now()
        proxy_id = proxy_id or str(uuid.uuid4())
        existing = self.get_proxy(proxy_id)
        values = self._proxy_values(payload, existing)
        if existing:
            with self.database.connect() as connection:
                connection.execute(
                    """
                    UPDATE proxies SET name = ?, scheme = ?, host = ?, port = ?,
                        username_ciphertext = ?, password_ciphertext = ?, enabled = ?,
                        weight = ?, channels = ?, status = 'untested', updated_at = ?
                    WHERE id = ?
                    """,
                    (*values, now, proxy_id),
                )
        else:
            with self.database.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO proxies (
                        id, name, scheme, host, port, username_ciphertext,
                        password_ciphertext, enabled, weight, channels, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (proxy_id, *values, now, now),
                )
        result = self.get_proxy(proxy_id)
        assert result is not None
        return result

    def create_proxies(self, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not payloads:
            return []
        now = utc_now()
        proxy_ids = [str(uuid.uuid4()) for _ in payloads]
        records = [
            (proxy_id, *self._proxy_values(payload), now, now)
            for proxy_id, payload in zip(proxy_ids, payloads, strict=True)
        ]
        with self.database.connect() as connection:
            connection.executemany(
                """
                INSERT INTO proxies (
                    id, name, scheme, host, port, username_ciphertext,
                    password_ciphertext, enabled, weight, channels, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )
        by_id = {item["id"]: item for item in self.list_proxies(reveal=False)}
        return [by_id[proxy_id] for proxy_id in proxy_ids]

    def delete_proxy(self, proxy_id: str) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
        return bool(cursor.rowcount)

    def set_proxies_enabled(self, proxy_ids: list[str], enabled: bool) -> int:
        if not proxy_ids:
            return 0
        placeholders = ", ".join("?" for _ in proxy_ids)
        with self.database.connect() as connection:
            cursor = connection.execute(
                f"UPDATE proxies SET enabled = ?, updated_at = ? "
                f"WHERE id IN ({placeholders})",
                (int(enabled), utc_now(), *proxy_ids),
            )
        return int(cursor.rowcount)

    def update_proxy_health(
        self,
        proxy_id: str,
        *,
        status: str,
        exit_ip: str = "",
        latency_ms: int | None = None,
        error: str = "",
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE proxies SET status = ?, exit_ip = ?, latency_ms = ?,
                    last_error = ?, last_checked_at = ?, updated_at = ? WHERE id = ?
                """,
                (
                    status,
                    exit_ip,
                    latency_ms,
                    error[:300],
                    utc_now(),
                    utc_now(),
                    proxy_id,
                ),
            )

    def proxy_urls_for_engine(self, engine_name: str) -> list[str]:
        rows = [item for item in self.list_proxies() if item["enabled"]]
        urls: list[str] = []
        for item in rows:
            channels = item["channels"]
            if channels and engine_name not in channels:
                continue
            auth = ""
            if item["username"]:
                auth = quote(item["username"], safe="")
                if item["password"]:
                    auth += ":" + quote(item["password"], safe="")
                auth += "@"
            url = f"{item['scheme']}://{auth}{item['host']}:{item['port']}"
            urls.extend([url] * int(item["weight"]))
        return urls

    def _proxy_values(
        self, payload: dict[str, Any], existing: dict[str, Any] | None = None
    ) -> tuple[Any, ...]:
        username = str(
            payload.get("username", existing.get("username", "") if existing else "")
        )
        password = str(
            payload.get("password", existing.get("password", "") if existing else "")
        )
        return (
            str(payload.get("name", "")).strip(),
            str(payload.get("scheme", "http")).lower(),
            str(payload.get("host", "")).strip(),
            int(payload.get("port", 0)),
            self.secret_box.encrypt(username),
            self.secret_box.encrypt(password),
            int(bool(payload.get("enabled", True))),
            max(1, int(payload.get("weight", 1))),
            json.dumps(sorted(set(str(item) for item in payload.get("channels", [])))),
        )

    def overview(self) -> dict[str, Any]:
        day_cutoff = (
            datetime.now(UTC)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
        )
        with self.database.connect() as connection:
            clients = connection.execute("SELECT COUNT(*) FROM client_keys").fetchone()[
                0
            ]
            active_clients = connection.execute(
                "SELECT COUNT(*) FROM client_keys WHERE enabled = 1"
            ).fetchone()[0]
            requests_today = connection.execute(
                "SELECT COUNT(*) FROM usage_events WHERE occurred_at >= ?",
                (day_cutoff,),
            ).fetchone()[0]
            failures_today = connection.execute(
                "SELECT COUNT(*) FROM usage_events WHERE occurred_at >= ? AND success = 0",
                (day_cutoff,),
            ).fetchone()[0]
            configured_providers = connection.execute(
                "SELECT COUNT(*) FROM provider_credentials WHERE secret_ciphertext != '' AND enabled = 1"
            ).fetchone()[0]
            healthy_proxies = connection.execute(
                "SELECT COUNT(*) FROM proxies WHERE enabled = 1 AND status = 'healthy'"
            ).fetchone()[0]
        return {
            "clients": int(clients),
            "active_clients": int(active_clients),
            "requests_today": int(requests_today),
            "failures_today": int(failures_today),
            "configured_providers": int(configured_providers),
            "healthy_proxies": int(healthy_proxies),
        }

    @staticmethod
    def _client_values(payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name", "")).strip()
        if not name:
            raise ValueError("Key 名称不能为空")
        engines = sorted(
            set(
                str(item).strip() for item in payload.get("allowed_engines", []) if item
            )
        )
        if not engines:
            raise ValueError("至少选择一个允许渠道")
        return {
            "name": name,
            "enabled": bool(payload.get("enabled", True)),
            "allowed_engines": engines,
            "rpm_limit": max(1, min(int(payload.get("rpm_limit", 60)), 10000)),
            "daily_limit": max(
                1, min(int(payload.get("daily_limit", 1000)), 10_000_000)
            ),
            "concurrency_limit": max(
                1, min(int(payload.get("concurrency_limit", 4)), 1000)
            ),
            "max_results": max(1, min(int(payload.get("max_results", 10)), 100)),
            "timeout_seconds": max(
                1.0, min(float(payload.get("timeout_seconds", 20)), 120.0)
            ),
            "expires_at": str(payload.get("expires_at") or "").strip() or None,
        }

    @staticmethod
    def _client_public(row: Any) -> dict[str, Any]:
        item = _row_dict(row)
        item.pop("key_ciphertext", None)
        item.pop("key_digest", None)
        item["enabled"] = bool(item["enabled"])
        item["allowed_engines"] = _json_list(item.get("allowed_engines"))
        item["total_requests"] = int(item.get("total_requests") or 0)
        item["successful_requests"] = int(item.get("successful_requests") or 0)
        return item
