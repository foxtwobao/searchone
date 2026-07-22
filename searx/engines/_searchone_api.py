# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared helpers for SearchOne API-backed engines."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from dateutil import parser as date_parser

from searchone_control.runtime import provider_secret

from searx.exceptions import (
    SearxEngineAPIException,
    SearxEngineAccessDeniedException,
    SearxEngineTooManyRequestsException,
)


_INVALID_KEYS = {"", "unset", "unknown", "..."}


def resolve_api_key(configured_key: str | None, env_name: str, provider: str) -> str:
    """Return a hot-reloadable provider key, then fall back to static config."""

    try:
        found, enabled, managed_key = provider_secret(env_name)
    except RuntimeError:
        found, enabled, managed_key = False, False, ""
    if found and not enabled:
        raise SearxEngineAPIException(f"{provider}: provider is disabled")
    if managed_key.strip():
        return managed_key.strip()

    key = (configured_key or os.environ.get(env_name, "")).strip()
    if key.lower() in _INVALID_KEYS:
        raise SearxEngineAPIException(f"{provider}: missing API key ({env_name})")
    return key


def parse_datetime(value: Any) -> datetime | None:
    """Parse common API timestamp formats without failing a search response."""

    parsed = None
    if value in (None, ""):
        pass
    elif isinstance(value, (int, float)):
        try:
            parsed = datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            pass
    elif isinstance(value, str):
        if value.isdigit():
            parsed = parse_datetime(int(value))
        else:
            try:
                parsed = date_parser.parse(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError, OverflowError):
                pass
    return parsed


def error_message(payload: Any, fallback: str) -> str:
    """Extract a concise error message from common JSON error envelopes."""

    if not isinstance(payload, dict):
        return fallback

    for key in ("message", "detail", "error", "msg"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            for nested_key in ("message", "detail", "error", "msg"):
                nested = value.get(nested_key)
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
    return fallback


def raise_for_api_error(resp, provider: str) -> None:
    """Map API HTTP failures to SearXNG engine exceptions."""

    status = resp.status_code or 0
    if status < 400:
        return

    try:
        payload = resp.json()
    except Exception:  # pylint: disable=broad-exception-caught
        payload = None
    message = error_message(payload, f"HTTP {status}")
    message = f"{provider}: {message}"

    if status == 429:
        raise SearxEngineTooManyRequestsException(message=message)
    if status in (402, 403):
        raise SearxEngineAccessDeniedException(message=message)
    raise SearxEngineAPIException(message)
