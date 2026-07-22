# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search the web with the Metaso Search API."""

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
    "website": "https://metaso.cn/",
    "wikidata_id": None,
    "official_api_documentation": "https://metaso.cn/",
    "use_official_api": True,
    "require_api_key": True,
    "results": "JSON",
}

categories = ["general"]
paging = False
send_accept_language_header = False

api_key = ""
base_url = "https://metaso.cn/api/v1/search"
results_per_page = 10
scope = "webpage"
include_summary = True
include_raw_content = False
concise_snippet = True


def request(query: str, params: "OnlineParams") -> None:
    key = resolve_api_key(api_key, "METASO_API_KEY", "Metaso")
    params["url"] = base_url
    params["method"] = "POST"
    params["json"] = {
        "q": query,
        "scope": scope,
        "includeSummary": include_summary,
        "size": str(results_per_page),
        "includeRawContent": include_raw_content,
        "conciseSnippet": concise_snippet,
    }
    params["headers"].update(
        {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    )
    params["raise_for_httperror"] = False


def response(resp: "SXNG_Response") -> EngineResults:
    raise_for_api_error(resp, "Metaso")
    data = resp.json()
    results = EngineResults()

    for item in data.get("webpages", []):
        url = item.get("link")
        title = item.get("title")
        if not url or not title:
            continue

        authors = item.get("authors") or []
        author = (
            ", ".join(str(value) for value in authors)
            if isinstance(authors, list)
            else str(authors)
        )
        score = item.get("score")
        metadata = f"Metaso score: {score}" if score not in (None, "") else ""
        results.add(
            results.types.MainResult(
                url=url,
                title=title,
                content=item.get("summary") or item.get("snippet") or "",
                author=author,
                publishedDate=parse_datetime(item.get("date")),
                metadata=metadata,
            )
        )
    return results
