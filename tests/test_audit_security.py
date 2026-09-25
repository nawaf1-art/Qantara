"""Regression tests for the 2026-09-24 audit security findings.

Covers Q-10/S-b (no-token Host policy), S-c (Fetch-Metadata + backend probe
single-flight), S-g (per-login sessions, logout revoke, auth failure limiter),
HS-9 (non-ASCII tokens), HS-10 (MCP command redaction), HS-K6, CSP, mesh peer
filtering, and the setup-page TTS engine swap. Everything runs in-process with
no real network or subprocesses.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

from adapters.base import AdapterConfig
from gateway.transport_spike import http_api
from gateway.transport_spike.auth import (
    AUTH_COOKIE_NAME,
    AuthFailureLimiter,
    AuthSessionStore,
    load_auth_session_ttl,
    load_auth_token,
    tokens_equal,
)
from gateway.transport_spike.runtime import GatewayRuntime
from gateway.transport_spike.server import create_app

try:
    from test_gateway_http import FakeSTT, FakeTTS
except ModuleNotFoundError:  # pragma: no cover - path fallback
    from tests.test_gateway_http import FakeSTT, FakeTTS

REPO_ROOT = Path(__file__).resolve().parents[1]
TOKEN = "voice-secret-token-123456"


def _runtime() -> GatewayRuntime:
    return GatewayRuntime(
        adapter_config=AdapterConfig(kind="mock", name="mock"),
        stt=FakeSTT(),
        tts=FakeTTS(),
        event_sink=lambda _record: None,
    )


class _GatewayCase(unittest.IsolatedAsyncioTestCase):
    """Starts a gateway app with a controlled environment per test."""

    base_env: dict[str, str] = {}

    async def asyncSetUp(self) -> None:
        self.client: TestClient | None = None
        self.env_patch = None
        await self._start({})

    async def asyncTearDown(self) -> None:
        await self._stop()

    async def _stop(self) -> None:
        if self.client is not None:
            await self.client.close()
            self.client = None
        if self.env_patch is not None:
            self.env_patch.stop()
            self.env_patch = None

    async def _start(self, env: dict[str, str], runtime: GatewayRuntime | None = None) -> None:
        await self._stop()
        merged = {
            "QANTARA_AUTH_TOKEN": "",
            "QANTARA_ADMIN_TOKEN": "",
            "QANTARA_ALLOWED_HOSTS": "",
            "QANTARA_ALLOWED_ORIGINS": "",
            "QANTARA_ALLOW_CGNAT": "",
            "QANTARA_AUTH_SESSION_TTL_SECONDS": "",
            **self.base_env,
            **env,
        }
        self.env_patch = patch.dict(os.environ, merged)
        self.env_patch.start()
        self.runtime = runtime or _runtime()
        self.app = create_app(self.runtime)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()


# --------------------------------------------------------------------------
# Q-10 / S-b / R-3: no-token posture only accepts loopback Host values
# --------------------------------------------------------------------------


class NoTokenHostPolicyTests(_GatewayCase):
    async def test_loopback_hosts_are_accepted_without_token(self) -> None:
        port = self.client.port
        for host in (
            f"127.0.0.1:{port}",
            "127.0.0.1",
            "127.1.2.3:8765",
            f"localhost:{port}",
            "localhost",
            f"[::1]:{port}",
            "[::1]",
        ):
            with self.subTest(host=host):
                resp = await self.client.get("/api/status", headers={"Host": host})
                self.assertEqual(resp.status, 200)

    async def test_lan_hosts_rejected_without_token_with_clear_message(self) -> None:
        for host in (
            "qantara.local",
            "qantara.local:443",
            "192.168.1.20:8765",
            "10.0.0.5",
            "wpad",
            "attacker-box.local:8765",
        ):
            with self.subTest(host=host):
                resp = await self.client.post(
                    "/api/configure", json={"type": "mock"}, headers={"Host": host}
                )
                self.assertEqual(resp.status, 421)
                body = await resp.json()
                self.assertIn("Set QANTARA_AUTH_TOKEN to allow LAN access", body["error"])

    async def test_caddy_shaped_request_fails_closed_without_token(self) -> None:
        headers = {
            "Host": "qantara.local",
            "Origin": "https://qantara.local",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-For": "192.168.1.23",
        }
        configure = await self.client.post("/api/configure", json={"type": "mock"}, headers=headers)
        status = await self.client.get("/api/control/voice/status", headers=headers)
        self.assertEqual(configure.status, 421)
        self.assertEqual(status.status, 421)

    async def test_websocket_rejects_rebound_host_without_token(self) -> None:
        resp = await self.client.get(
            "/ws", headers={"Host": "attacker-box.local", "Origin": "http://attacker-box.local"}
        )
        self.assertEqual(resp.status, 421)

    async def test_allowed_hosts_is_the_explicit_escape_hatch(self) -> None:
        await self._start({"QANTARA_ALLOWED_HOSTS": "qantara.local, kitchen.lan:8765"})
        for host in ("qantara.local", "qantara.local:443", "kitchen.lan"):
            with self.subTest(host=host):
                resp = await self.client.get("/api/status", headers={"Host": host})
                self.assertEqual(resp.status, 200)
        other = await self.client.get("/api/status", headers={"Host": "other.local"})
        self.assertEqual(other.status, 421)

    async def test_lan_hosts_allowed_when_token_is_set(self) -> None:
        await self._start({"QANTARA_AUTH_TOKEN": TOKEN})
        for host in ("qantara.local", "192.168.1.20:8765", "wpad"):
            with self.subTest(host=host):
                resp = await self.client.get(
                    "/api/control/voice/status",
                    headers={"Host": host, "Authorization": f"Bearer {TOKEN}"},
                )
                self.assertEqual(resp.status, 200)
        public = await self.client.get(
            "/api/status", headers={"Host": "evil.example", "Authorization": f"Bearer {TOKEN}"}
        )
        self.assertEqual(public.status, 421)


class StartupWarningTests(unittest.TestCase):
    env = {"QANTARA_AUTH_TOKEN": "", "QANTARA_ADMIN_TOKEN": "", "QANTARA_SPIKE_HOST": "127.0.0.1"}

    def test_bind_host_argument_drives_warning(self) -> None:
        with patch.dict(os.environ, self.env), self.assertLogs(
            "gateway.transport_spike.server", level="WARNING"
        ) as captured:
            create_app(_runtime(), bind_host="0.0.0.0")
        self.assertTrue(any("QANTARA_AUTH_TOKEN" in line for line in captured.output))

    def test_loopback_bind_does_not_warn(self) -> None:
        with patch.dict(os.environ, self.env), self.assertNoLogs(
            "gateway.transport_spike.server", level="WARNING"
        ):
            create_app(_runtime(), bind_host="127.0.0.1")

    def test_sdk_voice_gateway_passes_host_to_create_app(self) -> None:
        from qantara import VoiceGateway

        with patch("gateway.transport_spike.server.create_app") as fake_create:
            VoiceGateway(host="0.0.0.0", port=9999, runtime="rt").create_app()
        fake_create.assert_called_once()
        self.assertEqual(fake_create.call_args.kwargs.get("bind_host"), "0.0.0.0")


# --------------------------------------------------------------------------
# S-c: Fetch-Metadata, origin-protected backend probes, single-flight cache
# --------------------------------------------------------------------------


class _CountingProbes:
    def __init__(self, delay: float = 0.05) -> None:
        self.calls = {"ollama": 0, "openclaw": 0, "openai": 0, "mcp": 0}
        self.delay = delay

    def patchers(self):
        async def ollama():
            self.calls["ollama"] += 1
            await asyncio.sleep(self.delay)
            return {"available": False}

        async def openclaw():
            self.calls["openclaw"] += 1
            await asyncio.sleep(self.delay)
            return {"available": False, "installed": False, "gateway_running": False, "agents": []}

        async def openai():
            self.calls["openai"] += 1
            await asyncio.sleep(self.delay)
            return {"available": False, "servers": []}

        async def mcp():
            self.calls["mcp"] += 1
            await asyncio.sleep(self.delay)
            return {"available": False, "configured": False}

        return [
            patch.object(http_api, "probe_ollama", ollama),
            patch.object(http_api, "probe_openclaw", openclaw),
            patch.object(http_api, "probe_openai_compatible", openai),
            patch.object(http_api, "probe_mcp", mcp),
        ]


class FetchMetadataAndProbeTests(_GatewayCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.probes = _CountingProbes()
        self._patchers = self.probes.patchers()
        for patcher in self._patchers:
            patcher.start()

    async def asyncTearDown(self) -> None:
        for patcher in self._patchers:
            patcher.stop()
        await super().asyncTearDown()

    async def test_cross_site_api_request_is_rejected(self) -> None:
        resp = await self.client.get("/api/status", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(resp.status, 403)

    async def test_same_origin_and_none_fetch_site_allowed(self) -> None:
        for value in ("same-origin", "none", "same-site"):
            with self.subTest(value=value):
                resp = await self.client.get("/api/status", headers={"Sec-Fetch-Site": value})
                self.assertEqual(resp.status, 200)

    async def test_cross_site_allowed_for_allowlisted_origin(self) -> None:
        await self._start({"QANTARA_ALLOWED_ORIGINS": "https://dashboard.example"})
        resp = await self.client.get(
            "/api/status",
            headers={"Sec-Fetch-Site": "cross-site", "Origin": "https://dashboard.example"},
        )
        self.assertEqual(resp.status, 200)

    async def test_backends_get_rejects_foreign_origin(self) -> None:
        for path in ("/api/backends", "/api/backends/stream"):
            with self.subTest(path=path):
                resp = await self.client.get(path, headers={"Origin": "https://evil.example"})
                self.assertEqual(resp.status, 403)
        self.assertEqual(sum(self.probes.calls.values()), 0)

    async def test_backend_probes_are_single_flight_and_cached(self) -> None:
        responses = await asyncio.gather(*(self.client.get("/api/backends") for _ in range(6)))
        for resp in responses:
            self.assertEqual(resp.status, 200)
            await resp.json()
        self.assertEqual(self.probes.calls["openclaw"], 1)
        self.assertEqual(self.probes.calls["mcp"], 1)

        stream = await self.client.get("/api/backends/stream")
        text = await stream.text()
        self.assertIn("event: done", text)
        self.assertEqual(self.probes.calls["openclaw"], 1)

    async def test_backend_probe_cache_expires(self) -> None:
        now = [1000.0]
        cache = http_api.BackendProbeCache(ttl_seconds=10.0, clock=lambda: now[0])
        calls = []

        async def factory():
            calls.append(1)
            return {"available": True}

        self.assertEqual(await cache.get("x", factory), {"available": True})
        await cache.get("x", factory)
        self.assertEqual(len(calls), 1)
        now[0] += 10.5
        await cache.get("x", factory)
        self.assertEqual(len(calls), 2)

    async def test_backend_probe_failure_is_not_cached(self) -> None:
        cache = http_api.BackendProbeCache(ttl_seconds=10.0)
        calls = []

        async def failing():
            calls.append(1)
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            await cache.get("y", failing)
        with self.assertRaises(RuntimeError):
            await cache.get("y", failing)
        self.assertEqual(len(calls), 2)


# --------------------------------------------------------------------------
# S-g: per-login sessions, logout revoke, failure limiter; HS-9 byte compare
# --------------------------------------------------------------------------


class AuthSessionTests(_GatewayCase):
    base_env = {"QANTARA_AUTH_TOKEN": TOKEN}

    async def _login(self, token: str = TOKEN, headers: dict[str, str] | None = None):
        return await self.client.post("/api/auth/login", json={"token": token}, headers=headers or {})

    def _cookie_value(self, resp) -> str:
        morsel = resp.cookies.get(AUTH_COOKIE_NAME)
        self.assertIsNotNone(morsel, "login did not set the auth cookie")
        return morsel.value

    async def test_each_login_gets_a_distinct_session(self) -> None:
        first = self._cookie_value(await self._login())
        self.client.session.cookie_jar.clear()
        second = self._cookie_value(await self._login())
        self.assertNotEqual(first, second)
        self.assertNotEqual(first, TOKEN)

    async def test_cookie_session_authenticates_and_logout_revokes_server_side(self) -> None:
        login = await self._login()
        self.assertEqual(login.status, 200)
        sid = self._cookie_value(login)
        # Replay the cookie explicitly so the test does not depend on the jar.
        self.client.session.cookie_jar.clear()
        cookie_header = {"Cookie": f"{AUTH_COOKIE_NAME}={sid}"}
        ok = await self.client.get("/api/control/voice/status", headers=cookie_header)
        self.assertEqual(ok.status, 200)

        logout = await self.client.post("/api/auth/logout", headers=cookie_header)
        self.assertEqual(logout.status, 200)
        self.client.session.cookie_jar.clear()

        replay = await self.client.get("/api/control/voice/status", headers=cookie_header)
        self.assertEqual(replay.status, 401)
        status = await self.client.get("/api/auth/status", headers=cookie_header)
        self.assertFalse((await status.json())["authenticated"])

    async def test_logout_of_one_session_keeps_other_sessions(self) -> None:
        first = self._cookie_value(await self._login())
        self.client.session.cookie_jar.clear()
        second = self._cookie_value(await self._login())
        self.client.session.cookie_jar.clear()
        await self.client.post("/api/auth/logout", headers={"Cookie": f"{AUTH_COOKIE_NAME}={first}"})
        self.client.session.cookie_jar.clear()
        still = await self.client.get(
            "/api/control/voice/status", headers={"Cookie": f"{AUTH_COOKIE_NAME}={second}"}
        )
        self.assertEqual(still.status, 200)

    async def test_session_cookie_uses_configured_ttl(self) -> None:
        await self._start({"QANTARA_AUTH_SESSION_TTL_SECONDS": "600"})
        login = await self._login()
        self.assertIn("Max-Age=600", login.headers.get("Set-Cookie", ""))

    async def test_login_failures_are_rate_limited_with_retry_after(self) -> None:
        for attempt in range(10):
            resp = await self._login(token=f"wrong-token-{attempt:02d}-xxxxxxxxxxxx")
            self.assertEqual(resp.status, 401)
        blocked = await self._login(token="wrong-token-final-xxxxxxxxxxxxx")
        self.assertEqual(blocked.status, 429)
        self.assertGreater(int(blocked.headers["Retry-After"]), 0)
        # The correct token is also refused while the client is locked out.
        correct = await self._login()
        self.assertEqual(correct.status, 429)

    async def test_bearer_failures_count_towards_the_limit(self) -> None:
        for attempt in range(10):
            resp = await self.client.get(
                "/api/control/voice/status",
                headers={"Authorization": f"Bearer guess-{attempt:02d}-xxxxxxxxxxxxxxxx"},
            )
            self.assertEqual(resp.status, 401)
        blocked = await self.client.get(
            "/api/control/voice/status", headers={"Authorization": f"Bearer {TOKEN}"}
        )
        self.assertEqual(blocked.status, 429)
        self.assertIn("Retry-After", blocked.headers)

    async def test_repeating_the_same_wrong_credential_does_not_lock_out(self) -> None:
        for _ in range(15):
            resp = await self.client.get(
                "/api/control/voice/status", headers={"Authorization": "Bearer stale-token"}
            )
            self.assertEqual(resp.status, 401)
        ok = await self.client.get(
            "/api/control/voice/status", headers={"Authorization": f"Bearer {TOKEN}"}
        )
        self.assertEqual(ok.status, 200)

    async def test_limiter_is_keyed_per_client(self) -> None:
        for attempt in range(10):
            await self._login(
                token=f"wrong-token-{attempt:02d}-xxxxxxxxxxxx",
                headers={"X-Forwarded-For": "192.168.1.66"},
            )
        blocked = await self._login(headers={"X-Forwarded-For": "192.168.1.66"})
        self.assertEqual(blocked.status, 429)
        other = await self._login(headers={"X-Forwarded-For": "192.168.1.77"})
        self.assertEqual(other.status, 200)

    async def test_unauthenticated_requests_without_credentials_do_not_count(self) -> None:
        for _ in range(20):
            resp = await self.client.get("/api/control/voice/status")
            self.assertEqual(resp.status, 401)
        ok = await self._login()
        self.assertEqual(ok.status, 200)

    async def test_non_ascii_tokens_compare_without_crashing(self) -> None:
        arabic = "مفتاح-سري-طويل-جدا-للاختبار-123"
        await self._start({"QANTARA_AUTH_TOKEN": arabic})
        good = await self._login(token=arabic)
        self.assertEqual(good.status, 200)
        self.client.session.cookie_jar.clear()
        bad = await self._login(token="كلمة-مرور-خاطئة-تماما-للاختبار")
        self.assertEqual(bad.status, 401)
        bearer = await self.client.get(
            "/api/control/voice/status", headers={"Authorization": "Bearer ééééééééééééééééééééééééé"}
        )
        self.assertEqual(bearer.status, 401)


class AuthPrimitiveTests(unittest.TestCase):
    def test_tokens_equal_handles_non_ascii_and_mismatch(self) -> None:
        self.assertTrue(tokens_equal("مفتاح", "مفتاح"))
        self.assertFalse(tokens_equal("مفتاح", "مفتاخ"))
        self.assertFalse(tokens_equal("abc", "مفتاح"))
        self.assertFalse(tokens_equal("\ud800bad", "good"))

    def test_session_store_expires_and_is_bounded(self) -> None:
        now = [0.0]
        store = AuthSessionStore(ttl_seconds=100, max_sessions=3, clock=lambda: now[0])
        sid = store.create()
        self.assertTrue(store.is_valid(sid))
        now[0] = 101.0
        self.assertFalse(store.is_valid(sid))
        ids = [store.create() for _ in range(5)]
        self.assertLessEqual(len(store), 3)
        self.assertFalse(store.is_valid(ids[0]))
        self.assertTrue(store.is_valid(ids[-1]))
        store.revoke(ids[-1])
        self.assertFalse(store.is_valid(ids[-1]))
        self.assertFalse(store.is_valid(""))

    def test_failure_limiter_is_bounded_and_windowed(self) -> None:
        now = [0.0]
        limiter = AuthFailureLimiter(max_failures=3, window_seconds=60, max_clients=4, clock=lambda: now[0])
        for index in range(3):
            limiter.record_failure("a", f"guess-{index}")
        self.assertIsNotNone(limiter.retry_after("a"))
        self.assertIsNone(limiter.retry_after("b"))
        now[0] = 61.0
        self.assertIsNone(limiter.retry_after("a"))
        for client in range(20):
            limiter.record_failure(f"client-{client}", "x")
        self.assertLessEqual(limiter.client_count(), 4)

    def test_session_ttl_env_validation(self) -> None:
        with patch.dict(os.environ, {"QANTARA_AUTH_SESSION_TTL_SECONDS": ""}):
            self.assertEqual(load_auth_session_ttl(), 12 * 60 * 60)
        with patch.dict(os.environ, {"QANTARA_AUTH_SESSION_TTL_SECONDS": "90"}):
            self.assertEqual(load_auth_session_ttl(), 90)
        for bad in ("0", "-5", "abc"):
            with self.subTest(bad=bad), patch.dict(os.environ, {"QANTARA_AUTH_SESSION_TTL_SECONDS": bad}):
                with self.assertRaises(RuntimeError):
                    load_auth_session_ttl()

    def test_configured_token_rejects_whitespace_and_control_characters(self) -> None:
        for bad in ("token with spaces 1234567890", "token\x07control-1234567890123"):
            with self.subTest(bad=bad), patch.dict(os.environ, {"QANTARA_TEST_TOKEN": bad}):
                with self.assertRaises(RuntimeError):
                    load_auth_token("QANTARA_TEST_TOKEN")
        with patch.dict(os.environ, {"QANTARA_TEST_TOKEN": "مفتاح-سري-طويل-جدا-للاختبار-123"}):
            self.assertEqual(load_auth_token("QANTARA_TEST_TOKEN"), "مفتاح-سري-طويل-جدا-للاختبار-123")


# --------------------------------------------------------------------------
# HS-10, HS-K6, CSP/Cache-Control, mesh peers, TTS engine swap
# --------------------------------------------------------------------------


class StatusRedactionTests(_GatewayCase):
    base_env = {"QANTARA_AUTH_TOKEN": TOKEN}

    async def test_status_does_not_expose_mcp_command_line(self) -> None:
        env = {
            "QANTARA_MCP_TRANSPORT": "stdio",
            "QANTARA_MCP_COMMAND": "/usr/bin/npx -y some-mcp-server --api-key sk-live-EXAMPLESECRET",
        }
        with patch.dict(os.environ, env):
            runtime = GatewayRuntime(
                adapter_config=AdapterConfig(kind="mcp_client", name="mcp"),
                stt=FakeSTT(),
                tts=FakeTTS(),
                event_sink=lambda _record: None,
            )
        await self._start({**env, "QANTARA_ADMIN_TOKEN": "admin-secret-token-123456"}, runtime=runtime)
        resp = await self.client.get("/api/status", headers={"Authorization": f"Bearer {TOKEN}"})
        text = await resp.text()
        self.assertEqual(resp.status, 200)
        self.assertNotIn("sk-live-EXAMPLESECRET", text)
        self.assertNotIn("--api-key", text)
        body = await resp.json()
        self.assertEqual(body["agent"], "npx")
        self.assertTrue(body["mcp_command_configured"])

        admin = await self.client.get(
            "/api/admin/runtime", headers={"Authorization": "Bearer admin-secret-token-123456"}
        )
        self.assertNotIn("sk-live-EXAMPLESECRET", await admin.text())


class CatalogAuthTests(_GatewayCase):
    base_env = {"QANTARA_AUTH_TOKEN": TOKEN}

    async def test_tts_and_languages_require_auth_when_token_set(self) -> None:
        for path in ("/api/tts", "/api/languages"):
            with self.subTest(path=path):
                missing = await self.client.get(path)
                self.assertEqual(missing.status, 401)
                allowed = await self.client.get(path, headers={"Authorization": f"Bearer {TOKEN}"})
                self.assertEqual(allowed.status, 200)

    async def test_tts_and_languages_open_without_token(self) -> None:
        await self._start({"QANTARA_AUTH_TOKEN": ""})
        for path in ("/api/tts", "/api/languages"):
            with self.subTest(path=path):
                resp = await self.client.get(path)
                self.assertEqual(resp.status, 200)


class BrowserHeaderTests(_GatewayCase):
    async def test_csp_connect_src_is_same_origin_only(self) -> None:
        resp = await self.client.get("/api/status")
        csp = resp.headers["Content-Security-Policy"]
        self.assertIn("connect-src 'self';", csp)
        self.assertNotIn("ws:", csp)
        self.assertNotIn("wss:", csp)

    async def test_html_pages_are_served_with_no_cache(self) -> None:
        for path in ("/setup/index.html", "/spike/index.html", "/translate/index.html"):
            with self.subTest(path=path):
                resp = await self.client.get(path)
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.headers.get("Cache-Control"), "no-cache")
        for path in ("/", "/setup", "/spike", "/translate"):
            with self.subTest(path=path):
                resp = await self.client.get(path, allow_redirects=False)
                self.assertEqual(resp.headers.get("Cache-Control"), "no-cache")


class MeshPeerFilterTests(_GatewayCase):
    async def test_invalid_peers_are_dropped(self) -> None:
        peers = [
            SimpleNamespace(node_id="kitchen-01", role="full", host="192.168.1.5", port=8770),
            SimpleNamespace(node_id="<img src=x onerror=alert(1)>", role="full", host="192.168.1.6", port=8770),
            SimpleNamespace(node_id="bedroom", role="<script>", host="192.168.1.7", port=8770),
            SimpleNamespace(node_id="x" * 65, role="mic-only", host="192.168.1.8", port=8770),
            SimpleNamespace(node_id="hall.speaker_2", role="speaker-only", host="192.168.1.9", port=8770),
            SimpleNamespace(node_id=None, role="full", host="192.168.1.10", port=8770),
        ]
        self.runtime.mesh_controller = SimpleNamespace(
            registry=SimpleNamespace(list_peers=lambda: peers),
            stop=AsyncMock(),
        )
        resp = await self.client.get("/api/mesh/peers")
        body = await resp.json()
        self.assertEqual([peer["node_id"] for peer in body["peers"]], ["kitchen-01", "hall.speaker_2"])


class _SwapTTS(FakeTTS):
    def __init__(self, kind: str, available: bool = True) -> None:
        self.kind = kind
        self._available = available

    @property
    def available(self) -> bool:
        return self._available


class TTSEngineSwapTests(_GatewayCase):
    async def _configure(self, engine: str):
        with patch.object(http_api, "unload_previous_model", new_callable=AsyncMock):
            return await self.client.post("/api/configure", json={"type": "mock", "tts_engine": engine})

    async def test_selected_engine_is_applied_live(self) -> None:
        built: list[str] = []

        def factory(kind: str | None = None):
            built.append(kind or "")
            return _SwapTTS(kind or "")

        with patch.dict(os.environ, {"QANTARA_TTS_PROVIDER": "piper"}), patch.object(
            http_api, "create_tts_provider", side_effect=factory
        ):
            resp = await self._configure("kokoro")
            body = await resp.json()
            env_after = os.environ.get("QANTARA_TTS_PROVIDER")
        self.assertEqual(resp.status, 200)
        self.assertEqual(built, ["kokoro"])
        self.assertEqual(self.runtime.tts.kind, "kokoro")
        self.assertTrue(body["tts"]["applied"])
        self.assertFalse(body["tts"]["restart_required"])
        self.assertEqual(env_after, "piper")

    async def test_unavailable_engine_keeps_current_and_says_so(self) -> None:
        original = self.runtime.tts
        with patch.object(http_api, "create_tts_provider", return_value=_SwapTTS("chatterbox", available=False)):
            resp = await self._configure("chatterbox")
            body = await resp.json()
        self.assertEqual(resp.status, 200)
        self.assertIs(self.runtime.tts, original)
        self.assertFalse(body["tts"]["applied"])
        self.assertIn("error", body["tts"])

    async def test_factory_error_keeps_current_engine(self) -> None:
        original = self.runtime.tts
        with patch.object(http_api, "create_tts_provider", side_effect=RuntimeError("no model")):
            resp = await self._configure("kokoro")
            body = await resp.json()
        self.assertEqual(resp.status, 200)
        self.assertIs(self.runtime.tts, original)
        self.assertFalse(body["tts"]["applied"])


# --------------------------------------------------------------------------
# S-f: MCP server host normalization
# --------------------------------------------------------------------------


class McpServerHostTests(unittest.TestCase):
    def _import(self):
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        import mcp_server

        return mcp_server

    def test_wildcard_and_empty_hosts_are_not_loopback(self) -> None:
        mod = self._import()
        for host in ("", "0.0.0.0", "::", "[::]", "  "):
            with self.subTest(host=host):
                self.assertFalse(mod._is_loopback_host(host))
        for host in ("127.0.0.1", "::1", "[::1]", "localhost", "127.0.0.2"):
            with self.subTest(host=host):
                self.assertTrue(mod._is_loopback_host(host))

    def test_empty_configured_host_normalizes_to_loopback(self) -> None:
        mod = self._import()
        for value in ("", "   "):
            with self.subTest(value=value), patch.dict(os.environ, {"QANTARA_MCP_SERVER_HOST": value}):
                self.assertEqual(mod._configured_server_host(), "127.0.0.1")
        with patch.dict(os.environ, {"QANTARA_MCP_SERVER_HOST": "0.0.0.0"}):
            self.assertEqual(mod._configured_server_host(), "0.0.0.0")

    def test_wildcard_http_bind_requires_opt_in(self) -> None:
        mod = self._import()
        env = {k: v for k, v in os.environ.items() if k != "QANTARA_MCP_SERVER_ALLOW_INSECURE"}
        with patch.dict(os.environ, env, clear=True):
            for host in ("", "::"):
                with self.subTest(host=host), self.assertRaises(SystemExit):
                    mod._require_safe_http_binding("http", host)


if __name__ == "__main__":
    unittest.main()
