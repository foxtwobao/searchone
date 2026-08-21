# SPDX-License-Identifier: AGPL-3.0-or-later
# pylint: disable=invalid-name,missing-class-docstring,missing-module-docstring

from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from searchone_control.tender import (
    build_tender_query,
    catalog_sources,
    source_for_url,
    tender_domains,
)

from searx.engines import exa, metaso, minimax, tavily, tender, zhipu_web_search, zhihu
from searx.exceptions import (
    SearxEngineAPIException,
    SearxEngineTooManyRequestsException,
)
from tests import SearxTestCase


def params(**overrides):
    value = {
        "headers": {},
        "pageno": 1,
        "time_range": None,
        "safesearch": 0,
        "method": "GET",
        "json": {},
    }
    value.update(overrides)
    return value


def response(payload, status_code=200):
    result = Mock()
    result.status_code = status_code
    result.json.return_value = payload
    return result


class TavilyEngineTests(SearxTestCase):

    def test_request_and_response(self):
        request_params = params(time_range="week")
        with patch.object(tavily, "api_key", "test-key"):
            tavily.request("agent search", request_params)

        self.assertEqual(request_params["url"], "https://api.tavily.com/search")
        self.assertEqual(request_params["method"], "POST")
        self.assertEqual(request_params["json"]["time_range"], "week")
        self.assertEqual(request_params["headers"]["Authorization"], "Bearer test-key")

        results = tavily.response(
            response(
                {
                    "answer": "A concise answer",
                    "results": [
                        {
                            "title": "Result",
                            "url": "https://example.com/result",
                            "content": "Summary",
                            "score": 0.91,
                            "published_date": "2026-07-20T10:00:00Z",
                        }
                    ],
                }
            )
        )
        self.assertEqual(results[0].answer, "A concise answer")
        self.assertEqual(results[1].title, "Result")
        self.assertEqual(results[1].metadata, "Tavily score: 0.910")

    def test_missing_api_key(self):
        with patch.object(tavily, "api_key", ""), patch.dict("os.environ", {"TAVILY_API_KEY": ""}):
            with self.assertRaises(SearxEngineAPIException):
                tavily.request("query", params())


class TenderEngineTests(SearxTestCase):

    def test_catalog_and_query_expansion(self):
        self.assertEqual(len(catalog_sources()), 103)
        self.assertEqual(len(tender_domains()), 118)
        self.assertEqual(len(tender_domains()), len(set(tender_domains())))

        query = build_tender_query("榆林 消防器材")
        self.assertIn("榆林 消防器材", query)
        self.assertIn("灭火器", query)
        self.assertIn("询价", query)

        source = source_for_url("https://search.ccgp.gov.cn/bxsearch")
        self.assertIsNotNone(source)
        self.assertEqual(source.name, "中国政府采购网搜索")

    def test_request_uses_tavily_with_domain_allowlist(self):
        request_params = params(time_range="month")
        with patch.object(tender, "api_key", "test-key"):
            tender.request("陕西 五金工具", request_params)

        payload = request_params["json"]
        self.assertEqual(request_params["url"], "https://api.tavily.com/search")
        self.assertEqual(request_params["method"], "POST")
        self.assertEqual(request_params["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(payload["time_range"], "month")
        self.assertFalse(payload["include_answer"])
        self.assertEqual(len(payload["include_domains"]), 118)
        self.assertIn("ccgp.gov.cn", payload["include_domains"])
        self.assertIn("五金", payload["query"])

    def test_request_defaults_to_recent_results(self):
        request_params = params()
        with patch.object(tender, "api_key", "test-key"):
            tender.request("陕西 劳保用品", request_params)

        self.assertEqual(request_params["json"]["time_range"], "month")

    def test_explicit_year_disables_default_time_filter(self):
        request_params = params()
        with patch.object(tender, "api_key", "test-key"):
            tender.request("2024 陕西 劳保用品", request_params)

        self.assertNotIn("time_range", request_params["json"])
        self.assertEqual(request_params["json"]["query"].count("2024"), 1)

    def test_response_filters_unknown_domains_and_labels_source(self):
        results = tender.response(
            response(
                {
                    "results": [
                        {
                            "title": "<em>消防器材</em>采购公告",
                            "url": "https://www.ccgp.gov.cn/cggg/dfgg/gkzb/notice.htm",
                            "content": "采购灭火器",
                            "score": 0.92,
                            "published_date": "2026-07-21T10:00:00+08:00",
                            "favicon": "https://www.ccgp.gov.cn/favicon.ico",
                        },
                        {
                            "title": "Untrusted mirror",
                            "url": "https://example.com/tender/1",
                            "content": "Mirror",
                        },
                    ]
                }
            )
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "消防器材采购公告")
        self.assertIn("中国政府采购网", results[0].metadata)
        self.assertIn("Tavily score: 0.920", results[0].metadata)
        self.assertEqual(results[0].priority, "high")


class ExaEngineTests(SearxTestCase):

    def test_request_and_response(self):
        request_params = params()
        with patch.object(exa, "api_key", "exa-key"):
            exa.request("semantic search", request_params)

        self.assertEqual(request_params["method"], "POST")
        self.assertEqual(request_params["headers"]["x-api-key"], "exa-key")
        self.assertEqual(request_params["json"]["contents"]["text"]["maxCharacters"], 500)

        results = exa.response(
            response(
                {
                    "results": [
                        {
                            "title": "Exa result",
                            "url": "https://example.com/exa",
                            "text": "Semantic content",
                            "author": "Example Author",
                            "publishedDate": "2026-07-19",
                            "score": 0.8,
                        }
                    ]
                }
            )
        )
        self.assertEqual(results[0].content, "Semantic content")
        self.assertEqual(results[0].author, "Example Author")

    def test_rate_limit(self):
        with self.assertRaises(SearxEngineTooManyRequestsException):
            exa.response(response({"error": "quota exceeded"}, status_code=429))


class MiniMaxEngineTests(SearxTestCase):

    def test_request_and_response(self):
        request_params = params()
        with patch.object(minimax, "api_key", "minimax-key"):
            minimax.request("联网搜索", request_params)

        self.assertEqual(
            request_params["url"],
            "https://api.minimaxi.com/v1/coding_plan/search",
        )
        self.assertEqual(request_params["method"], "POST")
        self.assertEqual(request_params["json"], {"q": "联网搜索"})
        self.assertEqual(request_params["headers"]["Authorization"], "Bearer minimax-key")

        results = minimax.response(
            response(
                {
                    "organic": [
                        {
                            "title": "MiniMax 结果",
                            "link": "https://example.com/minimax",
                            "snippet": "搜索摘要",
                            "date": "2026-08-08",
                        },
                        {"title": "缺少链接"},
                        "无效结果",
                        {"title": "链接类型无效", "link": ["https://example.com"]},
                        {"title": ["标题类型无效"], "link": "https://example.com"},
                    ]
                }
            )
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://example.com/minimax")
        self.assertEqual(results[0].title, "MiniMax 结果")
        self.assertEqual(results[0].content, "搜索摘要")
        self.assertEqual(results[0].publishedDate.date().isoformat(), "2026-08-08")

    def test_rate_limit(self):
        with self.assertRaises(SearxEngineTooManyRequestsException):
            minimax.response(response({"error": "rate limited"}, status_code=429))

    def test_invalid_json_and_payload(self):
        invalid_json = response({})
        invalid_json.json.side_effect = ValueError("invalid json")
        with self.assertRaisesRegex(SearxEngineAPIException, "invalid JSON"):
            minimax.response(invalid_json)

        with self.assertRaisesRegex(SearxEngineAPIException, "invalid response"):
            minimax.response(response({"organic": {}}))


class ZhipuEngineTests(SearxTestCase):
    def test_search_uses_managed_key_and_maps_results(self):
        client = Mock()
        context = Mock()
        context.__enter__ = Mock(return_value=client)
        context.__exit__ = Mock(return_value=False)
        rows = [
            {
                "title": " 智谱结果 ",
                "link": " https://example.com/zhipu ",
                "content": "搜索摘要",
            },
            {"title": "缺少链接"},
            "无效结果",
            {"title": ["无效标题"], "link": "https://example.com/invalid"},
        ]

        with (
            patch.object(zhipu_web_search, "api_key", "fake-zhipu-key"),
            patch.object(zhipu_web_search, "_client", return_value=context) as client_factory,
            patch.object(zhipu_web_search, "search_mcp", return_value=rows) as mcp_search,
        ):
            results = zhipu_web_search.search("联网搜索", {})

        self.assertEqual(zhipu_web_search.engine_type, "offline")
        client_factory.assert_called_once_with("zhipu", timeout=30.0)
        mcp_search.assert_called_once_with(client, "fake-zhipu-key", "联网搜索")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "智谱结果")
        self.assertEqual(results[0].url, "https://example.com/zhipu")
        self.assertEqual(results[0].content, "搜索摘要")

    def test_search_requires_managed_key(self):
        with (
            patch.object(zhipu_web_search, "api_key", ""),
            patch.dict("os.environ", {"ZHIPU_CODING_PLAN_API_KEY": ""}),
        ):
            with self.assertRaises(SearxEngineAPIException):
                zhipu_web_search.search("query", {})


class MetasoEngineTests(SearxTestCase):

    def test_request_and_response(self):
        request_params = params()
        with patch.object(metaso, "api_key", "metaso-key"):
            metaso.request("中文搜索", request_params)

        self.assertEqual(request_params["json"]["scope"], "webpage")
        self.assertEqual(request_params["json"]["size"], "10")
        self.assertEqual(request_params["headers"]["Authorization"], "Bearer metaso-key")

        results = metaso.response(
            response(
                {
                    "webpages": [
                        {
                            "title": "秘塔结果",
                            "link": "https://example.cn/metaso",
                            "summary": "AI 摘要",
                            "authors": ["作者甲", "作者乙"],
                            "score": "0.75",
                            "date": "2026-07-18",
                        }
                    ]
                }
            )
        )
        self.assertEqual(results[0].content, "AI 摘要")
        self.assertEqual(results[0].author, "作者甲, 作者乙")


class ZhihuEngineTests(SearxTestCase):

    def test_request_and_response(self):
        request_params = params(pageno=2, time_range="month")
        with patch.object(zhihu, "api_key", "tikhub-key"):
            zhihu.request("人工智能", request_params)

        query = parse_qs(urlparse(request_params["url"]).query)
        self.assertEqual(query["offset"], ["20"])
        self.assertEqual(query["time_interval"], ["a_month"])
        self.assertEqual(request_params["headers"]["Authorization"], "Bearer tikhub-key")

        results = zhihu.response(
            response(
                {
                    "code": 200,
                    "data": {
                        "data": [
                            {
                                "highlight": {
                                    "title": "<em>人工智能</em>是什么",
                                    "description": "回答摘要",
                                },
                                "object": {
                                    "type": "answer",
                                    "id": 456,
                                    "created_time": 1784500000,
                                    "voteup_count": 12,
                                    "comment_count": 3,
                                    "author": {
                                        "name": "答主",
                                        "avatar_url": "https://example.com/avatar.jpg",
                                    },
                                    "question": {"id": 123, "title": "人工智能是什么"},
                                },
                            }
                        ]
                    },
                }
            )
        )
        self.assertEqual(results[0].title, "人工智能是什么")
        self.assertEqual(results[0].url, "https://www.zhihu.com/question/123/answer/456")
        self.assertEqual(results[0].author, "答主")
        self.assertIn("votes: 12", results[0].metadata)
