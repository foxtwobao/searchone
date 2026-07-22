"""Runtime proxy management for all SearXNG outbound networks."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import httpx
from httpx_socks import SyncProxyTransport

from .runtime import get_store


_APPLY_LOCK = threading.RLock()
SUPPORTED_PROXY_SCHEMES = {"http", "https", "socks4", "socks5", "socks5h"}


def parse_proxy_url(value: str) -> dict[str, Any]:
    """Parse one standard proxy URL into a storage payload."""

    raw = value.strip()
    if not raw:
        raise ValueError("代理地址不能为空")
    parsed = urlsplit(raw)
    scheme = parsed.scheme.lower()
    if scheme not in SUPPORTED_PROXY_SCHEMES:
        raise ValueError("不支持的代理协议")
    if not parsed.hostname:
        raise ValueError("代理主机不能为空")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("代理端口无效") from exc
    if port is None or port < 1 or port > 65535:
        raise ValueError("代理端口无效")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("代理地址不能包含路径、查询参数或片段")
    host = parsed.hostname
    display_host = f"[{host}]" if ":" in host else host
    return {
        "name": f"{display_host}:{port}",
        "scheme": scheme,
        "host": host,
        "port": port,
        "username": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "enabled": True,
        "weight": 1,
        "channels": [],
    }


def proxy_identity(proxy: dict[str, Any]) -> tuple[str, str, int, str, str]:
    return (
        str(proxy["scheme"]).lower(),
        str(proxy["host"]).lower(),
        int(proxy["port"]),
        str(proxy.get("username", "")),
        str(proxy.get("password", "")),
    )


def proxy_url(proxy: dict[str, Any]) -> str:
    auth = ""
    if proxy.get("username"):
        auth = quote(str(proxy["username"]), safe="")
        if proxy.get("password"):
            auth += ":" + quote(str(proxy["password"]), safe="")
        auth += "@"
    host = str(proxy["host"])
    display_host = f"[{host}]" if ":" in host else host
    return f"{proxy['scheme']}://{auth}{display_host}:{proxy['port']}"


def apply_proxy_pool() -> (
    dict[str, int]
):  # pylint: disable=import-outside-toplevel,protected-access
    """Apply the current pool atomically to every initialized network."""

    from searx.network.network import NETWORKS

    store = get_store()
    enabled = [
        item
        for item in store.list_proxies()
        if item["enabled"] and item["status"] != "failed"
    ]
    with _APPLY_LOCK:
        grouped: dict[int, tuple[Any, set[str]]] = {}
        for network_name, network in NETWORKS.items():
            key = id(network)
            grouped.setdefault(key, (network, set()))[1].add(network_name)

        configured = 0
        direct = 0
        for network, names in grouped.values():
            urls: list[str] = []
            for item in enabled:
                channels = set(item.get("channels") or [])
                if channels and not channels.intersection(names):
                    continue
                urls.extend([proxy_url(item)] * max(1, int(item.get("weight", 1))))
            network.proxies = {"all://": urls} if urls else None
            network._proxies_cycle = network.get_proxy_cycles()
            if urls:
                configured += 1
            else:
                direct += 1
    return {"proxied_networks": configured, "direct_networks": direct}


def test_proxy(proxy: dict[str, Any]) -> dict[str, Any]:
    url = proxy_url(proxy)
    started = time.monotonic()
    try:
        if proxy["scheme"].startswith("socks"):
            transport = SyncProxyTransport.from_url(url)
            client = httpx.Client(
                transport=transport, timeout=12, follow_redirects=True
            )
        else:
            client = httpx.Client(proxy=url, timeout=12, follow_redirects=True)
        with client:
            response = client.get("https://api.ipify.org?format=json")
            response.raise_for_status()
            exit_ip = str(response.json().get("ip", ""))
        return {
            "status": "healthy",
            "exit_ip": exit_ip,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": "",
        }
    except Exception as exc:  # pylint: disable=broad-except
        return {
            "status": "failed",
            "exit_ip": "",
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": str(exc),
        }


def test_proxies_concurrently(
    proxies: list[dict[str, Any]], max_workers: int = 20
) -> list[dict[str, Any]]:
    if not proxies:
        return []
    workers = max(1, min(int(max_workers), 50, len(proxies)))

    def run(proxy: dict[str, Any]) -> dict[str, Any]:
        result = test_proxy(proxy)
        return {"id": proxy["id"], "name": proxy["name"], **result}

    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="proxy-test"
    ) as pool:
        return list(pool.map(run, proxies))
