# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search the web with the Exa Search API."""

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
    "website": "https://exa.ai/",
    "wikidata_id": None,
    "official_api_documentation": "https://docs.exa.ai/reference/search",
    "use_official_api": True,
    "require_api_key": True,
    "results": "JSON",
}

categories = ["general"]
paging = False
send_accept_language_header = False

api_key = ""
base_url = "https://api.exa.ai/search"
results_per_page = 10
search_type = "auto"
include_text = True
text_max_characters = 500


def request(query: str, params: "OnlineParams") -> None:
    key = resolve_api_key(api_key, "EXA_API_KEY", "Exa")
    payload: dict[str, t.Any] = {
        "query": query,
        "numResults": results_per_page,
        "type": search_type,
    }
    if include_text:
        payload["contents"] = {"text": {"maxCharacters": text_max_characters}}

    params["url"] = base_url
    params["method"] = "POST"
    params["json"] = payload
    params["headers"].update(
        {
            "x-api-key": key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    )
    params["raise_for_httperror"] = False


def _content(item: dict[str, t.Any]) -> str:
    contents = item.get("contents")
    if isinstance(contents, dict):
        text = contents.get("text")
        if isinstance(text, str):
            return text
    for key in ("text", "excerpt", "summary"):
        value = item.get(key)
        if isinstance(value, str):
            return value
    return ""


def response(resp: "SXNG_Response") -> EngineResults:
    raise_for_api_error(resp, "Exa")
    data = resp.json()
    results = EngineResults()

    for item in data.get("results", []):
        url = item.get("url")
        title = item.get("title")
        if not url or not title:
            continue

        score = item.get("score")
        metadata = f"Exa score: {score:.3f}" if isinstance(score, (int, float)) else ""
        results.add(
            results.types.MainResult(
                url=url,
                title=title,
                content=_content(item),
                author=item.get("author") or "",
                publishedDate=parse_datetime(item.get("publishedDate")),
                thumbnail=item.get("image") or "",
                metadata=metadata,
            )
        )
    return results
