# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search the web with Zhipu Coding Plan WebSearch Prime MCP."""

from __future__ import annotations

import typing as t

from searchone_control.providers import _client
from searchone_control.zhipu_mcp import ZhipuMcpHttpError, search as search_mcp

from searx.engines._searchone_api import resolve_api_key
from searx.exceptions import (
    SearxEngineAPIException,
    SearxEngineAccessDeniedException,
    SearxEngineTooManyRequestsException,
)
from searx.result_types import EngineResults

if t.TYPE_CHECKING:
    from searx.search.processors import RequestParams


about = {
    "website": "https://bigmodel.cn/",
    "wikidata_id": None,
    "official_api_documentation": "https://docs.bigmodel.cn/cn/coding-plan/tool/mcp/web-search",
    "use_official_api": True,
    "require_api_key": True,
    "results": "JSON",
}

engine_type = "offline"
categories = ["general"]
paging = False
send_accept_language_header = False

api_key = ""


def search(query: str, params: "RequestParams") -> EngineResults:
    """Run one stateful MCP tool call and map valid rows to main results."""

    del params
    key = resolve_api_key(
        api_key,
        "ZHIPU_CODING_PLAN_API_KEY",
        "智谱 WebSearch Prime",
    )
    try:
        with _client("zhipu", timeout=30.0) as client:
            rows = search_mcp(client, key, query)
    except ZhipuMcpHttpError as exc:
        message = f"智谱 WebSearch Prime: HTTP {exc.status_code}"
        if exc.status_code == 429:
            raise SearxEngineTooManyRequestsException(message=message) from exc
        if exc.status_code in (401, 402, 403):
            raise SearxEngineAccessDeniedException(message=message) from exc
        raise SearxEngineAPIException(message) from exc

    results = EngineResults()
    for item in rows:
        if not isinstance(item, dict):
            continue
        url = item.get("link")
        title = item.get("title")
        if not isinstance(url, str) or not url.strip():
            continue
        if not isinstance(title, str) or not title.strip():
            continue
        content = item.get("content")
        results.add(
            results.types.MainResult(
                url=url.strip(),
                title=title.strip(),
                content=content if isinstance(content, str) else "",
            )
        )
    return results
