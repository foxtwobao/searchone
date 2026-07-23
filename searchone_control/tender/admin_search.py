# SPDX-License-Identifier: AGPL-3.0-or-later
"""Concurrent tender search used by the SearchOne administration console."""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from html import unescape
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import quote, urlencode, urljoin

import httpx
from httpx_socks import SyncProxyTransport

from searchone_control.networking import proxy_identity, proxy_url


_SPACE = re.compile(r"\s+")
_CHANNEL = "tender"
_PROXY_ROTATION_LOCK = threading.Lock()
_LAST_PROXY_BY_SOURCE: dict[str, tuple[str, str, int, str, str]] = {}
_PROXY_CURSOR = 0
_BLOCK_TAGS = {
    "article",
    "br",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "p",
    "section",
    "table",
    "td",
    "th",
    "tr",
}


@dataclass(frozen=True)
class AdminTenderSource:
    """One province-level search endpoint and its parser family."""

    source_id: str
    province: str
    name: str
    website: str
    adapter: str
    search_url: str


SOURCES = (
    AdminTenderSource(
        "shanghai",
        "上海",
        "上海市政府采购网",
        "http://www.ccgp-shanghai.gov.cn/",
        "zcy",
        "http://www.ccgp-shanghai.gov.cn/portal/all",
    ),
    AdminTenderSource(
        "anhui",
        "安徽",
        "安徽省政府采购网",
        "https://www.ccgp-anhui.gov.cn/",
        "zcy",
        "https://www.ccgp-anhui.gov.cn/portal/all",
    ),
    AdminTenderSource(
        "guangxi",
        "广西",
        "广西政府采购网",
        "http://www.ccgp-guangxi.gov.cn/",
        "zcy",
        "http://www.ccgp-guangxi.gov.cn/portal/all",
    ),
    AdminTenderSource(
        "hunan",
        "湖南",
        "湖南政府采购网",
        "http://www.ccgp-hunan.gov.cn/",
        "zcy",
        "http://www.ccgp-hunan.gov.cn/portal/all",
    ),
    AdminTenderSource(
        "guizhou",
        "贵州",
        "贵州省政府采购网",
        "http://www.ccgp-guizhou.gov.cn/",
        "zcy",
        "http://www.ccgp-guizhou.gov.cn/portal/all",
    ),
    AdminTenderSource(
        "shanxi",
        "山西",
        "山西政府采购网",
        "http://www.ccgp-shanxi.gov.cn/",
        "zcy",
        "http://www.ccgp-shanxi.gov.cn/portal/all",
    ),
    AdminTenderSource(
        "jiangsu",
        "江苏",
        "江苏省公共资源交易网",
        "http://jsggzy.jszwfw.gov.cn/",
        "epoint_jiangsu",
        (
            "http://jsggzy.jszwfw.gov.cn/inteligentsearch/rest/"
            "esinteligentsearch/getFullTextDataNew"
        ),
    ),
    AdminTenderSource(
        "shandong",
        "山东",
        "山东省政府采购信息公开平台",
        "http://www.ccgp-shandong.gov.cn/",
        "shandong",
        "http://www.ccgp-shandong.gov.cn:8087/api/website/site/searchAllByCode",
    ),
    AdminTenderSource(
        "qinghai",
        "青海",
        "青海省公共资源交易网",
        "http://www.qhggzyjy.gov.cn/ggzy/",
        "epoint_qinghai",
        (
            "http://www.qhggzyjy.gov.cn/inteligentsearch/rest/"
            "inteligentSearch/getFullTextData"
        ),
    ),
    AdminTenderSource(
        "ningxia",
        "宁夏",
        "宁夏公共资源交易网",
        "https://ggzyjy.fzggw.nx.gov.cn/",
        "epoint_ningxia",
        (
            "https://ggzyjy.fzggw.nx.gov.cn/interface_wz/rest/"
            "esinteligentsearch/getFullTextDataNew"
        ),
    ),
)

_SOURCE_BY_ID = {source.source_id: source for source in SOURCES}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append(" ")


def plain_text(value: Any, limit: int | None = None) -> str:
    """Convert an upstream HTML fragment into compact plain text."""

    parser = _TextExtractor()
    try:
        parser.feed(unescape(str(value or "")))
        text = _SPACE.sub(" ", "".join(parser.parts)).strip()
    except (ValueError, TypeError):
        text = _SPACE.sub(" ", str(value or "")).strip()
    if limit is not None and len(text) > limit:
        return text[: max(0, limit - 1)].rstrip() + "…"
    return text


def source_catalog() -> list[dict[str, str]]:
    """Return public metadata for the configured province sources."""

    return [
        {
            key: value
            for key, value in asdict(source).items()
            if key not in {"adapter", "search_url"}
        }
        for source in SOURCES
    ]


def eligible_proxies(proxies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return enabled, tender-capable proxies with duplicate endpoints removed."""

    result = []
    seen: set[tuple[str, str, int, str, str]] = set()
    for item in proxies:
        channels = item.get("channels") or []
        if not item.get("enabled") or (channels and _CHANNEL not in channels):
            continue
        identity = proxy_identity(item)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(item)
    return result


def search_tenders(
    keyword: str,
    source_ids: list[str],
    proxies: list[dict[str, Any]],
    *,
    days: int = 90,
    per_source: int = 10,
) -> dict[str, Any]:
    """Search selected province sources concurrently using distinct proxies."""

    normalized = _SPACE.sub(" ", str(keyword)).strip()
    if not normalized:
        raise ValueError("请输入搜索关键词")
    if len(normalized) > 100:
        raise ValueError("搜索关键词不能超过 100 个字符")
    if not source_ids:
        raise ValueError("请至少选择一个省份网站")
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("省份网站不能重复")
    try:
        selected = [_SOURCE_BY_ID[source_id] for source_id in source_ids]
    except KeyError as exc:
        raise ValueError("包含不支持的省份网站") from exc

    days = max(1, min(int(days), 3650))
    per_source = max(1, min(int(per_source), 20))
    available = eligible_proxies(proxies)
    if not available:
        assigned: list[dict[str, Any] | None] = [None] * len(selected)
    else:
        assigned = _rotate_proxies(selected, available)
    started = time.monotonic()
    outcomes: list[dict[str, Any]] = []
    with ThreadPoolExecutor(
        max_workers=len(selected), thread_name_prefix="tender-search"
    ) as executor:
        futures = {
            executor.submit(
                _search_source,
                source,
                proxy,
                normalized,
                days,
                per_source,
            ): source.source_id
            for source, proxy in zip(selected, assigned, strict=True)
        }
        for future in as_completed(futures):
            outcomes.append(future.result())

    order = {source_id: index for index, source_id in enumerate(source_ids)}
    outcomes.sort(key=lambda item: order[item["source"]["source_id"]])
    results = [result for outcome in outcomes for result in outcome["results"]]
    results.sort(key=lambda item: item.get("published_at") or "", reverse=True)
    return {
        "keyword": normalized,
        "days": days,
        "per_source": per_source,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "searched": len(outcomes),
        "succeeded": sum(item["status"] == "ok" for item in outcomes),
        "failed": sum(item["status"] == "failed" for item in outcomes),
        "result_count": len(results),
        "sources": outcomes,
        "results": results,
    }


def _rotate_proxies(
    sources: list[AdminTenderSource], proxies: list[dict[str, Any]]
) -> list[dict[str, Any] | None]:
    """Assign unique rotating proxies and use direct access for any shortfall."""

    global _PROXY_CURSOR  # pylint: disable=global-statement
    with _PROXY_ROTATION_LOCK:
        ordered = sorted(proxies, key=lambda item: str(item.get("id", "")))
        offset = _PROXY_CURSOR % len(ordered)
        ordered = ordered[offset:] + ordered[:offset]
        source_offset = _PROXY_CURSOR % len(sources)
        rotating_sources = sources[source_offset:] + sources[:source_offset]
        used: set[tuple[str, str, int, str, str]] = set()
        by_source: dict[str, dict[str, Any]] = {}
        for source in rotating_sources[: len(ordered)]:
            previous = _LAST_PROXY_BY_SOURCE.get(source.source_id)
            candidate = next(
                (
                    proxy
                    for proxy in ordered
                    if proxy_identity(proxy) not in used
                    and proxy_identity(proxy) != previous
                ),
                None,
            )
            if candidate is None:
                candidate = next(
                    (proxy for proxy in ordered if proxy_identity(proxy) not in used),
                    None,
                )
            if candidate is None:
                break
            identity = proxy_identity(candidate)
            used.add(identity)
            by_source[source.source_id] = candidate
            _LAST_PROXY_BY_SOURCE[source.source_id] = identity
        _PROXY_CURSOR = (_PROXY_CURSOR + 1) % max(len(ordered), len(sources))
    return [by_source.get(source.source_id) for source in sources]


def _client(proxy: dict[str, Any] | None) -> httpx.Client:
    options: dict[str, Any] = {
        "timeout": httpx.Timeout(20.0, connect=12.0),
        "follow_redirects": True,
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "Chrome/124.0 Safari/537.36 SearchOne/1.0"
            ),
            "X-Requested-With": "XMLHttpRequest",
        },
    }
    if proxy is None:
        return httpx.Client(**options)
    url = proxy_url(proxy)
    if str(proxy.get("scheme", "")).startswith("socks"):
        options["transport"] = SyncProxyTransport.from_url(url)
    else:
        options["proxy"] = url
    return httpx.Client(**options)


def _search_source(
    source: AdminTenderSource,
    proxy: dict[str, Any] | None,
    keyword: str,
    days: int,
    per_source: int,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        with _client(proxy) as client:
            results, total = _ADAPTERS[source.adapter](
                client, source, keyword, days, per_source
            )
        status = "ok"
        error = ""
    except (httpx.HTTPError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        results = []
        total = 0
        status = "failed"
        error = _safe_error(exc)
    return {
        "source": {
            "source_id": source.source_id,
            "province": source.province,
            "name": source.name,
            "website": source.website,
        },
        "proxy": (
            {
                "id": str(proxy.get("id", "")),
                "name": str(proxy.get("name", "未命名代理")),
                "exit_ip": str(proxy.get("exit_ip", "")),
            }
            if proxy is not None
            else {"id": "", "name": "本机直连", "exit_ip": ""}
        ),
        "status": status,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "total": total,
        "result_count": len(results),
        "results": results,
        "error": error,
    }


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"站点返回 HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "站点请求超时"
    if isinstance(exc, httpx.ProxyError):
        return "代理连接失败"
    if isinstance(exc, (ValueError, KeyError, TypeError, json.JSONDecodeError)):
        return plain_text(str(exc), 160) or "站点响应格式异常"
    return "站点请求失败"


def _date_bounds(days: int) -> tuple[datetime, datetime]:
    end = datetime.now(UTC)
    return end - timedelta(days=days), end


def _result(
    source: AdminTenderSource,
    *,
    title: Any,
    url: str,
    summary: Any = "",
    published_at: Any = "",
    buyer: Any = "",
    category: Any = "",
    project_code: Any = "",
) -> dict[str, str]:
    return {
        "source_id": source.source_id,
        "source_name": source.name,
        "province": source.province,
        "title": plain_text(title, 240),
        "url": url,
        "summary": plain_text(summary, 420),
        "published_at": _iso_date(published_at),
        "buyer": plain_text(buyer, 120),
        "category": plain_text(category, 100),
        "project_code": plain_text(project_code, 100),
    }


def _iso_date(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, UTC).isoformat()
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.isoformat()


def _zcy(
    client: httpx.Client,
    source: AdminTenderSource,
    keyword: str,
    days: int,
    per_source: int,
) -> tuple[list[dict[str, str]], int]:
    start, end = _date_bounds(days)
    response = client.post(
        source.search_url,
        json={
            "keyword": keyword,
            "firstCode": "",
            "secondCode": "",
            "districtCode": [],
            "publishDateBegin": round(start.timestamp() * 1000),
            "publishDateEnd": round(end.timestamp() * 1000),
            "pageNo": 1,
            "pageSize": per_source,
            "isTitleSearch": None,
            "order": "desc",
            "leaf": "0",
        },
    )
    response.raise_for_status()
    payload = response.json()
    data = payload["result"]["data"]
    rows = data.get("data") or []
    results = []
    for item in rows:
        query = urlencode(
            {
                "categoryCode": item.get("firstCode") or "ZcyAnnouncement",
                "parentId": item.get("parentId") or "",
                "articleId": item.get("articleId") or "",
            }
        )
        results.append(
            _result(
                source,
                title=item.get("title"),
                url=urljoin(source.website, "site/detail?" + query),
                summary=item.get("content"),
                published_at=item.get("publishDate"),
                buyer=item.get("purchaseName") or item.get("author"),
                category=item.get("pathName") or item.get("procurementMethod"),
                project_code=item.get("projectCode"),
            )
        )
    return results, int(data.get("total") or len(results))


def _shandong(
    client: httpx.Client,
    source: AdminTenderSource,
    keyword: str,
    days: int,
    per_source: int,
) -> tuple[list[dict[str, str]], int]:
    start, _end = _date_bounds(days)
    response = client.post(
        source.search_url,
        json={
            "type": "01",
            "colCode": "",
            "area": "",
            "cityType": "",
            "title": keyword,
            "projectCode": "",
            "currentPage": 1,
            "pageSize": 50,
            "buyKind": "",
            "buyType": "",
            "unitName": "",
            "startTime": "",
            "endTime": "",
            "oldData": 0,
            "homePage": 0,
            "mergeType": 0,
            "captchaCode": "",
            "captchaUuid": "",
        },
    )
    response.raise_for_status()
    outer = response.json()
    data = outer["data"]["data"]
    results = []
    for item in data.get("records") or []:
        published_at = _iso_date(item.get("date"))
        try:
            published_date = datetime.fromisoformat(published_at)
        except ValueError:
            published_date = None
        if published_date is not None and published_date < start:
            continue
        detail_query = urlencode(
            {
                "id": item.get("id") or "",
                "colCode": item.get("colCode") or "",
                "urlType": "site",
                "oldData": item.get("oldData") or 0,
            }
        )
        results.append(
            _result(
                source,
                title=item.get("title"),
                url=urljoin(source.website, "detail?" + detail_query),
                published_at=published_at,
                buyer=item.get("userName"),
                category=item.get("buyKindCode") or item.get("projectType"),
            )
        )
        if len(results) >= per_source:
            break
    return results, int(data.get("total") or len(results))


def _epoint_payload(
    keyword: str,
    days: int,
    per_source: int,
    *,
    cnum: str,
    sort: str,
    content_length: int,
    no_participle: str,
) -> dict[str, Any]:
    start, end = _date_bounds(days)
    return {
        "token": "",
        "pn": 0,
        "rn": per_source,
        "sdt": start.strftime("%Y-%m-%d %H:%M:%S"),
        "edt": end.strftime("%Y-%m-%d %H:%M:%S"),
        "wd": quote(keyword, safe=""),
        "inc_wd": "",
        "exc_wd": "",
        "fields": "title;content",
        "cnum": cnum,
        "sort": sort,
        "ssort": "title",
        "cl": content_length,
        "terminal": "",
        "condition": None,
        "time": None,
        "highlights": "title;content",
        "statistics": None,
        "unionCondition": None,
        "accuracy": "",
        "noParticiple": no_participle,
        "searchRange": None,
    }


def _epoint(
    client: httpx.Client,
    source: AdminTenderSource,
    payload: dict[str, Any],
    per_source: int,
) -> tuple[list[dict[str, str]], int]:
    response = client.post(source.search_url, json=payload)
    response.raise_for_status()
    data = response.json().get("result") or {}
    if isinstance(data, str):
        data = json.loads(data)
    results = [
        _result(
            source,
            title=item.get("title"),
            url=urljoin(source.website, item.get("linkurl") or ""),
            summary=item.get("content"),
            published_at=(
                item.get("showdate")
                or item.get("infodatepx")
                or item.get("infodate")
            ),
            buyer=(
                item.get("xiaquname")
                or item.get("author")
                or item.get("zhuanzai")
            ),
            category=item.get("gonggaotype") or item.get("categoryname"),
            project_code=item.get("id"),
        )
        for item in (data.get("records") or [])[:per_source]
    ]
    return results, int(data.get("totalcount") or len(results))


def _epoint_qinghai(
    client: httpx.Client,
    source: AdminTenderSource,
    keyword: str,
    days: int,
    per_source: int,
) -> tuple[list[dict[str, str]], int]:
    return _epoint(
        client,
        source,
        _epoint_payload(
            keyword,
            days,
            per_source,
            cnum="001;002;003;004;005;006;007;008;009;010",
            sort='{"showdate":"0"}',
            content_length=500,
            no_participle="",
        ),
        per_source,
    )


def _epoint_jiangsu(
    client: httpx.Client,
    source: AdminTenderSource,
    keyword: str,
    days: int,
    per_source: int,
) -> tuple[list[dict[str, str]], int]:
    payload = _epoint_payload(
        keyword,
        days,
        per_source,
        cnum="001",
        sort='{"infodatepx":"0"}',
        content_length=500,
        no_participle="1",
    )
    payload["wd"] = keyword
    payload["isBusiness"] = "1"
    return _epoint(client, source, payload, per_source)


def _epoint_ningxia(
    client: httpx.Client,
    source: AdminTenderSource,
    keyword: str,
    days: int,
    per_source: int,
) -> tuple[list[dict[str, str]], int]:
    return _epoint(
        client,
        source,
        _epoint_payload(
            keyword,
            days,
            per_source,
            cnum="",
            sort='{"infodate":"0"}',
            content_length=500,
            no_participle="1",
        ),
        per_source,
    )


Adapter = Callable[
    [httpx.Client, AdminTenderSource, str, int, int],
    tuple[list[dict[str, str]], int],
]

_ADAPTERS: dict[str, Adapter] = {
    "zcy": _zcy,
    "shandong": _shandong,
    "epoint_jiangsu": _epoint_jiangsu,
    "epoint_qinghai": _epoint_qinghai,
    "epoint_ningxia": _epoint_ningxia,
}
