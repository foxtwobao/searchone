# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search public Chinese tender and procurement sources through Tavily."""

from __future__ import annotations

import typing as t

from searchone_control.tender import (
    build_tender_query,
    has_explicit_year,
    source_for_url,
    source_metadata,
    tender_domains,
)

from searx import utils
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
    "website": "https://github.com/tommy619399/Bidding-and-Tendering-System",
    "wikidata_id": None,
    "official_api_documentation": ("https://docs.tavily.com/documentation/api-reference/endpoint/search"),
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
results_per_page = 20
search_depth = "advanced"
default_time_range = "month"


def request(query: str, params: "OnlineParams") -> None:
    key = resolve_api_key(api_key, "TAVILY_API_KEY", "Tender / Tavily")
    payload: dict[str, t.Any] = {
        "query": build_tender_query(query),
        "search_depth": search_depth,
        "topic": "general",
        "max_results": results_per_page,
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
        "include_favicon": True,
        "include_domains": list(tender_domains()),
    }
    requested_time_range = params["time_range"]
    if requested_time_range:
        payload["time_range"] = requested_time_range
    elif default_time_range and not has_explicit_year(query):
        payload["time_range"] = default_time_range

    params["url"] = base_url
    params["method"] = "POST"
    params["json"] = payload
    params["headers"].update(
        {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Client-Source": "searchone-tender",
        }
    )
    params["raise_for_httperror"] = False


def response(resp: "SXNG_Response") -> EngineResults:
    raise_for_api_error(resp, "Tender / Tavily")
    data = resp.json()
    results = EngineResults()

    for item in data.get("results", []):
        url = item.get("url")
        title = item.get("title")
        if not isinstance(url, str) or not isinstance(title, str):
            continue
        source = source_for_url(url)
        if source is None:
            continue

        results.add(
            results.types.MainResult(
                url=url,
                title=utils.html_to_text(title),
                content=utils.html_to_text(item.get("content") or ""),
                publishedDate=parse_datetime(item.get("published_date")),
                thumbnail=item.get("favicon") or "",
                metadata=source_metadata(source, item.get("score")),
                priority="high" if source.priority == 1 else "",
            )
        )
    return results
