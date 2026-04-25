from __future__ import annotations

import hmac
import os
import secrets

from aiohttp import web

ADMIN_TOKEN_KEY: web.AppKey[str | None] = web.AppKey("admin_token", str)
AUTH_TOKEN_KEY: web.AppKey[str | None] = web.AppKey("auth_token", str)
AUTH_SESSION_TOKEN_KEY: web.AppKey[str | None] = web.AppKey("auth_session_token", str)
AUTH_COOKIE_NAME = "qantara_auth"
MIN_AUTH_TOKEN_LENGTH = 24


def load_auth_token(env_name: str) -> str | None:
    token = os.environ.get(env_name, "").strip()
    if not token:
        return None
    if len(token) < MIN_AUTH_TOKEN_LENGTH:
        raise RuntimeError(
            f"{env_name} must be at least {MIN_AUTH_TOKEN_LENGTH} characters when set"
        )
    return token


def new_auth_session_token(auth_token: str | None) -> str | None:
    if auth_token is None:
        return None
    return secrets.token_urlsafe(32)


def app_bearer_token(request: web.Request, key: web.AppKey[str | None]) -> str | None:
    return request.app.get(key)


def has_valid_bearer_token(request: web.Request, key: web.AppKey[str | None]) -> bool:
    expected = app_bearer_token(request, key)
    if expected is None:
        return True
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(token, expected)


def has_valid_browser_session(request: web.Request) -> bool:
    expected = request.app.get(AUTH_SESSION_TOKEN_KEY)
    if expected is None:
        return False
    token = request.cookies.get(AUTH_COOKIE_NAME, "")
    return hmac.compare_digest(token, expected)


def has_valid_auth_token(request: web.Request, key: web.AppKey[str | None]) -> bool:
    expected = app_bearer_token(request, key)
    if expected is None:
        return True
    if has_valid_bearer_token(request, key):
        return True
    if key is AUTH_TOKEN_KEY and has_valid_browser_session(request):
        return True
    return False


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
    if has_valid_auth_token(request, key):
        return None
    return web.json_response({"error": "unauthorized"}, status=401)


async def api_auth_status_handler(request: web.Request) -> web.Response:
    required = app_bearer_token(request, AUTH_TOKEN_KEY) is not None
    return web.json_response(
        {
            "required": required,
            "authenticated": (not required) or has_valid_auth_token(request, AUTH_TOKEN_KEY),
        }
    )


async def api_auth_login_handler(request: web.Request) -> web.Response:
    expected = app_bearer_token(request, AUTH_TOKEN_KEY)
    if expected is None:
        return web.json_response({"ok": True, "required": False})
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    token = str(body.get("token", ""))
    if not hmac.compare_digest(token, expected):
        return web.json_response({"error": "unauthorized"}, status=401)
    session_token = request.app.get(AUTH_SESSION_TOKEN_KEY)
    if session_token is None:
        return web.json_response({"error": "auth session unavailable"}, status=500)
    response = web.json_response({"ok": True, "required": True})
    response.set_cookie(
        AUTH_COOKIE_NAME,
        session_token,
        max_age=12 * 60 * 60,
        httponly=True,
        secure=request.secure,
        samesite="Strict",
        path="/",
    )
    return response


async def api_auth_logout_handler(_request: web.Request) -> web.Response:
    response = web.json_response({"ok": True})
    response.del_cookie(AUTH_COOKIE_NAME, path="/")
    return response
