# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search the web with the Tavily Search API."""

from __future__ import annotations

import typing as t

from searx.engines._searchone_api import (
    parse_datetime,
    raise_for_api_error,
    resolve_api_key,
)
from searx.result_types import EngineResults

if t.TYPE_CHECKING:
    from searx.extended_types import SXNG_Response
    from searx.search.processors import OnlineParams


about = {
    "website": "https://tavily.com/",
    "wikidata_id": None,
    "official_api_documentation": "https://docs.tavily.com/documentation/api-reference/endpoint/search",
    "use_official_api": True,
    "require_api_key": True,
    "results": "JSON",
}

categories = ["general"]
paging = False
time_range_support = True
send_accept_language_header = False

api_key = ""
base_url = "https://api.tavily.com/search"
results_per_page = 10
search_depth = "basic"
topic = "general"
include_answer = True


def request(query: str, params: "OnlineParams") -> None:
    key = resolve_api_key(api_key, "TAVILY_API_KEY", "Tavily")
    payload: dict[str, t.Any] = {
        "query": query,
        "search_depth": search_depth,
        "topic": topic,
        "max_results": results_per_page,
        "include_answer": include_answer,
        "include_raw_content": False,
        "include_images": False,
    }
    if params["time_range"]:
        payload["time_range"] = params["time_range"]

    params["url"] = base_url
    params["method"] = "POST"
    params["json"] = payload
    params["headers"].update(
        {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Client-Source": "searchone-searxng",
        }
    )
    params["raise_for_httperror"] = False


def response(resp: "SXNG_Response") -> EngineResults:
    raise_for_api_error(resp, "Tavily")
    data = resp.json()
    results = EngineResults()

    answer = data.get("answer")
    if isinstance(answer, str) and answer.strip():
        results.add(results.types.Answer(answer=answer.strip()))

    for item in data.get("results", []):
        url = item.get("url")
        title = item.get("title")
        if not url or not title:
            continue

        score = item.get("score")
        metadata = (
            f"Tavily score: {score:.3f}" if isinstance(score, (int, float)) else ""
        )
        results.add(
            results.types.MainResult(
                url=url,
                title=title,
                content=item.get("content") or "",
                publishedDate=parse_datetime(item.get("published_date")),
                thumbnail=item.get("favicon") or "",
                metadata=metadata,
            )
        )
    return results
