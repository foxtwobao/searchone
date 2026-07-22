"""Attach SearchOne administration and API policy to the existing Flask app."""

from __future__ import annotations

from flask import Flask

from searx.webapp import app as searx_app

from .admin import admin
from .gateway import (
    finalize_search_response,
    gateway,
    prepare_search_request,
    release_search_request,
)
from .networking import apply_proxy_pool
from .runtime import initialize_runtime


def create_app() -> Flask:
    flask_app = searx_app
    if flask_app.extensions.get("searchone_control"):
        return flask_app

    config, _, _ = initialize_runtime()
    flask_app.secret_key = config.session_secret
    flask_app.config.update(
        SESSION_COOKIE_NAME="searchone_admin_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        PERMANENT_SESSION_LIFETIME=3600 * 8,
    )
    flask_app.register_blueprint(admin)
    flask_app.register_blueprint(gateway)

    flask_app.before_request_funcs.setdefault(None, []).append(prepare_search_request)
    flask_app.after_request(finalize_search_response)
    flask_app.teardown_request(release_search_request)
    flask_app.extensions["searchone_control"] = True
    apply_proxy_pool()
    return flask_app


app = create_app()
