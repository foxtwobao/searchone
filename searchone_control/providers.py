"""Provider credential validation used by the administration console."""

from __future__ import annotations

import time
from typing import Any

import httpx
from httpx_socks import SyncProxyTransport

from .networking import proxy_url
from .runtime import get_store


def _client(provider: str) -> httpx.Client:
    store = get_store()
    candidates = [
        item
        for item in store.list_proxies()
        if item["enabled"] and (not item["channels"] or provider in item["channels"])
    ]
    if not candidates:
        return httpx.Client(timeout=20, follow_redirects=True)
    selected = candidates[0]
    url = proxy_url(selected)
    if selected["scheme"].startswith("socks"):
        return httpx.Client(
            transport=SyncProxyTransport.from_url(url),
            timeout=20,
            follow_redirects=True,
        )
    return httpx.Client(proxy=url, timeout=20, follow_redirects=True)


def test_provider(provider: str) -> dict[str, Any]:
    store = get_store()
    item = next(
        (row for row in store.list_providers() if row["provider"] == provider), None
    )
    if item is None:
        raise ValueError("未知供应商")
    if not item["enabled"]:
        raise ValueError("供应商已停用")
    key = item["secret"].strip()
    if not key:
        raise ValueError("尚未配置供应商凭证")

    started = time.monotonic()
    try:
        with _client(provider) as client:
            response = _request(client, provider, key)
            response.raise_for_status()
        latency_ms = int((time.monotonic() - started) * 1000)
        message = f"连接正常，HTTP {response.status_code}，{latency_ms} ms"
        store.update_provider_test(provider, "healthy", message)
        return {"status": "healthy", "message": message, "latency_ms": latency_ms}
    except Exception as exc:  # pylint: disable=broad-except
        message = str(exc)[:300]
        store.update_provider_test(provider, "failed", message)
        return {"status": "failed", "message": message}


def _request(client: httpx.Client, provider: str, key: str) -> httpx.Response:
    if provider == "tavily":
        return client.post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {key}"},
            json={"query": "OpenAI", "max_results": 1, "search_depth": "basic"},
        )
    if provider == "exa":
        return client.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": key},
            json={"query": "OpenAI", "numResults": 1},
        )
    if provider == "metaso":
        return client.post(
            "https://metaso.cn/api/v1/search",
            headers={"Authorization": f"Bearer {key}"},
            json={"q": "OpenAI", "size": 1, "scope": "webpage"},
        )
    if provider == "zhihu":
        return client.get(
            "https://api.tikhub.io/api/v1/zhihu/web/fetch_article_search_v3",
            headers={"Authorization": f"Bearer {key}"},
            params={"keyword": "OpenAI", "page": 1},
        )
    raise ValueError("未知供应商")
