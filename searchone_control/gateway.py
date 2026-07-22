"""Authentication and quota enforcement for SearchOne search responses."""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, Response, g, jsonify, request
from werkzeug.datastructures import MultiDict

from searx.webapp import search as searx_search

from .runtime import get_store


gateway = Blueprint("searchone_gateway", __name__)

_CONCURRENCY_LOCK = threading.Lock()
_QUOTA_LOCK = threading.Lock()
_CONCURRENCY: dict[str, int] = defaultdict(int)


def _api_error(status: int, code: str, message: str) -> tuple[Response, int]:
    return jsonify({"error": {"code": code, "message": message}}), status


def _bearer_token() -> str:
    value = request.headers.get("Authorization", "").strip()
    if not value.lower().startswith("bearer "):
        return ""
    return value[7:].strip()


def _is_api_search() -> bool:
    if request.path == "/api/v1/search":
        return True
    if request.path != "/search":
        return False
    output_format = str(request.values.get("format", "html")).lower()
    return output_format != "html"


def prepare_search_request() -> (
    tuple[Response, int] | None
):  # pylint: disable=too-many-return-statements,too-many-branches
    if not _is_api_search():
        return None

    store = get_store()
    client = store.authenticate_client(_bearer_token())
    if client is None:
        return _api_error(401, "invalid_api_key", "缺少或无效的 API Key")

    payload: dict[str, Any] = request.get_json(silent=True) or {}
    query = str(
        payload.get("query") or payload.get("q") or request.values.get("q", "")
    ).strip()
    if not query:
        return _api_error(400, "query_required", "搜索关键词不能为空")
    if len(query) > 500:
        return _api_error(400, "query_too_long", "搜索关键词不能超过 500 个字符")

    raw_engines = payload.get("engines", request.values.get("engines", ""))
    if isinstance(raw_engines, list):
        requested_engines = [
            str(item).strip() for item in raw_engines if str(item).strip()
        ]
    else:
        requested_engines = [
            item.strip() for item in str(raw_engines).split(",") if item.strip()
        ]
    allowed_engines = list(client["allowed_engines"])
    engines = requested_engines or allowed_engines
    denied = sorted(set(engines) - set(allowed_engines))
    if denied:
        return _api_error(
            403, "engine_not_allowed", f"API Key 不允许使用渠道：{', '.join(denied)}"
        )
    if not engines:
        return _api_error(403, "no_allowed_engines", "API Key 没有可用搜索渠道")

    with _QUOTA_LOCK:
        minute_count, day_count = store.quota_counts(client["id"])
        if minute_count >= client["rpm_limit"]:
            return _api_error(429, "rpm_limit_exceeded", "已超过每分钟请求限制")
        if day_count >= client["daily_limit"]:
            return _api_error(429, "daily_limit_exceeded", "已超过每日请求限制")
        usage_id = store.reserve_usage(client["id"], query, engines)

    with _CONCURRENCY_LOCK:
        if _CONCURRENCY[client["id"]] >= client["concurrency_limit"]:
            store.finalize_usage(
                usage_id,
                status_code=429,
                success=False,
                duration_ms=0,
                result_count=0,
                error_code="concurrency_limit_exceeded",
            )
            return _api_error(429, "concurrency_limit_exceeded", "已超过并发请求限制")
        _CONCURRENCY[client["id"]] += 1

    try:
        requested_limit = int(
            payload.get("limit") or request.values.get("limit") or client["max_results"]
        )
    except (TypeError, ValueError):
        requested_limit = client["max_results"]
    result_limit = max(1, min(requested_limit, client["max_results"]))
    try:
        requested_timeout = float(
            payload.get("timeout")
            or payload.get("timeout_limit")
            or request.values.get("timeout_limit")
            or client["timeout_seconds"]
        )
    except (TypeError, ValueError):
        requested_timeout = client["timeout_seconds"]
    timeout_seconds = max(1.0, min(requested_timeout, client["timeout_seconds"]))

    args = MultiDict(request.args)
    args.setlist("q", [query])
    args.setlist("engines", [",".join(engines)])
    args.setlist("format", ["json"])
    args.setlist("timeout_limit", [str(timeout_seconds)])
    for key in ("categories", "language", "time_range", "safesearch", "pageno"):
        value = payload.get(key)
        if value not in (None, ""):
            args.setlist(key, [str(value)])
    request.args = args
    request.form.update(args.to_dict(flat=True))

    g.searchone_api = {
        "client": client,
        "engines": engines,
        "result_limit": result_limit,
        "timeout_seconds": timeout_seconds,
        "usage_id": usage_id,
        "started": time.monotonic(),
        "minute_count": minute_count,
        "released": False,
    }
    return None


def finalize_search_response(response: Response) -> Response:
    context = getattr(g, "searchone_api", None)
    if not context:
        return response

    result_count = 0
    error_code = ""
    if response.is_json:
        payload = response.get_json(silent=True)
        if isinstance(payload, dict):
            results = payload.get("results")
            if isinstance(results, list):
                payload["results"] = results[: context["result_limit"]]
                result_count = len(payload["results"])
            payload["meta"] = {
                "client_key": context["client"]["key_prefix"],
                "engines": context["engines"],
                "result_limit": context["result_limit"],
                "timeout_seconds": context["timeout_seconds"],
            }
            response.set_data(json.dumps(payload, ensure_ascii=False))
        else:
            error_code = "invalid_response"

    elapsed_ms = int((time.monotonic() - context["started"]) * 1000)
    success = response.status_code < 400
    if not success and not error_code:
        error_code = f"http_{response.status_code}"
    get_store().finalize_usage(
        context["usage_id"],
        status_code=response.status_code,
        success=success,
        duration_ms=elapsed_ms,
        result_count=result_count,
        error_code=error_code,
    )
    _release_concurrency(context)
    response.headers["X-SearchOne-Key"] = context["client"]["key_prefix"]
    response.headers["X-RateLimit-Limit-Minute"] = str(context["client"]["rpm_limit"])
    response.headers["X-RateLimit-Remaining-Minute"] = str(
        max(0, context["client"]["rpm_limit"] - context["minute_count"] - 1)
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def release_search_request(_error: BaseException | None = None) -> None:
    context = getattr(g, "searchone_api", None)
    if context:
        _release_concurrency(context)


def _release_concurrency(context: dict[str, Any]) -> None:
    if context.get("released"):
        return
    with _CONCURRENCY_LOCK:
        client_id = context["client"]["id"]
        _CONCURRENCY[client_id] = max(0, _CONCURRENCY[client_id] - 1)
    context["released"] = True


@gateway.route("/api/v1/search", methods=["GET", "POST"])
def search_v1():
    return searx_search()


@gateway.route("/api/v1/key", methods=["GET"])
def key_info():
    store = get_store()
    client = store.authenticate_client(_bearer_token())
    if client is None:
        return _api_error(401, "invalid_api_key", "缺少或无效的 API Key")
    minute_count, day_count = store.quota_counts(client["id"])
    return jsonify(
        {
            "name": client["name"],
            "key_prefix": client["key_prefix"],
            "allowed_engines": client["allowed_engines"],
            "limits": {
                "rpm": client["rpm_limit"],
                "daily": client["daily_limit"],
                "concurrency": client["concurrency_limit"],
                "max_results": client["max_results"],
                "timeout_seconds": client["timeout_seconds"],
            },
            "usage": {"minute": minute_count, "day": day_count},
            "server_time": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    )
