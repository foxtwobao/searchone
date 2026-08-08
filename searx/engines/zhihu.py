# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search Zhihu through the TikHub API."""

from __future__ import annotations

import typing as t
from urllib.parse import urlencode

from searx import utils
from searx.engines._searchone_api import (
    error_message,
    parse_datetime,
    raise_for_api_error,
    resolve_api_key,
)
from searx.exceptions import SearxEngineAPIException
from searx.result_types import EngineResults

if t.TYPE_CHECKING:
    from searx.extended_types import SXNG_Response
    from searx.search.processors import OnlineParams


about = {
    "website": "https://www.zhihu.com/",
    "wikidata_id": "Q15959722",
    "official_api_documentation": "https://api.tikhub.io/",
    "use_official_api": False,
    "require_api_key": True,
    "results": "JSON",
}

categories = ["social media"]
paging = True
time_range_support = True
send_accept_language_header = False

api_key = ""
base_url = "https://api.tikhub.io/api/v1/zhihu/web/fetch_article_search_v3"
results_per_page = 20
vertical = ""
sort = ""

time_range_map = {
    "day": "a_day",
    "week": "a_week",
    "month": "a_month",
    "year": "a_year",
}


def request(query: str, params: "OnlineParams") -> None:
    key = resolve_api_key(api_key, "TIKHUB_TOKEN", "TikHub Zhihu")
    query_args = {
        "keyword": query,
        "offset": (params["pageno"] - 1) * results_per_page,
        "limit": results_per_page,
        "show_all_topics": "0",
        "search_source": "Normal",
        "vertical": vertical,
        "sort": sort,
        "time_interval": time_range_map.get(params["time_range"], ""),
        "vertical_info": "0,0,0,0,0,0,0,0,0,0,0,0",
    }
    params["url"] = f"{base_url}?{urlencode(query_args)}"
    params["headers"].update(
        {
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        }
    )
    params["raise_for_httperror"] = False


def _result_url(obj: dict[str, t.Any]) -> str:
    obj_type = obj.get("type") or ""
    obj_id = obj.get("id") or obj.get("original_id")
    result_url = ""

    if obj_type == "answer":
        question = obj.get("question") or {}
        question_id = question.get("id")
        if question_id and obj_id:
            result_url = f"https://www.zhihu.com/question/{question_id}/answer/{obj_id}"
    elif obj_type == "article" and obj_id:
        result_url = f"https://zhuanlan.zhihu.com/p/{obj_id}"
    elif obj_type == "question" and obj_id:
        result_url = f"https://www.zhihu.com/question/{obj_id}"
    elif obj_type == "zvideo" and obj_id:
        result_url = f"https://www.zhihu.com/zvideo/{obj_id}"
    elif obj_type == "topic" and obj_id:
        result_url = f"https://www.zhihu.com/topic/{obj_id}/hot"
    elif obj_type == "people":
        author = obj.get("author") or obj
        token = author.get("url_token")
        if token:
            result_url = f"https://www.zhihu.com/people/{token}"

    if not result_url:
        url = obj.get("url") or ""
        if isinstance(url, str) and url.startswith("https://www.zhihu.com/"):
            result_url = url
    return result_url


def _title(obj: dict[str, t.Any], highlight: dict[str, t.Any]) -> str:
    value = highlight.get("title") or obj.get("title") or obj.get("name")
    if not value and obj.get("type") == "answer":
        value = (obj.get("question") or {}).get("title")
    return utils.html_to_text(value or "")


def _metadata(obj: dict[str, t.Any]) -> str:
    values = []
    for key, label in (
        ("voteup_count", "votes"),
        ("comment_count", "comments"),
        ("favorites_count", "favorites"),
    ):
        value = obj.get(key)
        if value not in (None, ""):
            values.append(f"{label}: {value}")
    return " | ".join(values)


def response(resp: "SXNG_Response") -> EngineResults:
    raise_for_api_error(resp, "TikHub Zhihu")
    data = resp.json()
    if data.get("code") not in (None, 200):
        raise SearxEngineAPIException(error_message(data, "TikHub Zhihu API error"))

    result_data = data.get("data") or {}
    items = result_data.get("data") or []
    results = EngineResults()

    for item in items:
        if not isinstance(item, dict):
            continue
        obj = item.get("object") or {}
        highlight = item.get("highlight") or {}
        if not isinstance(obj, dict) or not isinstance(highlight, dict):
            continue

        url = _result_url(obj)
        title = _title(obj, highlight)
        if not url or not title:
            continue

        author = obj.get("author") or {}
        content = highlight.get("description") or obj.get("excerpt") or obj.get("description") or ""
        results.add(
            results.types.MainResult(
                url=url,
                title=title,
                content=utils.html_to_text(content),
                author=author.get("name") or "" if isinstance(author, dict) else "",
                publishedDate=parse_datetime(obj.get("created_time")),
                thumbnail=(author.get("avatar_url") or "" if isinstance(author, dict) else ""),
                metadata=_metadata(obj),
            )
        )
    return results
