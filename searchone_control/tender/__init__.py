# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tender-search domain data and query helpers."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


_DATA_DIR = Path(__file__).resolve().parent
_CONFIG_PATH = _DATA_DIR / "deep-search-config.json"
_PROFILE_PATH = _DATA_DIR / "default-profile.json"
_CATALOG_PATH = _DATA_DIR / "china500-procurement-platforms-2025.csv"
_WHITESPACE = re.compile(r"\s+")
_YEAR = re.compile(r"\b20\d{2}\b")


@dataclass(frozen=True)
class TenderSource:
    """One official or corporate procurement source."""

    name: str
    domain: str
    tier: str
    priority: int
    region: str = ""
    catalog_id: str = ""


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig") as handle:
        return json.load(handle)


def _domain(value: str) -> str:
    host = (urlsplit(value).hostname or "").lower()
    return host.removeprefix("www.")


@lru_cache(maxsize=1)
def search_config() -> dict[str, Any]:
    """Return the bundled tender-search configuration."""

    return _load_json(_CONFIG_PATH)


@lru_cache(maxsize=1)
def search_profile() -> dict[str, Any]:
    """Return the bundled supplier profile and keyword groups."""

    return _load_json(_PROFILE_PATH)


@lru_cache(maxsize=1)
def catalog_sources() -> tuple[TenderSource, ...]:
    """Load the China 500 procurement-platform catalog."""

    priority_map = (
        search_config().get("enterprise_platform_catalog", {}).get("priority_map")
        or {"A": 2, "B": 3, "C": 4}
    )
    sources = []
    with _CATALOG_PATH.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            domain = _domain(str(row.get("平台主页URL") or ""))
            catalog_id = str(row.get("目录ID") or "").strip()
            if not domain or not catalog_id:
                continue
            grade = str(row.get("适配优先级") or "C").strip().upper()
            sources.append(
                TenderSource(
                    name="｜".join(
                        value
                        for value in (
                            str(row.get("企业名称") or "").strip(),
                            str(row.get("平台名称") or "").strip(),
                        )
                        if value
                    ),
                    domain=domain,
                    tier="china500_corporate",
                    priority=int(priority_map.get(grade, 4)),
                    region=str(row.get("重点区域") or "").strip(),
                    catalog_id=catalog_id,
                )
            )
    return tuple(sources)


@lru_cache(maxsize=1)
def tender_sources() -> tuple[TenderSource, ...]:
    """Return one preferred source record for every configured domain."""

    by_domain: dict[str, TenderSource] = {}
    for item in search_config().get("sources", []):
        domain = _domain(str(item.get("url") or ""))
        if not domain:
            continue
        source = TenderSource(
            name=str(item.get("name") or domain),
            domain=domain,
            tier=str(item.get("tier") or "official"),
            priority=int(item.get("priority") or 3),
            region=str(item.get("region") or ""),
        )
        current = by_domain.get(domain)
        if current is None or source.priority < current.priority:
            by_domain[domain] = source

    for source in catalog_sources():
        current = by_domain.get(source.domain)
        if current is None or source.priority < current.priority:
            by_domain[source.domain] = source

    return tuple(
        sorted(
            by_domain.values(),
            key=lambda item: (item.priority, item.tier, item.domain),
        )
    )


@lru_cache(maxsize=1)
def tender_domains() -> tuple[str, ...]:
    """Return the deterministic domain allow-list sent to the search API."""

    return tuple(source.domain for source in tender_sources())


def source_for_url(url: str) -> TenderSource | None:
    """Find the most specific configured source matching a result URL."""

    domain = _domain(url)
    if not domain:
        return None
    matches = (
        source
        for source in tender_sources()
        if domain == source.domain or domain.endswith("." + source.domain)
    )
    return max(matches, key=lambda item: len(item.domain), default=None)


def build_tender_query(query: str) -> str:
    """Add procurement and matched product synonyms to a user query."""

    normalized = _WHITESPACE.sub(" ", query).strip()
    config = search_config()
    profile = search_profile()
    additions: list[str] = []
    lower_query = normalized.lower()

    for keywords in profile.get("keyword_groups", {}).values():
        values = [str(value).strip() for value in keywords if str(value).strip()]
        if any(value.lower() in lower_query for value in values):
            additions.extend(value for value in values[:6] if value not in normalized)

    procurement_terms = [
        str(value).strip()
        for value in config.get("procurement_terms", [])[:10]
        if str(value).strip() and str(value).strip() not in normalized
    ]
    parts = [normalized]
    if not _YEAR.search(normalized):
        parts.append(str(date.today().year))
    if additions:
        parts.append("(" + " OR ".join(dict.fromkeys(additions)) + ")")
    if procurement_terms:
        parts.append("(" + " OR ".join(procurement_terms) + ")")
    return " ".join(part for part in parts if part)


def has_explicit_year(query: str) -> bool:
    """Return whether the user explicitly requested a calendar year."""

    return bool(_YEAR.search(query))


def source_metadata(source: TenderSource, score: Any = None) -> str:
    """Build compact, user-facing metadata for a tender result."""

    values = [source.name, source.tier]
    if source.region:
        values.append(source.region)
    if isinstance(score, (int, float)):
        values.append(f"Tavily score: {score:.3f}")
    return " | ".join(values)
