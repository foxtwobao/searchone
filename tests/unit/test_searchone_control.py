# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the SearchOne control plane."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from cryptography.fernet import Fernet

from searchone_control.bootstrap import ensure_runtime_secrets
from searchone_control.crypto import SecretBox
from searchone_control.db import Database
from searchone_control.networking import (
    parse_proxy_url,
    proxy_identity,
    test_proxies_concurrently,
)
from searchone_control.providers import _request
from searchone_control.store import ControlStore
from searchone_control.tender.admin_search import (
    SOURCES,
    _epoint,
    _shandong,
    _zcy,
    plain_text,
    search_tenders,
    source_catalog,
)


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

    def test_minimax_provider_is_seeded_and_encrypted(self):
        providers = {item["provider"]: item for item in self.store.list_providers()}
        self.assertEqual(providers["minimax"]["env_name"], "MINIMAX_API_KEY")

        self.store.update_provider("minimax", "minimax-secret", True)
        self.assertEqual(
            self.store.get_provider_secret("MINIMAX_API_KEY"),
            (True, True, "minimax-secret"),
        )

    def test_minimax_provider_connection_request(self):
        client = Mock()
        response_mock = Mock()
        client.post.return_value = response_mock

        self.assertIs(_request(client, "minimax", "secret"), response_mock)
        client.post.assert_called_once_with(
            "https://api.minimaxi.com/v1/coding_plan/search",
            headers={"Authorization": "Bearer secret"},
            json={"q": "OpenAI"},
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


class AdminTenderSearchTest(unittest.TestCase):
    @staticmethod
    def _proxy(proxy_id: str, host: str) -> dict:
        return {
            "id": proxy_id,
            "name": f"proxy-{proxy_id}",
            "scheme": "http",
            "host": host,
            "port": 8080,
            "username": "",
            "password": "",
            "enabled": True,
            "channels": [],
            "exit_ip": "203.0.113.10",
        }

    def test_source_catalog_contains_ten_distinct_provinces(self):
        catalog = source_catalog()

        self.assertEqual(len(catalog), 10)
        self.assertEqual(len({item["province"] for item in catalog}), 10)
        self.assertNotIn("search_url", catalog[0])
        self.assertNotIn("adapter", catalog[0])

    def test_plain_text_removes_highlight_markup(self):
        self.assertEqual(
            plain_text("医院<em style='color:red'>医疗</em>&nbsp;设备"),
            "医院医疗 设备",
        )

    def test_search_assigns_one_distinct_proxy_per_source(self):
        proxies = [self._proxy("one", "127.0.0.1"), self._proxy("two", "127.0.0.2")]

        def fake_search(source, proxy, keyword, days, per_source):
            return {
                "source": {
                    "source_id": source.source_id,
                    "province": source.province,
                    "name": source.name,
                    "website": source.website,
                },
                "proxy": {"id": proxy["id"], "name": proxy["name"], "exit_ip": ""},
                "status": "ok",
                "duration_ms": 1,
                "total": 0,
                "result_count": 0,
                "results": [],
                "error": "",
            }

        source_ids = [SOURCES[0].source_id, SOURCES[1].source_id]
        with (
            patch(
                "searchone_control.tender.admin_search._search_source",
                side_effect=fake_search,
            ),
            patch.dict(
                "searchone_control.tender.admin_search._LAST_PROXY_BY_SOURCE",
                {},
                clear=True,
            ),
            patch("searchone_control.tender.admin_search._PROXY_CURSOR", 0),
        ):
            first = search_tenders("医疗设备", source_ids, proxies)
            second = search_tenders("医疗设备", source_ids, proxies)

        self.assertEqual(first["succeeded"], 2)
        self.assertEqual(
            len({item["proxy"]["id"] for item in first["sources"]}), 2
        )
        first_by_source = {
            item["source"]["source_id"]: item["proxy"]["id"]
            for item in first["sources"]
        }
        second_by_source = {
            item["source"]["source_id"]: item["proxy"]["id"]
            for item in second["sources"]
        }
        self.assertTrue(
            all(
                first_by_source[source_id] != second_by_source[source_id]
                for source_id in source_ids
            )
        )

    def test_search_uses_direct_for_sources_without_unique_proxy(self):
        proxies = [self._proxy("one", "127.0.0.1"), self._proxy("two", "127.0.0.1")]

        def fake_search(source, proxy, keyword, days, per_source):
            return {
                "source": {
                    "source_id": source.source_id,
                    "province": source.province,
                    "name": source.name,
                    "website": source.website,
                },
                "proxy": {
                    "id": proxy["id"] if proxy else "",
                    "name": proxy["name"] if proxy else "本机直连",
                    "exit_ip": "",
                },
                "status": "ok",
                "duration_ms": 1,
                "total": 0,
                "result_count": 0,
                "results": [],
                "error": "",
            }

        with (
            patch(
                "searchone_control.tender.admin_search._search_source",
                side_effect=fake_search,
            ),
            patch.dict(
                "searchone_control.tender.admin_search._LAST_PROXY_BY_SOURCE",
                {},
                clear=True,
            ),
            patch("searchone_control.tender.admin_search._PROXY_CURSOR", 0),
        ):
            first = search_tenders(
                "医疗设备", [SOURCES[0].source_id, SOURCES[1].source_id], proxies
            )
            second = search_tenders(
                "医疗设备", [SOURCES[0].source_id, SOURCES[1].source_id], proxies
            )

        self.assertEqual(
            {item["proxy"]["name"] for item in first["sources"]},
            {"proxy-one", "本机直连"},
        )
        first_proxied = next(
            item["source"]["source_id"]
            for item in first["sources"]
            if item["proxy"]["id"]
        )
        second_proxied = next(
            item["source"]["source_id"]
            for item in second["sources"]
            if item["proxy"]["id"]
        )
        self.assertNotEqual(first_proxied, second_proxied)

    def test_search_uses_direct_connection_when_proxy_pool_is_empty(self):
        outcome = {
            "source": {
                "source_id": SOURCES[0].source_id,
                "province": SOURCES[0].province,
                "name": SOURCES[0].name,
                "website": SOURCES[0].website,
            },
            "proxy": {"id": "", "name": "本机直连", "exit_ip": ""},
            "status": "ok",
            "duration_ms": 1,
            "total": 0,
            "result_count": 0,
            "results": [],
            "error": "",
        }
        with patch(
            "searchone_control.tender.admin_search._search_source",
            return_value=outcome,
        ) as mocked:
            result = search_tenders("医疗设备", [SOURCES[0].source_id], [])

        self.assertIsNone(mocked.call_args.args[1])
        self.assertEqual(result["sources"][0]["proxy"]["name"], "本机直连")

    def test_zcy_response_is_normalized(self):
        payload = {
            "result": {
                "data": {
                    "total": 1,
                    "data": [
                        {
                            "articleId": "article+id==",
                            "firstCode": "ZcyAnnouncement",
                            "parentId": 100,
                            "title": "医院<em>设备</em>招标公告",
                            "content": "采购&nbsp;内容",
                            "publishDate": 1784734233000,
                            "purchaseName": "某医院",
                            "pathName": "采购公告",
                            "projectCode": "P-001",
                        }
                    ],
                }
            }
        }
        transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))

        with httpx.Client(transport=transport) as client:
            results, total = _zcy(client, SOURCES[0], "设备", 90, 5)

        self.assertEqual(total, 1)
        self.assertEqual(results[0]["title"], "医院设备招标公告")
        self.assertIn("article%2Bid%3D%3D", results[0]["url"])

    def test_shandong_response_is_normalized(self):
        shandong_payload = {
            "data": {
                "data": {
                    "total": 1,
                    "records": [
                        {
                            "id": "encrypted-id",
                            "title": "山东设备采购公告",
                            "date": "2026-07-22 18:16:07",
                            "colCode": "0301",
                            "oldData": 0,
                            "userName": "代理机构",
                            "buyKindCode": "公开招标",
                        }
                    ],
                }
            }
        }
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(200, json=shandong_payload)
        )
        with httpx.Client(transport=transport) as client:
            shandong, _ = _shandong(client, SOURCES[7], "设备", 90, 5)

        self.assertEqual(shandong[0]["buyer"], "代理机构")
        self.assertIn("/detail?", shandong[0]["url"])

    def test_epoint_response_is_normalized(self):
        payload = {
            "result": {
                "totalcount": 1,
                "records": [
                    {
                        "title": "青海<em>设备</em>采购公告",
                        "content": "公告内容",
                        "linkurl": "/ggzy/notice/1.html",
                        "showdate": "2026-07-22 18:00:07",
                        "xiaquname": "青海省本级",
                        "gonggaotype": "政府采购",
                        "id": "notice-1",
                    }
                ],
            }
        }
        transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))

        with httpx.Client(transport=transport) as client:
            results, total = _epoint(client, SOURCES[8], {}, 5)

        self.assertEqual(total, 1)
        self.assertEqual(results[0]["title"], "青海设备采购公告")
        self.assertEqual(results[0]["category"], "政府采购")


if __name__ == "__main__":
    unittest.main()
