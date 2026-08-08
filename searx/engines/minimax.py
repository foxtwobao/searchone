# SPDX-License-Identifier: AGPL-3.0-or-later
"""Search the web with the MiniMax TokenPlan Search API."""

from __future__ import annotations

import typing as t

from searx.engines._searchone_api import (
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
    "website": "https://www.minimaxi.com/",
    "wikidata_id": None,
    "official_api_documentation": "https://platform.minimaxi.com/",
    "use_official_api": True,
    "require_api_key": True,
    "results": "JSON",
}

categories = ["general"]
paging = False
send_accept_language_header = False

api_key = ""
base_url = "https://api.minimaxi.com/v1/coding_plan/search"


def request(query: str, params: "OnlineParams") -> None:
    key = resolve_api_key(api_key, "MINIMAX_API_KEY", "MiniMax")
    params["url"] = base_url
    params["method"] = "POST"
    params["json"] = {"q": query}
    params["headers"].update(
        {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    )
    params["raise_for_httperror"] = False


def response(resp: "SXNG_Response") -> EngineResults:
    raise_for_api_error(resp, "MiniMax")
    try:
        data = resp.json()
    except (TypeError, ValueError) as exc:
        raise SearxEngineAPIException("MiniMax: invalid JSON response") from exc

    if not isinstance(data, dict) or not isinstance(data.get("organic"), list):
        raise SearxEngineAPIException("MiniMax: invalid response payload")

    results = EngineResults()
    for item in data["organic"]:
        if not isinstance(item, dict):
            continue
        url = item.get("link")
        title = item.get("title")
        if not isinstance(url, str) or not url.strip():
            continue
        if not isinstance(title, str) or not title.strip():
            continue
        results.add(
            results.types.MainResult(
                url=url.strip(),
                title=title.strip(),
                content=item.get("snippet") or "",
                publishedDate=parse_datetime(item.get("date")),
            )
        )
    return results
