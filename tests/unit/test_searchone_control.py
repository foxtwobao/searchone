# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the SearchOne control plane."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from searchone_control.bootstrap import ensure_runtime_secrets
from searchone_control.crypto import SecretBox
from searchone_control.db import Database
from searchone_control.networking import (
    parse_proxy_url,
    proxy_identity,
    test_proxies_concurrently,
)
from searchone_control.store import ControlStore


class SearchOneControlStoreTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.tempdir.name) / "searchone.db")
        self.database.initialize("admin", "secret-password")
        self.store = ControlStore(
            self.database, SecretBox(Fernet.generate_key().decode("ascii"))
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def test_client_key_is_revealable_and_authenticates(self):
        client = self.store.create_client(
            {
                "name": "AgentOne",
                "allowed_engines": ["tavily", "bing"],
                "rpm_limit": 5,
                "daily_limit": 50,
                "concurrency_limit": 2,
                "max_results": 6,
                "timeout_seconds": 12,
            }
        )

        self.assertTrue(client["key"].startswith("sone_"))
        authenticated = self.store.authenticate_client(client["key"])
        self.assertIsNotNone(authenticated)
        self.assertEqual(authenticated["allowed_engines"], ["bing", "tavily"])
        self.assertEqual(
            self.store.get_client(client["id"], reveal=True)["key"], client["key"]
        )

    def test_usage_counts_and_rotation(self):
        client = self.store.create_client(
            {"name": "AgentOne", "allowed_engines": ["tavily"]}
        )
        usage_id = self.store.reserve_usage(client["id"], "OpenAI", ["tavily"])
        self.store.finalize_usage(
            usage_id,
            status_code=200,
            success=True,
            duration_ms=123,
            result_count=3,
        )
        self.assertEqual(self.store.quota_counts(client["id"]), (1, 1))

        rotated = self.store.rotate_client_key(client["id"])
        self.assertIsNone(self.store.authenticate_client(client["key"]))
        self.assertIsNotNone(self.store.authenticate_client(rotated["key"]))

    def test_provider_and_proxy_secrets_are_encrypted(self):
        provider = self.store.update_provider("tavily", "provider-secret", True)
        self.assertEqual(provider["secret"], "provider-secret")
        self.assertEqual(
            self.store.get_provider_secret("TAVILY_API_KEY"),
            (True, True, "provider-secret"),
        )

        proxy = self.store.save_proxy(
            {
                "name": "proxy-one",
                "scheme": "http",
                "host": "127.0.0.1",
                "port": 8080,
                "username": "user",
                "password": "pass",
                "channels": [],
            }
        )
        self.assertEqual(proxy["username"], "user")
        self.assertEqual(proxy["password"], "pass")
        self.assertIn(
            "user:pass@127.0.0.1:8080", self.store.proxy_urls_for_engine("bing")[0]
        )

    def test_proxy_url_parsing_and_bulk_insert(self):
        parsed = parse_proxy_url("http://user%40mail:pass%3Aword@209.50.160.174:3129")
        self.assertEqual(parsed["host"], "209.50.160.174")
        self.assertEqual(parsed["port"], 3129)
        self.assertEqual(parsed["username"], "user@mail")
        self.assertEqual(parsed["password"], "pass:word")
        self.assertEqual(
            proxy_identity(parsed),
            ("http", "209.50.160.174", 3129, "user@mail", "pass:word"),
        )

        created = self.store.create_proxies(
            [parsed, parse_proxy_url("socks5://127.0.0.1:1080")]
        )
        self.assertEqual(len(created), 2)
        self.assertTrue(all(item["status"] == "untested" for item in created))
        self.assertEqual(len(self.store.list_proxies()), 2)
        self.store.set_proxies_enabled([created[0]["id"]], False)
        by_id = {item["id"]: item for item in self.store.list_proxies()}
        self.assertFalse(by_id[created[0]["id"]]["enabled"])
        self.assertTrue(by_id[created[1]["id"]]["enabled"])

        with self.assertRaisesRegex(ValueError, "不支持的代理协议"):
            parse_proxy_url("ftp://127.0.0.1:21")
        with self.assertRaisesRegex(ValueError, "代理端口无效"):
            parse_proxy_url("http://127.0.0.1")

    def test_proxy_tests_run_concurrently(self):
        proxies = [
            {"id": "one", "name": "one"},
            {"id": "two", "name": "two"},
        ]
        result = {
            "status": "healthy",
            "exit_ip": "203.0.113.1",
            "latency_ms": 12,
            "error": "",
        }
        with patch(
            "searchone_control.networking.test_proxy", return_value=result
        ) as mocked:
            tested = test_proxies_concurrently(proxies, max_workers=2)
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual({item["id"] for item in tested}, {"one", "two"})
        self.assertTrue(all(item["status"] == "healthy" for item in tested))

    def test_admin_password_is_verified(self):
        self.assertTrue(self.store.verify_admin("admin", "secret-password"))
        self.assertFalse(self.store.verify_admin("admin", "wrong"))

    def test_runtime_secrets_use_first_start_environment_once(self):
        path = Path(self.tempdir.name) / "runtime-secrets.env"
        first_key = Fernet.generate_key().decode("ascii")
        with patch.dict(
            "os.environ",
            {
                "SEARCHONE_MASTER_KEY": first_key,
                "SEARCHONE_SESSION_SECRET": "first-session",
                "SEARCHONE_ADMIN_USERNAME": "operator",
                "SEARCHONE_ADMIN_PASSWORD": "first-password",
            },
        ):
            created, values = ensure_runtime_secrets(path)
        self.assertTrue(created)
        self.assertEqual(values["SEARCHONE_MASTER_KEY"], first_key)
        self.assertEqual(values["SEARCHONE_ADMIN_USERNAME"], "operator")

        with patch.dict(
            "os.environ",
            {
                "SEARCHONE_ADMIN_PASSWORD": "replacement-password",
            },
        ):
            created, persisted = ensure_runtime_secrets(path)
        self.assertFalse(created)
        self.assertEqual(persisted["SEARCHONE_ADMIN_PASSWORD"], "first-password")


if __name__ == "__main__":
    unittest.main()
