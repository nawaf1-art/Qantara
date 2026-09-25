from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import math
import os
import secrets
import time
import unicodedata
from collections import deque
from collections.abc import Callable
from typing import Any

from aiohttp import web

LOGGER = logging.getLogger(__name__)

ADMIN_TOKEN_KEY: web.AppKey[str | None] = web.AppKey("admin_token", str)
AUTH_TOKEN_KEY: web.AppKey[str | None] = web.AppKey("auth_token", str)
AUTH_COOKIE_NAME = "qantara_auth"
MIN_AUTH_TOKEN_LENGTH = 24
DEFAULT_AUTH_SESSION_TTL_SECONDS = 12 * 60 * 60
MAX_AUTH_SESSIONS = 256
AUTH_FAILURE_LIMIT = 10
AUTH_FAILURE_WINDOW_SECONDS = 60.0
AUTH_FAILURE_MAX_CLIENTS = 1024


def _token_bytes(value: str) -> bytes:
    # surrogatepass keeps undecodable env bytes / lone surrogates comparable
    # instead of raising, so a hostile header can never turn into a 500.
    return value.encode("utf-8", "surrogatepass")


def tokens_equal(presented: str, expected: str) -> bool:
    """Constant-time token comparison that accepts any Unicode text.

    ``hmac.compare_digest`` refuses non-ASCII ``str`` values, which made an
    Arabic ``QANTARA_AUTH_TOKEN`` crash login with a 500. Compare UTF-8 bytes.
    """
    if not isinstance(presented, str) or not isinstance(expected, str):
        return False
    return hmac.compare_digest(_token_bytes(presented), _token_bytes(expected))


def load_auth_token(env_name: str) -> str | None:
    token = os.environ.get(env_name, "").strip()
    if not token:
        return None
    if len(token) < MIN_AUTH_TOKEN_LENGTH:
        raise RuntimeError(
            f"{env_name} must be at least {MIN_AUTH_TOKEN_LENGTH} characters when set"
        )
    if any(ch.isspace() or unicodedata.category(ch).startswith("C") for ch in token):
        raise RuntimeError(
            f"{env_name} must not contain whitespace or control characters"
        )
    if not token.isascii():
        LOGGER.warning(
            "%s contains non-ASCII characters; browser login works, but API clients "
            "must send the Bearer header UTF-8 encoded",
            env_name,
        )
    return token


def load_auth_session_ttl() -> int:
    raw = os.environ.get("QANTARA_AUTH_SESSION_TTL_SECONDS", "").strip()
    if not raw:
        return DEFAULT_AUTH_SESSION_TTL_SECONDS
    try:
        ttl = int(raw)
    except ValueError:
        raise RuntimeError(
            "QANTARA_AUTH_SESSION_TTL_SECONDS must be a positive integer number of seconds"
        ) from None
    if ttl <= 0:
        raise RuntimeError(
            "QANTARA_AUTH_SESSION_TTL_SECONDS must be a positive integer number of seconds"
        )
    return ttl


def _digest(value: str) -> str:
    return hashlib.sha256(_token_bytes(value)).hexdigest()


class AuthSessionStore:
    """Server-side browser sessions: one random id per login, with expiry.

    Only a SHA-256 of each session id is kept, so lookups do not leak timing
    about stored ids. The map is bounded; the oldest session is evicted when
    it is full.
    """

    def __init__(
        self,
        ttl_seconds: float = DEFAULT_AUTH_SESSION_TTL_SECONDS,
        *,
        max_sessions: int = MAX_AUTH_SESSIONS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self._clock = clock
        self._sessions: dict[str, float] = {}

    def __len__(self) -> int:
        return len(self._sessions)

    def _prune(self) -> None:
        now = self._clock()
        for key in [key for key, expiry in self._sessions.items() if expiry <= now]:
            self._sessions.pop(key, None)

    def create(self) -> str:
        self._prune()
        while len(self._sessions) >= self.max_sessions:
            self._sessions.pop(next(iter(self._sessions)), None)
        session_id = secrets.token_urlsafe(32)
        self._sessions[_digest(session_id)] = self._clock() + self.ttl_seconds
        return session_id

    def is_valid(self, session_id: str | None) -> bool:
        if not session_id:
            return False
        key = _digest(session_id)
        expiry = self._sessions.get(key)
        if expiry is None:
            return False
        if expiry <= self._clock():
            self._sessions.pop(key, None)
            return False
        return True

    def revoke(self, session_id: str | None) -> None:
        if session_id:
            self._sessions.pop(_digest(session_id), None)


class AuthFailureLimiter:
    """Sliding-window limiter for failed credentials, keyed by client address.

    Only *distinct* wrong credentials count: a browser replaying a stale
    cookie or a client polling with an outdated token is counted once, while
    guessing requires new values and is capped at ``max_failures`` per window.
    Memory is bounded by ``max_clients`` x ``max_failures`` entries.
    """

    def __init__(
        self,
        *,
        max_failures: int = AUTH_FAILURE_LIMIT,
        window_seconds: float = AUTH_FAILURE_WINDOW_SECONDS,
        max_clients: int = AUTH_FAILURE_MAX_CLIENTS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.max_clients = max_clients
        self._clock = clock
        self._failures: dict[str, deque[tuple[float, str]]] = {}

    def client_count(self) -> int:
        return len(self._failures)

    def _entries(self, key: str, now: float) -> deque[tuple[float, str]] | None:
        entries = self._failures.get(key)
        if entries is None:
            return None
        cutoff = now - self.window_seconds
        while entries and entries[0][0] <= cutoff:
            entries.popleft()
        if not entries:
            self._failures.pop(key, None)
            return None
        return entries

    def retry_after(self, key: str) -> float | None:
        now = self._clock()
        entries = self._entries(key, now)
        if entries is None or len(entries) < self.max_failures:
            return None
        return max(entries[0][0] + self.window_seconds - now, 0.001)

    def record_failure(self, key: str, credential: str) -> None:
        now = self._clock()
        digest = _digest(credential)[:32]
        entries = self._entries(key, now)
        if entries is None:
            if len(self._failures) >= self.max_clients:
                for stale in list(self._failures):
                    self._entries(stale, now)
                while len(self._failures) >= self.max_clients:
                    self._failures.pop(next(iter(self._failures)), None)
            entries = deque()
            self._failures[key] = entries
        if len(entries) >= self.max_failures:
            return
        if any(existing == digest for _, existing in entries):
            return
        entries.append((now, digest))


AUTH_SESSION_STORE_KEY: web.AppKey[AuthSessionStore] = web.AppKey(
    "auth_session_store", AuthSessionStore
)
AUTH_FAILURE_LIMITER_KEY: web.AppKey[AuthFailureLimiter] = web.AppKey(
    "auth_failure_limiter", AuthFailureLimiter
)


def install_auth(app: web.Application) -> str | None:
    """Load and validate tokens and attach per-app session/limiter state."""
    auth_token = load_auth_token("QANTARA_AUTH_TOKEN")
    app[AUTH_TOKEN_KEY] = auth_token
    app[ADMIN_TOKEN_KEY] = load_auth_token("QANTARA_ADMIN_TOKEN")
    app[AUTH_SESSION_STORE_KEY] = AuthSessionStore(load_auth_session_ttl())
    app[AUTH_FAILURE_LIMITER_KEY] = AuthFailureLimiter()
    return auth_token


def client_key(request: web.Request) -> str:
    """Identify the client for the failure limiter.

    Behind the documented loopback reverse proxy every request arrives from
    127.0.0.1, so for loopback peers the right-most X-Forwarded-For entry
    (the one the proxy appended) is used instead.
    """
    remote = request.remote or "unknown"
    try:
        is_loopback = ipaddress.ip_address(remote).is_loopback
    except ValueError:
        is_loopback = False
    if is_loopback:
        forwarded = request.headers.get("X-Forwarded-For", "")
        last = forwarded.rsplit(",", 1)[-1].strip()
        if last:
            return f"{remote}|{last[:64]}"
    return remote


def app_bearer_token(request: web.Request, key: web.AppKey[str | None]) -> str | None:
    return request.app.get(key)


def _presented_bearer(request: web.Request) -> str | None:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token


def has_valid_bearer_token(request: web.Request, key: web.AppKey[str | None]) -> bool:
    expected = app_bearer_token(request, key)
    if expected is None:
        return True
    token = _presented_bearer(request)
    return token is not None and tokens_equal(token, expected)


def has_valid_browser_session(request: web.Request) -> bool:
    if request.app.get(AUTH_TOKEN_KEY) is None:
        return False
    store = request.app.get(AUTH_SESSION_STORE_KEY)
    if store is None:
        return False
    return store.is_valid(request.cookies.get(AUTH_COOKIE_NAME, ""))


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


def _too_many_attempts(retry_after: float) -> web.Response:
    seconds = max(1, math.ceil(retry_after))
    return web.json_response(
        {"error": "too many failed authentication attempts; retry later"},
        status=429,
        headers={"Retry-After": str(seconds)},
    )


def _credential_check(request: web.Request) -> tuple[list[str], bool, bool]:
    """Return (presented credentials, any valid, stale cookie presented)."""
    auth_token = request.app.get(AUTH_TOKEN_KEY)
    admin_token = request.app.get(ADMIN_TOKEN_KEY)
    presented: list[str] = []
    valid = False
    stale_cookie = False
    header = request.headers.get("Authorization", "")
    if header:
        presented.append(f"authorization:{header}")
        bearer = _presented_bearer(request)
        if bearer is not None and any(
            expected is not None and tokens_equal(bearer, expected)
            for expected in (auth_token, admin_token)
        ):
            valid = True
    cookie = request.cookies.get(AUTH_COOKIE_NAME, "")
    if cookie and auth_token is not None:
        presented.append(f"cookie:{cookie}")
        if has_valid_browser_session(request):
            valid = True
        else:
            stale_cookie = True
    return presented, valid, stale_cookie


def _auth_limited_path(path: str) -> bool:
    return path.startswith("/api/") or path == "/ws"


@web.middleware
async def auth_failure_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    """Count wrong credentials on every protected route and lock out guessers.

    Every Bearer/cookie-protected route answers differently for right and
    wrong tokens, so limiting only the login route would leave a token
    oracle. Requests that present no credentials are never counted.
    """
    limiter = request.app.get(AUTH_FAILURE_LIMITER_KEY)
    if limiter is None or not _auth_limited_path(request.path):
        return await handler(request)
    if request.app.get(AUTH_TOKEN_KEY) is None:
        # Without a gateway token only the admin API checks credentials.
        if request.app.get(ADMIN_TOKEN_KEY) is None or not request.path.startswith("/api/admin/"):
            return await handler(request)
    key = client_key(request)
    presented, valid, stale_cookie = _credential_check(request)
    is_login = request.method == "POST" and request.path == "/api/auth/login"
    if presented or is_login:
        retry_after = limiter.retry_after(key)
        if retry_after is not None:
            return _too_many_attempts(retry_after)
    if presented and not valid:
        for credential in presented:
            limiter.record_failure(key, credential)
    response = await handler(request)
    if stale_cookie and isinstance(response, web.Response) and not response.prepared:
        response.del_cookie(AUTH_COOKIE_NAME, path="/")
    return response


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
    if not isinstance(body, dict):
        return web.json_response({"error": "invalid JSON body"}, status=400)
    token = body.get("token", "")
    if not isinstance(token, str):
        return web.json_response({"error": "token must be a string"}, status=400)
    if not tokens_equal(token, expected):
        limiter = request.app.get(AUTH_FAILURE_LIMITER_KEY)
        if limiter is not None:
            limiter.record_failure(client_key(request), f"login:{token}")
        return web.json_response({"error": "unauthorized"}, status=401)
    store = request.app.get(AUTH_SESSION_STORE_KEY)
    if store is None:
        return web.json_response({"error": "auth session unavailable"}, status=500)
    # Rotate: a fresh login replaces whatever session this browser held.
    store.revoke(request.cookies.get(AUTH_COOKIE_NAME, ""))
    session_id = store.create()
    response = web.json_response({"ok": True, "required": True})
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "").split(",", 1)[
        0
    ].strip().lower()
    response.set_cookie(
        AUTH_COOKIE_NAME,
        session_id,
        max_age=int(store.ttl_seconds),
        httponly=True,
        secure=request.secure or forwarded_proto == "https",
        samesite="Strict",
        path="/",
    )
    return response


async def api_auth_logout_handler(request: web.Request) -> web.Response:
    store = request.app.get(AUTH_SESSION_STORE_KEY)
    if store is not None:
        store.revoke(request.cookies.get(AUTH_COOKIE_NAME, ""))
    response = web.json_response({"ok": True})
    response.del_cookie(AUTH_COOKIE_NAME, path="/")
    return response
