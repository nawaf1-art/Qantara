from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import aiohttp as _aiohttp
from aiohttp import web

from adapters.base import AdapterConfig
from adapters.factory import create_adapter, load_adapter_config
from gateway.mesh.controller import MeshController, MeshControllerConfig
from gateway.mesh.wyoming_bridge import WyomingBridge
from gateway.transport_spike.common import (
    DEFAULT_SPEECH_RATE,
    MANAGED_BRIDGE_PORT,
    REPO_ROOT,
    SESSION_STORE_TTL_MS,
    TARGET_SAMPLE_RATE,
    utc_now,
)
from providers.factory import create_stt_provider, create_tts_provider

_BRIDGE_SCRIPTS: dict[str, str] = {
    "ollama": os.path.join(REPO_ROOT, "gateway", "ollama_session_backend", "server.py"),
    "openclaw": os.path.join(REPO_ROOT, "gateway", "openclaw_session_backend", "server.py"),
}
LOGGER = logging.getLogger(__name__)

SESSION_STATES = {"idle", "listening", "thinking", "speaking", "interrupted"}


@dataclass(slots=True)
class BackendBinding:
    binding_id: str
    backend_type: str
    adapter_config: AdapterConfig
    adapter: Any
    url: str = ""
    model: str = ""
    agent: str = ""
    managed_bridge_type: str | None = None
    managed_bridge_proc: asyncio.subprocess.Process | None = None
    managed_bridge_port: int | None = None
    health: dict[str, Any] = field(default_factory=lambda: {"status": "unknown", "detail": "health pending"})

    @property
    def adapter_kind(self) -> str:
        return self.adapter.adapter_kind


@dataclass(slots=True)
class SessionSnapshot:
    client_session_id: str
    binding_id: str
    runtime_session_handle: str | None = None
    voice_id: str | None = None
    requested_voice_id: str | None = None
    speech_rate: float = DEFAULT_SPEECH_RATE
    voice_pitch: float = 0.0
    voice_tone: str = "neutral"
    expressiveness: float | None = None
    primary_language: str = "en"
    translation_mode: str | None = None
    translation_source: str | None = None
    translation_target: str | None = None
    client_name: str = "qantara-browser"
    updated_monotonic_ms: float = 0.0


class GatewayRuntime:
    def __init__(
        self,
        adapter_config: AdapterConfig | None = None,
        stt: Any | None = None,
        tts: Any | None = None,
        event_sink: Any | None = None,
    ) -> None:
        self.stt = stt or create_stt_provider()
        self.tts = tts or create_tts_provider()
        self.event_sink = event_sink or self._print_event
        self._bindings: dict[str, BackendBinding] = {}
        self._session_store: dict[str, SessionSnapshot] = {}
        self._active_sessions: dict[str, str] = {}
        self._next_bridge_port = MANAGED_BRIDGE_PORT
        self._configure_lock = asyncio.Lock()
        self.mesh_controller: MeshController | None = None
        self.wyoming_bridge: WyomingBridge | None = None
        # Defaults picked up by new sessions (populated via /api/configure).
        self.default_primary_language: str = "en"
        self.default_translation_mode: str | None = None
        self.default_translation_source: str | None = None
        self.default_translation_target: str | None = None
        self.default_binding_id = self._create_initial_binding(adapter_config or load_adapter_config())

    def _now_ms(self) -> float:
        return round(time.monotonic() * 1000, 3)

    @staticmethod
    def _print_event(record: dict[str, Any]) -> None:
        import json

        print(json.dumps(record), flush=True)

    def _allocate_bridge_port(self) -> int:
        port = self._next_bridge_port
        self._next_bridge_port += 1
        return port

    def _initial_public_type(self, config: AdapterConfig) -> tuple[str, str, str, str]:
        kind = config.kind
        if kind == "mock":
            return "mock", "", "", ""
        if kind == "openai_compatible":
            return (
                "openai_compatible",
                os.environ.get("QANTARA_OPENAI_BASE_URL", "").rstrip("/"),
                os.environ.get("QANTARA_OPENAI_MODEL", ""),
                "",
            )
        if kind == "session_gateway_http":
            return (
                "custom",
                os.environ.get("QANTARA_BACKEND_BASE_URL", "").rstrip("/"),
                os.environ.get("QANTARA_OLLAMA_MODEL", ""),
                os.environ.get("QANTARA_OPENCLAW_AGENT_ID", ""),
            )
        return kind, "", "", ""

    def _create_initial_binding(self, config: AdapterConfig) -> str:
        backend_type, url, model, agent = self._initial_public_type(config)
        binding_id = str(uuid.uuid4())
        self._bindings[binding_id] = BackendBinding(
            binding_id=binding_id,
            backend_type=backend_type,
            adapter_config=config,
            adapter=create_adapter(config),
            url=url,
            model=model,
            agent=agent,
        )
        return binding_id

    def default_binding(self) -> BackendBinding:
        return self._bindings[self.default_binding_id]

    def status_payload(self) -> dict[str, Any]:
        binding = self.default_binding()
        return {
            "type": binding.backend_type,
            "model": binding.model,
            "agent": binding.agent,
            "url": binding.url,
            "adapter_kind": binding.adapter_kind,
            "health": binding.health,
            "managed_bridge": binding.managed_bridge_type,
        }

    def admin_payload(self) -> dict[str, Any]:
        ref_counts: dict[str, int] = {}
        for binding_id in self._active_sessions.values():
            ref_counts[binding_id] = ref_counts.get(binding_id, 0) + 1
        for snapshot in self._session_store.values():
            ref_counts.setdefault(snapshot.binding_id, 0)
        return {
            "default_binding_id": self.default_binding_id,
            "bindings": [
                {
                    "binding_id": binding.binding_id,
                    "backend_type": binding.backend_type,
                    "adapter_kind": binding.adapter_kind,
                    "url": binding.url,
                    "model": binding.model,
                    "agent": binding.agent,
                    "health": binding.health,
                    "managed_bridge": binding.managed_bridge_type,
                    "managed_bridge_port": binding.managed_bridge_port,
                    "reference_count": ref_counts.get(binding.binding_id, 0),
                    "is_default": binding.binding_id == self.default_binding_id,
                }
                for binding in self._bindings.values()
            ],
            "active_sessions": [
                {"session_id": session_id, "binding_id": binding_id}
                for session_id, binding_id in self._active_sessions.items()
            ],
            "stored_sessions": [
                {
                    "client_session_id": snapshot.client_session_id,
                    "binding_id": snapshot.binding_id,
                    "runtime_session_handle": snapshot.runtime_session_handle,
                    "voice_id": snapshot.voice_id,
                    "requested_voice_id": snapshot.requested_voice_id,
                    "speech_rate": snapshot.speech_rate,
                    "voice_pitch": snapshot.voice_pitch,
                    "voice_tone": snapshot.voice_tone,
                }
                for snapshot in self._session_store.values()
            ],
        }

    def snapshot_for(self, client_session_id: str | None) -> SessionSnapshot | None:
        self.prune_session_store()
        if not client_session_id:
            return None
        return self._session_store.get(client_session_id)

    def register_session(self, session: Session) -> None:
        self.prune_session_store()
        snapshot = self.snapshot_for(session.client_session_id)
        # Binding always follows the current default — /api/configure is a
        # global backend switch, so a returning session must land on the
        # newest choice, not a stale snapshot pin.
        binding = self.default_binding()
        if snapshot:
            session.client_name = snapshot.client_name or session.client_name
            session.speech_rate = snapshot.speech_rate
            session.voice_pitch = snapshot.voice_pitch
            session.voice_tone = snapshot.voice_tone
            session.expressiveness = snapshot.expressiveness
            session.primary_language = snapshot.primary_language
            session.translation_mode = snapshot.translation_mode
            session.translation_source = snapshot.translation_source
            session.translation_target = snapshot.translation_target
            # input_language is per-turn — do not restore
            session.requested_voice_id = snapshot.requested_voice_id
            session.voice_id = snapshot.voice_id
            # Only carry over the runtime session handle when the snapshot
            # was taken against the same binding — otherwise the handle is
            # meaningless to the new adapter.
            if snapshot.binding_id == binding.binding_id:
                session.runtime_session_handle = snapshot.runtime_session_handle
        else:
            # No prior snapshot — apply runtime-wide translation defaults.
            session.primary_language = self.default_primary_language
            session.translation_mode = self.default_translation_mode
            session.translation_source = self.default_translation_source
            session.translation_target = self.default_translation_target
        session.binding = binding
        self._active_sessions[session.session_id] = binding.binding_id
        self.save_session_state(session)

    def save_session_state(self, session: Session) -> None:
        if not session.client_session_id or session.binding is None:
            return
        self._session_store[session.client_session_id] = SessionSnapshot(
            client_session_id=session.client_session_id,
            binding_id=session.binding.binding_id,
            runtime_session_handle=session.runtime_session_handle,
            voice_id=session.voice_id,
            requested_voice_id=session.requested_voice_id,
            speech_rate=session.speech_rate,
            voice_pitch=session.voice_pitch,
            voice_tone=session.voice_tone,
            expressiveness=session.expressiveness,
            primary_language=session.primary_language,
            translation_mode=session.translation_mode,
            translation_source=session.translation_source,
            translation_target=session.translation_target,
            client_name=session.client_name,
            updated_monotonic_ms=self._now_ms(),
        )

    def release_session(self, session: Session) -> None:
        self._active_sessions.pop(session.session_id, None)
        self.save_session_state(session)
        self.prune_session_store()

    def prune_session_store(self) -> None:
        now = self._now_ms()
        expired_clients = [
            client_session_id
            for client_session_id, snapshot in self._session_store.items()
            if client_session_id not in self._active_sessions
            and now - snapshot.updated_monotonic_ms > SESSION_STORE_TTL_MS
        ]
        for client_session_id in expired_clients:
            self._session_store.pop(client_session_id, None)
        self._cleanup_unreferenced_bindings()

    async def refresh_binding_health(self, binding: BackendBinding) -> dict[str, Any]:
        try:
            health = await binding.adapter.check_health()
            binding.health = {"status": health.status, "detail": health.detail}
        except Exception as exc:
            binding.health = {"status": "degraded", "detail": str(exc)}
        return binding.health

    async def configure_backend(
        self,
        backend_type: str,
        url: str = "",
        model: str = "",
        agent: str = "",
    ) -> BackendBinding:
        async with self._configure_lock:
            binding = await self._create_binding(backend_type, url=url, model=model, agent=agent)
            self.default_binding_id = binding.binding_id
            self.prune_session_store()
            return binding

    async def _create_binding(
        self,
        backend_type: str,
        url: str = "",
        model: str = "",
        agent: str = "",
    ) -> BackendBinding:
        adapter_kind = "mock"
        env_overrides: dict[str, str] = {}
        managed_bridge_type: str | None = None
        bridge_port: int | None = None
        bridge_proc: asyncio.subprocess.Process | None = None

        if backend_type == "mock":
            adapter_kind = "mock"
            url = ""
        elif backend_type == "ollama":
            adapter_kind = "session_gateway_http"
            managed_bridge_type = "ollama"
            bridge_port = self._allocate_bridge_port()
            if os.environ.get("QANTARA_OLLAMA_BASE_URL"):
                env_overrides["QANTARA_OLLAMA_BASE_URL"] = os.environ["QANTARA_OLLAMA_BASE_URL"]
            if model:
                env_overrides["QANTARA_OLLAMA_MODEL"] = model
            bridge_proc = await self._start_managed_bridge(managed_bridge_type, bridge_port, env_overrides)
            url = f"http://127.0.0.1:{bridge_port}"
        elif backend_type == "openclaw":
            adapter_kind = "session_gateway_http"
            managed_bridge_type = "openclaw"
            bridge_port = self._allocate_bridge_port()
            if agent:
                env_overrides["QANTARA_OPENCLAW_AGENT_ID"] = agent
            bridge_proc = await self._start_managed_bridge(managed_bridge_type, bridge_port, env_overrides)
            url = f"http://127.0.0.1:{bridge_port}"
        elif backend_type in {"openai_compatible", "openai"}:
            if not url:
                raise ValueError("openai_compatible type requires 'url'")
            adapter_kind = "openai_compatible"
        elif backend_type == "custom":
            if not url:
                raise ValueError("custom type requires 'url'")
            adapter_kind = "session_gateway_http"
        else:
            raise ValueError(f"unknown type: {backend_type}")

        config = AdapterConfig(kind=adapter_kind, name=backend_type)
        if adapter_kind in {"session_gateway_http", "openai_compatible"}:
            config.options["base_url"] = url
        if adapter_kind == "openai_compatible" and model:
            config.options["model"] = model

        binding = BackendBinding(
            binding_id=str(uuid.uuid4()),
            backend_type=backend_type,
            adapter_config=config,
            adapter=create_adapter(config),
            url=url,
            model=model,
            agent=agent,
            managed_bridge_type=managed_bridge_type,
            managed_bridge_proc=bridge_proc,
            managed_bridge_port=bridge_port,
        )
        self._bindings[binding.binding_id] = binding

        if managed_bridge_type is not None and bridge_port is not None:
            binding.health = {"status": "starting", "detail": "bridge starting up..."}
            asyncio.create_task(self._background_health_wait(binding))
        else:
            await self.refresh_binding_health(binding)
        return binding

    async def _start_managed_bridge(
        self,
        bridge_type: str,
        port: int,
        env_overrides: dict[str, str] | None = None,
    ) -> asyncio.subprocess.Process | None:
        script = _BRIDGE_SCRIPTS.get(bridge_type)
        if script is None or not os.path.isfile(script):
            return None
        env = os.environ.copy()
        env["QANTARA_REAL_BACKEND_PORT"] = str(port)
        env["QANTARA_REAL_BACKEND_HOST"] = "127.0.0.1"
        if env_overrides:
            env.update(env_overrides)
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            script,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if proc.stdout is not None:
            asyncio.create_task(
                self._log_bridge_stream(bridge_type, proc.stdout, logging.INFO)
            )
        if proc.stderr is not None:
            asyncio.create_task(
                self._log_bridge_stream(bridge_type, proc.stderr, logging.WARNING)
            )
        return proc

    async def _log_bridge_stream(
        self,
        bridge_type: str,
        stream: asyncio.StreamReader,
        level: int,
    ) -> None:
        logger = logging.getLogger(f"qantara.bridge.{bridge_type}")
        try:
            while not stream.at_eof():
                line = await stream.readline()
                if not line:
                    continue
                logger.log(
                    level,
                    "[%s] %s",
                    bridge_type,
                    line.decode("utf-8", errors="replace").rstrip(),
                )
        except Exception as exc:
            LOGGER.debug("bridge log stream ended for %s: %s", bridge_type, exc)

    async def _background_health_wait(self, binding: BackendBinding) -> None:
        if binding.url:
            binding.health = {"status": "starting", "detail": "bridge starting up..."}
            binding.health = await health_check_bridge(binding.url)

    def _cleanup_unreferenced_bindings(self) -> None:
        referenced_binding_ids = {self.default_binding_id, *self._active_sessions.values()}
        referenced_binding_ids.update(snapshot.binding_id for snapshot in self._session_store.values())
        for binding_id in list(self._bindings):
            if binding_id in referenced_binding_ids:
                continue
            binding = self._bindings.pop(binding_id, None)
            if binding and binding.managed_bridge_proc is not None:
                asyncio.create_task(_shutdown_bridge_process(binding.managed_bridge_proc))

    async def start_mesh(self) -> None:
        """Start the mesh controller if QANTARA_MESH_ROLE is set to a
        non-disabled value. Called from the aiohttp app startup."""
        role = os.environ.get("QANTARA_MESH_ROLE", "disabled").strip().lower()
        if role == "disabled":
            return
        if self.mesh_controller is not None:
            return
        node_id = os.environ.get("QANTARA_MESH_NODE_ID", f"qantara-{uuid.uuid4().hex[:8]}")
        mesh_port = int(os.environ.get("QANTARA_MESH_PORT", "8901"))
        service_type = os.environ.get("QANTARA_MESH_SERVICE_TYPE", "_qantara._tcp.local.")
        self.mesh_controller = MeshController(MeshControllerConfig(
            node_id=node_id,
            role=role,
            mesh_port=mesh_port,
            service_type=service_type,
            capabilities={
                "stt": self.stt.available if self.stt else False,
                "tts": self.tts.available if self.tts else False,
            },
        ))
        await self.mesh_controller.start()

    async def stop_mesh(self) -> None:
        if self.mesh_controller is not None:
            await self.mesh_controller.stop()
            self.mesh_controller = None

    async def start_wyoming(self) -> None:
        # Read env at call time (not import time) so tests can patch it
        wyoming_enabled = os.environ.get("QANTARA_WYOMING_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        if not wyoming_enabled:
            return
        if self.wyoming_bridge is not None:
            return
        wyoming_port = int(os.environ.get("QANTARA_WYOMING_PORT", "10700"))
        wyoming_node_name = os.environ.get("QANTARA_WYOMING_NODE_NAME", "qantara")
        wyoming_area = os.environ.get("QANTARA_WYOMING_AREA", "")
        self.wyoming_bridge = WyomingBridge(
            node_name=wyoming_node_name, area=wyoming_area,
            port=wyoming_port, version="0.2.2", has_vad=False,
            runtime=self,
        )
        await self.wyoming_bridge.start()

    async def stop_wyoming(self) -> None:
        if self.wyoming_bridge is not None:
            await self.wyoming_bridge.stop()
            self.wyoming_bridge = None

    async def close(self) -> None:
        await self.stop_wyoming()
        await self.stop_mesh()
        for binding in list(self._bindings.values()):
            if binding.managed_bridge_proc is not None:
                await _shutdown_bridge_process(binding.managed_bridge_proc)


APP_RUNTIME_KEY: web.AppKey[GatewayRuntime] = web.AppKey("runtime", GatewayRuntime)


class Session:
    def __init__(self, websocket: web.WebSocketResponse, runtime: GatewayRuntime) -> None:
        self.websocket = websocket
        self.runtime = runtime
        self.session_id = str(uuid.uuid4())
        self.connection_id = str(uuid.uuid4())
        self.started_monotonic_ms = round(time.monotonic() * 1000, 3)
        self.binding: BackendBinding | None = None
        self.runtime_session_handle = None
        self.turn_id = None
        self.frames_in = 0
        self.frames_out = 0
        self.playback_generation = 0
        self.last_vad_state = "silence"
        self.recent_pcm: list[int] = []
        self.recent_pcm_limit = TARGET_SAMPLE_RATE * 6
        self.last_tts_started_ms: float | None = None
        self.current_turn_handle: str | None = None
        self.current_turn_task: asyncio.Task | None = None
        self.speech_task: asyncio.Task | None = None
        self.speech_generation = 0
        self.turns_completed = 0
        self.client_name = "qantara-browser"
        self.client_session_id = self.session_id
        self.requested_voice_id: str | None = None
        self.voice_id: str | None = runtime.tts.default_voice_id
        self.speech_rate: float = DEFAULT_SPEECH_RATE
        self.voice_pitch: float = 0.0
        self.voice_tone: str = "neutral"
        self.expressiveness: float | None = None
        self.input_language: str | None = None
        self.primary_language: str = "en"
        self.translation_mode: str | None = None
        self.translation_source: str | None = None
        self.translation_target: str | None = None
        self.partial_task: asyncio.Task | None = None
        self.partial_last_text: str = ""
        self.speech_started_ms: float | None = None
        self.state: str = "idle"
        self.state_entered_ms: float = round(time.monotonic() * 1000, 3)
        self.current_turn_buffered_text: str = ""
        self.current_turn_phase: str | None = None
        self.mesh_should_respond: bool = True

    async def set_state(self, new_state: str, reason: str | None = None) -> None:
        if new_state not in SESSION_STATES:
            raise ValueError(f"unknown session state: {new_state!r}")
        previous = self.state
        if previous == new_state:
            return
        now_ms = round(time.monotonic() * 1000, 3)
        ms_in_previous = round(now_ms - self.state_entered_ms, 3)
        self.state = new_state
        self.state_entered_ms = now_ms
        payload = {
            "previous_state": previous,
            "current_state": new_state,
            "ms_in_previous_state": ms_in_previous,
            "reason": reason,
        }
        await self.emit("session_state_changed", "session", payload)
        import json
        if not self.websocket.closed:
            try:
                await self.websocket.send_str(json.dumps({"type": "session_state_changed", **payload}))
            except Exception:
                pass

    async def emit(self, event_name: str, source: str, payload: dict) -> None:
        record = {
            "event_name": event_name,
            "session_id": self.session_id,
            "connection_id": self.connection_id,
            "turn_id": self.turn_id,
            "ts_monotonic_ms": round(time.monotonic() * 1000, 3),
            "ts_wall_time": utc_now(),
            "source": source,
            "payload": payload,
        }
        self.runtime.event_sink(record)


async def health_check_bridge(url: str, retries: int = 30, delay: float = 0.3) -> dict[str, Any]:
    timeout = _aiohttp.ClientTimeout(total=2)
    for _ in range(retries):
        try:
            async with _aiohttp.ClientSession(timeout=timeout) as cs:
                async with cs.get(f"{url}/health") as resp:
                    if resp.status < 500:
                        return {"status": "ok", "detail": "bridge healthy"}
        except Exception:
            pass
        await asyncio.sleep(delay)
    return {"status": "degraded", "detail": "bridge not ready after retries"}


async def _shutdown_bridge_process(proc: asyncio.subprocess.Process) -> None:
    try:
        if proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except TimeoutError:
            proc.kill()
            await proc.wait()
    except ProcessLookupError:
        pass
