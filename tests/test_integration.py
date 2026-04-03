"""End-to-end integration test: fake backend + gateway + WebSocket client."""

import asyncio
import json
import os
import sys
import struct

import aiohttp
import pytest
import pytest_asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gateway.fake_session_backend.server import create_app as create_backend_app
from gateway.transport_spike.server import create_app as create_gateway_app, PCM_KIND


BACKEND_PORT = 19210
GATEWAY_PORT = 18910


@pytest_asyncio.fixture
async def backend_server():
    """Start the fake session backend on a test port."""
    app = create_backend_app()
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", BACKEND_PORT)
    await site.start()
    yield f"http://127.0.0.1:{BACKEND_PORT}"
    await runner.cleanup()


@pytest_asyncio.fixture
async def gateway_server(backend_server, monkeypatch):
    """Start the gateway pointing at the fake backend."""
    monkeypatch.setenv("QANTARA_ADAPTER", "session_gateway_http")
    monkeypatch.setenv("QANTARA_BACKEND_BASE_URL", backend_server)

    # Reimport with new env
    import importlib
    import gateway.transport_spike.server as srv_mod
    from adapters.factory import create_adapter, load_adapter_config

    config = load_adapter_config()
    adapter = create_adapter(config)
    monkeypatch.setattr(srv_mod, "ADAPTER", adapter)
    monkeypatch.setattr(srv_mod, "ADAPTER_CONFIG", config)

    app = create_gateway_app()
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", GATEWAY_PORT)
    await site.start()
    yield f"http://127.0.0.1:{GATEWAY_PORT}"
    await runner.cleanup()


@pytest.mark.asyncio
async def test_health_check(backend_server):
    """Verify the fake backend health endpoint works."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{backend_server}/health") as resp:
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_session_create_and_turn(backend_server):
    """Verify session creation and turn submission against fake backend."""
    async with aiohttp.ClientSession() as session:
        # Create session
        async with session.post(
            f"{backend_server}/sessions",
            json={"client_context": {"client_name": "test"}},
        ) as resp:
            assert resp.status == 200
            data = await resp.json()
            handle = data["session_handle"]
            assert handle

        # Submit turn
        async with session.post(
            f"{backend_server}/sessions/{handle}/turns",
            json={"transcript": "Hello", "turn_context": {}},
        ) as resp:
            assert resp.status == 200
            data = await resp.json()
            turn_handle = data["turn_handle"]
            assert turn_handle

        # Stream events
        async with session.get(
            f"{backend_server}/sessions/{handle}/turns/{turn_handle}/events",
        ) as resp:
            assert resp.status == 200
            events = []
            async for chunk in resp.content:
                line = chunk.decode().strip()
                if line:
                    events.append(json.loads(line))
            types = [e["type"] for e in events]
            assert "assistant_text_delta" in types
            assert "assistant_text_final" in types
            assert "turn_completed" in types


@pytest.mark.asyncio
async def test_websocket_session_init(gateway_server):
    """Verify WebSocket connection and session_init through the gateway."""
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(f"{gateway_server.replace('http', 'ws')}/ws") as ws:
            # Send session_init
            await ws.send_str(json.dumps({
                "type": "session_init",
                "client_name": "integration-test",
            }))

            # Should receive session_ready
            msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
            assert msg.type == aiohttp.WSMsgType.TEXT
            data = json.loads(msg.data)
            assert data["type"] == "session_ready"
            assert "session_id" in data

            await ws.close()


@pytest.mark.asyncio
async def test_websocket_submit_turn(gateway_server):
    """Verify submitting a text turn through the gateway WebSocket."""
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(f"{gateway_server.replace('http', 'ws')}/ws") as ws:
            await ws.send_str(json.dumps({
                "type": "session_init",
                "client_name": "integration-test",
            }))
            # Drain session_ready
            await asyncio.wait_for(ws.receive(), timeout=5.0)

            # Submit a turn
            await ws.send_str(json.dumps({
                "type": "submit_turn",
                "text": "Hello from the test",
            }))

            # Collect responses until we get assistant_text_final
            messages = []
            deadline = asyncio.get_event_loop().time() + 10.0
            while asyncio.get_event_loop().time() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=3.0)
                except asyncio.TimeoutError:
                    break
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    messages.append(data)
                    if data.get("type") == "assistant_text_final":
                        break
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                    break

            types = [m["type"] for m in messages]
            assert "assistant_text_delta" in types, f"Expected delta in {types}"
            assert "assistant_text_final" in types, f"Expected final in {types}"

            # The final text should reference our input
            final = next(m for m in messages if m["type"] == "assistant_text_final")
            assert "Hello from the test" in final["text"]

            await ws.close()


@pytest.mark.asyncio
async def test_websocket_clear_playback(gateway_server):
    """Verify clear_playback message is acknowledged."""
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(f"{gateway_server.replace('http', 'ws')}/ws") as ws:
            await ws.send_str(json.dumps({"type": "session_init", "client_name": "test"}))
            await asyncio.wait_for(ws.receive(), timeout=5.0)

            await ws.send_str(json.dumps({"type": "clear_playback"}))
            msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
            assert msg.type == aiohttp.WSMsgType.TEXT
            data = json.loads(msg.data)
            assert data["type"] == "playback_cleared"

            await ws.close()
