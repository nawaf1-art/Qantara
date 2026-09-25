# Python SDK

Qantara `0.4.0` exposes an embeddable `VoiceGateway` facade and an async `VoiceControl` client from the base Python package. The base package depends only on `aiohttp`; speech models and optional integrations are separate extras or operator-managed assets.

Qantara is not published to PyPI in this release line. Install the validated GitHub Release wheel or a tagged source reference as described in the [installation guide](INSTALLATION_AND_FIRST_RUN_GUIDE.md).

## Basic use

```python
from qantara import VoiceGateway

VoiceGateway(host="127.0.0.1", port=8765).run()
```

`run()` starts the aiohttp application and blocks until shutdown. When `QANTARA_TLS_CERT` and `QANTARA_TLS_KEY` are set, it uses the same TLS behavior as the standalone gateway.

## Build the aiohttp application

```python
from aiohttp import web
from qantara import VoiceGateway

app = VoiceGateway().create_app()
web.run_app(app, host="127.0.0.1", port=8765)
```

`create_app()` returns the complete Qantara `aiohttp.web.Application` without starting a server. This is useful for an aiohttp runner, test harness, or operator-controlled serving lifecycle. It passes the constructor's `host` to the gateway (`create_app(runtime, *, bind_host=...)` in `gateway.transport_spike.server`), so the no-token warning below reflects the interface you intend to bind.

## Constructor

```python
VoiceGateway(
    host="127.0.0.1",
    port=8765,
    runtime=None,
)
```

| Argument | Meaning |
|---|---|
| `host` | Bind interface used by `run()`; loopback is the safe default. A non-loopback host without `QANTARA_AUTH_TOKEN` logs a warning, and LAN clients get HTTP 421 until a token is set |
| `port` | TCP port used by `run()` |
| `runtime` | Optional pre-built gateway runtime for advanced embedding/testing |

The runtime injection surface is pre-1.0 and should be treated as advanced. Normal integrations should configure adapters and providers through documented `QANTARA_` environment variables.

## Configuration timing

The gateway reads many settings while the application/runtime is created. Set environment variables before constructing `VoiceGateway` or calling `create_app()`.

```python
import os

os.environ["QANTARA_ADAPTER"] = "openai_compatible"
os.environ["QANTARA_OPENAI_BASE_URL"] = "http://127.0.0.1:11434"
os.environ["QANTARA_OPENAI_MODEL"] = "qwen3.5:2b"

from qantara import VoiceGateway

VoiceGateway().run()
```

See [Configuration](CONFIGURATION.md) for the complete reference and [Architecture](../ARCHITECTURE.md) for ownership boundaries.

## Package boundary

The wheel contains:

- `qantara.VoiceGateway`
- gateway, adapter, provider, and discovery packages
- browser and identity assets
- public protocol and schema resources
- `qantara.control.VoiceControl`
- the `qantara` launcher and `qantara doctor` / `qantara-doctor` console scripts

The following remain source-checkout surfaces in `0.4.0`:

- the root `cli.py` shim (the same launcher as the `qantara` command)
- `mcp_server.py`
- Docker and operations files
- lock files, repository tests, and development scripts

The base wheel does not include a working STT model, the `piper-tts` package or Piper voice files, Ollama model, or agent runtime.

## Voice control client

`qantara.control.VoiceControl` is a small async client for a running gateway's `/api/control/voice/*` endpoints. It drives an already-connected browser voice session; it cannot capture a microphone by itself.

```python
import asyncio
from qantara.control import VoiceControl

async def main() -> None:
    async with VoiceControl("http://127.0.0.1:8765", token="...") as voice:
        print(await voice.status())
        await voice.speak("Hello from Python", interrupt=True)
        await voice.interrupt()

asyncio.run(main())
```

| Method | Endpoint | Notes |
|---|---|---|
| `status()` | `GET /api/control/voice/status` | Active sessions and their state |
| `speak(text, voice_id=None, interrupt=False, *, session_id=None, client_session_id=None)` | `POST /api/control/voice/speak` | Queues text for playback; `interrupt=True` cancels current speech first. Text is limited to `QANTARA_CONTROL_MAX_SPEAK_CHARS` (4,000) |
| `interrupt(*, session_id=None, client_session_id=None)` | `POST /api/control/voice/interrupt` | Stops playback and cancels the active turn |

`token` is the gateway's `QANTARA_AUTH_TOKEN` (optional for a loopback gateway without one). When several browser sessions are active, pass `session_id` or `client_session_id`. The client never uses proxy environment variables, does not follow redirects, refuses URLs with embedded credentials, and raises `VoiceControlError` (with `status` and `payload`) for gateway errors. Pass `session=` to reuse your own `aiohttp.ClientSession`.

## Security boundary

Embedding Qantara does not make it safe for direct public-internet exposure. Keep loopback defaults unless authentication, HTTPS/WSS, network policy, and certificate trust are deliberately configured. Any backend selected by the operator receives the text turns sent through its adapter.
