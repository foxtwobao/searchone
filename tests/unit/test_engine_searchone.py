# SPDX-License-Identifier: AGPL-3.0-or-later
# pylint: disable=missing-class-docstring,missing-module-docstring

from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from searx.engines import exa, metaso, tavily, zhihu
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
        with patch.object(tavily, "api_key", ""), patch.dict(
            "os.environ", {"TAVILY_API_KEY": ""}
        ):
            with self.assertRaises(SearxEngineAPIException):
                tavily.request("query", params())


class ExaEngineTests(SearxTestCase):

    def test_request_and_response(self):
        request_params = params()
        with patch.object(exa, "api_key", "exa-key"):
            exa.request("semantic search", request_params)

        self.assertEqual(request_params["method"], "POST")
        self.assertEqual(request_params["headers"]["x-api-key"], "exa-key")
        self.assertEqual(
            request_params["json"]["contents"]["text"]["maxCharacters"], 500
        )

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


class MetasoEngineTests(SearxTestCase):

    def test_request_and_response(self):
        request_params = params()
        with patch.object(metaso, "api_key", "metaso-key"):
            metaso.request("中文搜索", request_params)

        self.assertEqual(request_params["json"]["scope"], "webpage")
        self.assertEqual(request_params["json"]["size"], "10")
        self.assertEqual(
            request_params["headers"]["Authorization"], "Bearer metaso-key"
        )

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
        self.assertEqual(
            request_params["headers"]["Authorization"], "Bearer tikhub-key"
        )

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
        self.assertEqual(
            results[0].url, "https://www.zhihu.com/question/123/answer/456"
        )
        self.assertEqual(results[0].author, "答主")
        self.assertIn("votes: 12", results[0].metadata)
