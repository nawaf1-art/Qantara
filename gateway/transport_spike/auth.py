from __future__ import annotations

import os

from aiohttp import web

ADMIN_TOKEN_KEY: web.AppKey[str | None] = web.AppKey("admin_token", str)
AUTH_TOKEN_KEY: web.AppKey[str | None] = web.AppKey("auth_token", str)


def load_auth_token(env_name: str) -> str | None:
    token = os.environ.get(env_name, "").strip()
    return token or None


def app_bearer_token(request: web.Request, key: web.AppKey[str | None]) -> str | None:
    return request.app.get(key)


def has_valid_bearer_token(request: web.Request, key: web.AppKey[str | None]) -> bool:
    expected = app_bearer_token(request, key)
    if expected is None:
        return True
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    return scheme.lower() == "bearer" and token == expected


def require_bearer_token(
    request: web.Request,
    key: web.AppKey[str | None],
    *,
    feature_disabled_status: int | None = None,
) -> web.Response | None:
    expected = app_bearer_token(request, key)
    if expected is None:
        if feature_disabled_status == 404:
            return web.Response(status=404)
        return None
    if has_valid_bearer_token(request, key):
        return None
    return web.json_response({"error": "unauthorized"}, status=401)
