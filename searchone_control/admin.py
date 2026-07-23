"""SearchOne administration routes."""

from __future__ import annotations

import secrets
from functools import wraps
from typing import Any, Callable, TypeVar

from flask import (
    Blueprint,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from searx import engines as engine_registry, settings

from .networking import (
    apply_proxy_pool,
    parse_proxy_url,
    proxy_identity,
    test_proxies_concurrently,
    test_proxy,
)
from .providers import test_provider
from .runtime import get_database, get_store
from .tender.admin_search import (
    eligible_proxies,
    search_tenders,
    source_catalog,
)


admin = Blueprint(
    "searchone_admin",
    __name__,
    url_prefix="/admin",
    template_folder="templates",
    static_folder="static",
    static_url_path="/assets",
)

View = TypeVar("View", bound=Callable[..., Any])


def _csrf_token() -> str:
    token = session.get("searchone_csrf")
    if not token:
        token = secrets.token_urlsafe(24)
        session["searchone_csrf"] = token
    return token


def _admin_required(view: View) -> View:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any):
        if not session.get("searchone_admin"):
            if request.path.startswith("/admin/api/"):
                return jsonify({"error": "unauthorized"}), 401
            return redirect(url_for("searchone_admin.login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapped  # type: ignore[return-value]


def _require_csrf() -> tuple[Response, int] | None:
    if request.headers.get("X-CSRF-Token") != session.get("searchone_csrf"):
        return (
            jsonify({"error": "invalid_csrf", "message": "页面已过期，请刷新后重试"}),
            403,
        )
    return None


def _json_payload() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValueError("请求内容必须是 JSON 对象")
    return payload


def _audit(
    action: str,
    resource_type: str,
    resource_id: str,
    detail: dict[str, Any] | None = None,
) -> None:
    get_database().audit(
        str(session.get("searchone_admin", "admin")),
        action,
        resource_type,
        resource_id,
        detail,
    )


@admin.context_processor
def inject_admin_context() -> dict[str, Any]:
    return {
        "csrf_token": _csrf_token(),
        "admin_username": session.get("searchone_admin", ""),
    }


@admin.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        if request.form.get("csrf_token") != session.get("searchone_csrf"):
            error = "页面已过期，请刷新后重试"
        else:
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if get_store().verify_admin(username, password):
                session.clear()
                session["searchone_admin"] = username
                session["searchone_csrf"] = secrets.token_urlsafe(24)
                return redirect(url_for("searchone_admin.overview"))
            error = "用户名或密码错误"
    _csrf_token()
    return render_template("login.html", error=error)


@admin.route("/logout", methods=["POST"])
@_admin_required
def logout():
    csrf_error = _require_csrf()
    if csrf_error:
        return csrf_error
    session.clear()
    return redirect(url_for("searchone_admin.login"))


@admin.route("")
@admin.route("/")
@_admin_required
def overview():
    return render_template("overview.html", active_page="overview")


@admin.route("/clients")
@_admin_required
def clients_page():
    return render_template("clients.html", active_page="clients")


@admin.route("/providers")
@_admin_required
def providers_page():
    return render_template("providers.html", active_page="providers")


@admin.route("/proxies")
@_admin_required
def proxies_page():
    return render_template("proxies.html", active_page="proxies")


@admin.route("/tender-search")
@_admin_required
def tender_search_page():
    return render_template("tender_search.html", active_page="tender-search")


@admin.route("/api/overview")
@_admin_required
def overview_api():
    return jsonify(get_store().overview())


@admin.route("/api/tender-search/sources")
@_admin_required
def tender_search_sources_api():
    proxies = get_store().list_proxies(reveal=True)
    available = eligible_proxies(proxies)
    return jsonify(
        {
            "sources": source_catalog(),
            "available_proxies": len(available),
            "direct_mode": not available,
        }
    )


@admin.route("/api/tender-search", methods=["POST"])
@_admin_required
def tender_search_api():
    csrf_error = _require_csrf()
    if csrf_error:
        return csrf_error
    try:
        payload = _json_payload()
        raw_sources = payload.get("sources", [])
        if not isinstance(raw_sources, list):
            raise ValueError("省份网站必须是数组")
        result = search_tenders(
            str(payload.get("keyword", "")),
            [str(item) for item in raw_sources],
            get_store().list_proxies(reveal=True),
            days=int(payload.get("days", 90)),
            per_source=int(payload.get("per_source", 10)),
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"error": "invalid_search", "message": str(exc)}), 400
    _audit(
        "search",
        "tender_sources",
        "bulk",
        {
            "sources": result["searched"],
            "succeeded": result["succeeded"],
            "failed": result["failed"],
            "results": result["result_count"],
        },
    )
    return jsonify(result)


@admin.route("/api/engines")
@_admin_required
def engines_api():
    configured = {item["name"]: item for item in settings["engines"]}
    result = []
    for name, module in sorted(engine_registry.engines.items()):
        spec = configured.get(name, {})
        result.append(
            {
                "name": name,
                "shortcut": spec.get("shortcut", getattr(module, "shortcut", "")),
                "categories": spec.get(
                    "categories", getattr(module, "categories", ["general"])
                ),
                "enabled": not bool(spec.get("disabled", False)),
            }
        )
    return jsonify(result)


@admin.route("/api/clients", methods=["GET", "POST"])
@_admin_required
def clients_api():
    store = get_store()
    if request.method == "GET":
        return jsonify(store.list_clients())
    csrf_error = _require_csrf()
    if csrf_error:
        return csrf_error
    try:
        client = store.create_client(_json_payload())
    except (TypeError, ValueError) as exc:
        return jsonify({"error": "invalid_client", "message": str(exc)}), 400
    _audit("create", "client_key", client["id"], {"name": client["name"]})
    return jsonify(client), 201


@admin.route("/api/clients/<client_id>", methods=["GET", "PUT", "DELETE"])
@_admin_required
def client_api(client_id: str):  # pylint: disable=too-many-return-statements
    store = get_store()
    if request.method == "GET":
        client = store.get_client(client_id, reveal=True)
        if client is None:
            return jsonify({"error": "not_found"}), 404
        _audit("reveal", "client_key", client_id)
        response = jsonify(client)
        response.headers["Cache-Control"] = "no-store"
        return response
    csrf_error = _require_csrf()
    if csrf_error:
        return csrf_error
    if request.method == "DELETE":
        if not store.delete_client(client_id):
            return jsonify({"error": "not_found"}), 404
        _audit("delete", "client_key", client_id)
        return "", 204
    try:
        client = store.update_client(client_id, _json_payload())
    except (TypeError, ValueError) as exc:
        return jsonify({"error": "invalid_client", "message": str(exc)}), 400
    if client is None:
        return jsonify({"error": "not_found"}), 404
    _audit("update", "client_key", client_id, {"name": client["name"]})
    return jsonify(client)


@admin.route("/api/clients/<client_id>/rotate", methods=["POST"])
@_admin_required
def rotate_client_api(client_id: str):
    csrf_error = _require_csrf()
    if csrf_error:
        return csrf_error
    client = get_store().rotate_client_key(client_id)
    if client is None:
        return jsonify({"error": "not_found"}), 404
    _audit("rotate", "client_key", client_id)
    response = jsonify(client)
    response.headers["Cache-Control"] = "no-store"
    return response


@admin.route("/api/providers")
@_admin_required
def providers_api():
    return jsonify(get_store().list_providers(reveal=False))


@admin.route("/api/providers/<provider>", methods=["GET", "PUT"])
@_admin_required
def provider_api(provider: str):
    store = get_store()
    if request.method == "GET":
        item = next(
            (
                row
                for row in store.list_providers(reveal=True)
                if row["provider"] == provider
            ),
            None,
        )
        if item is None:
            return jsonify({"error": "not_found"}), 404
        _audit("reveal", "provider_credential", provider)
        response = jsonify(item)
        response.headers["Cache-Control"] = "no-store"
        return response
    csrf_error = _require_csrf()
    if csrf_error:
        return csrf_error
    payload = _json_payload()
    item = store.update_provider(
        provider, str(payload.get("secret", "")), bool(payload.get("enabled", True))
    )
    if item is None:
        return jsonify({"error": "not_found"}), 404
    _audit("update", "provider_credential", provider)
    return jsonify(item)


@admin.route("/api/providers/<provider>/test", methods=["POST"])
@_admin_required
def provider_test_api(provider: str):
    csrf_error = _require_csrf()
    if csrf_error:
        return csrf_error
    try:
        result = test_provider(provider)
    except ValueError as exc:
        return jsonify({"status": "failed", "message": str(exc)}), 400
    _audit("test", "provider_credential", provider, {"status": result["status"]})
    return jsonify(result), 200 if result["status"] == "healthy" else 502


@admin.route("/api/proxies", methods=["GET", "POST"])
@_admin_required
def proxies_api():
    store = get_store()
    if request.method == "GET":
        return jsonify(store.list_proxies(reveal=False))
    csrf_error = _require_csrf()
    if csrf_error:
        return csrf_error
    try:
        item = _validate_and_save_proxy(_json_payload())
    except (TypeError, ValueError) as exc:
        return jsonify({"error": "invalid_proxy", "message": str(exc)}), 400
    apply_proxy_pool()
    _audit("create", "proxy", item["id"], {"name": item["name"]})
    return jsonify(item), 201


@admin.route("/api/proxies/<proxy_id>", methods=["GET", "PUT", "DELETE"])
@_admin_required
def proxy_api(proxy_id: str):  # pylint: disable=too-many-return-statements
    store = get_store()
    if request.method == "GET":
        item = store.get_proxy(proxy_id, reveal=True)
        if item is None:
            return jsonify({"error": "not_found"}), 404
        _audit("reveal", "proxy", proxy_id)
        response = jsonify(item)
        response.headers["Cache-Control"] = "no-store"
        return response
    csrf_error = _require_csrf()
    if csrf_error:
        return csrf_error
    if request.method == "DELETE":
        if not store.delete_proxy(proxy_id):
            return jsonify({"error": "not_found"}), 404
        apply_proxy_pool()
        _audit("delete", "proxy", proxy_id)
        return "", 204
    try:
        item = _validate_and_save_proxy(_json_payload(), proxy_id)
    except (TypeError, ValueError) as exc:
        return jsonify({"error": "invalid_proxy", "message": str(exc)}), 400
    apply_proxy_pool()
    _audit("update", "proxy", proxy_id, {"name": item["name"]})
    return jsonify(item)


@admin.route("/api/proxies/<proxy_id>/test", methods=["POST"])
@_admin_required
def proxy_test_api(proxy_id: str):
    csrf_error = _require_csrf()
    if csrf_error:
        return csrf_error
    store = get_store()
    item = store.get_proxy(proxy_id, reveal=True)
    if item is None:
        return jsonify({"error": "not_found"}), 404
    result = test_proxy(item)
    store.update_proxy_health(
        proxy_id,
        status=result["status"],
        exit_ip=result["exit_ip"],
        latency_ms=result["latency_ms"],
        error=result["error"],
    )
    apply_proxy_pool()
    _audit("test", "proxy", proxy_id, {"status": result["status"]})
    return jsonify(result), 200 if result["status"] == "healthy" else 502


@admin.route("/api/proxies/import", methods=["POST"])
@_admin_required
def proxy_import_api():  # pylint: disable=too-many-locals,too-many-return-statements
    csrf_error = _require_csrf()
    if csrf_error:
        return csrf_error
    try:
        payload = _json_payload()
    except ValueError as exc:
        return jsonify({"error": "invalid_request", "message": str(exc)}), 400
    text = str(payload.get("text", ""))
    if len(text.encode("utf-8")) > 1_000_000:
        return (
            jsonify({"error": "import_too_large", "message": "导入内容不能超过 1 MB"}),
            400,
        )
    lines = [
        (index, line.strip())
        for index, line in enumerate(text.splitlines(), 1)
        if line.strip()
    ]
    if not lines:
        return (
            jsonify({"error": "empty_import", "message": "请粘贴代理地址或选择文件"}),
            400,
        )
    if len(lines) > 5000:
        return (
            jsonify(
                {"error": "too_many_proxies", "message": "单次最多导入 5000 个代理"}
            ),
            400,
        )

    store = get_store()
    known = {proxy_identity(item) for item in store.list_proxies(reveal=True)}
    parsed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    duplicates = 0
    enabled = bool(payload.get("enabled", True))
    try:
        weight = max(1, min(int(payload.get("weight", 1)), 100))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_weight", "message": "代理权重无效"}), 400
    channels = sorted(set(str(item) for item in payload.get("channels", []) if item))
    for line_number, value in lines:
        try:
            item = parse_proxy_url(value)
        except ValueError as exc:
            errors.append({"line": line_number, "message": str(exc)})
            continue
        identity = proxy_identity(item)
        if identity in known:
            duplicates += 1
            continue
        known.add(identity)
        item.update({"enabled": enabled, "weight": weight, "channels": channels})
        parsed.append(item)

    created = store.create_proxies(parsed)
    if created:
        apply_proxy_pool()
    _audit(
        "import",
        "proxy",
        "bulk",
        {"created": len(created), "duplicates": duplicates, "errors": len(errors)},
    )
    return (
        jsonify(
            {
                "created": len(created),
                "duplicates": duplicates,
                "errors": errors,
                "created_ids": [item["id"] for item in created],
            }
        ),
        201 if created else 200,
    )


@admin.route("/api/proxies/test", methods=["POST"])
@_admin_required
def proxies_test_api():
    csrf_error = _require_csrf()
    if csrf_error:
        return csrf_error
    try:
        payload = _json_payload()
        concurrency = max(1, min(int(payload.get("concurrency", 20)), 50))
    except (TypeError, ValueError) as exc:
        return jsonify({"error": "invalid_request", "message": str(exc)}), 400
    raw_ids = payload.get("ids", [])
    if not isinstance(raw_ids, list):
        return jsonify({"error": "invalid_ids", "message": "代理 ID 必须是数组"}), 400
    requested_ids = {str(item) for item in raw_ids if str(item).strip()}
    store = get_store()
    proxies = store.list_proxies(reveal=True)
    selected = [
        item for item in proxies if not requested_ids or item["id"] in requested_ids
    ]
    if requested_ids and len(selected) != len(requested_ids):
        return (
            jsonify({"error": "not_found", "message": "部分代理不存在，请刷新后重试"}),
            404,
        )
    if not selected:
        return jsonify({"error": "empty_proxy_pool", "message": "代理池为空"}), 400

    results = test_proxies_concurrently(selected, concurrency)
    for result in results:
        store.update_proxy_health(
            result["id"],
            status=result["status"],
            exit_ip=result["exit_ip"],
            latency_ms=result["latency_ms"],
            error=result["error"],
        )
    if bool(payload.get("enable_healthy", False)):
        store.set_proxies_enabled(
            [result["id"] for result in results if result["status"] == "healthy"],
            True,
        )
    apply_proxy_pool()
    healthy = sum(result["status"] == "healthy" for result in results)
    failed = len(results) - healthy
    _audit(
        "test",
        "proxy",
        "bulk",
        {
            "tested": len(results),
            "healthy": healthy,
            "failed": failed,
            "concurrency": concurrency,
        },
    )
    return jsonify(
        {
            "tested": len(results),
            "healthy": healthy,
            "failed": failed,
            "concurrency": min(concurrency, len(results)),
            "results": results,
        }
    )


def _validate_and_save_proxy(
    payload: dict[str, Any], proxy_id: str | None = None
) -> dict[str, Any]:
    name = str(payload.get("name", "")).strip()
    host = str(payload.get("host", "")).strip()
    scheme = str(payload.get("scheme", "http")).lower()
    if not name or not host:
        raise ValueError("代理名称和主机不能为空")
    if scheme not in {"http", "https", "socks4", "socks5", "socks5h"}:
        raise ValueError("不支持的代理协议")
    port = int(payload.get("port", 0))
    if port < 1 or port > 65535:
        raise ValueError("代理端口无效")
    payload = dict(payload)
    payload.update({"name": name, "host": host, "scheme": scheme, "port": port})
    return get_store().save_proxy(payload, proxy_id)
