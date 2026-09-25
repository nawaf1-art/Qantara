# Python SDK

Qantara `0.3.1` exposes an embeddable `VoiceGateway` facade from the base Python package. The base package depends only on `aiohttp`; speech models and optional integrations are separate extras or operator-managed assets.

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

`create_app()` returns the complete Qantara `aiohttp.web.Application` without starting a server. This is useful for an aiohttp runner, test harness, or operator-controlled serving lifecycle.

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
| `host` | Bind interface used by `run()`; loopback is the safe default |
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

The following remain source-checkout surfaces in `0.3.1`:

- `cli.py`
- `mcp_server.py`
- Docker and operations files
- repository tests and development scripts

The base wheel does not include a working STT model, Piper executable/voice files, Ollama model, or agent runtime.

## Security boundary

Embedding Qantara does not make it safe for direct public-internet exposure. Keep loopback defaults unless authentication, HTTPS/WSS, network policy, and certificate trust are deliberately configured. Any backend selected by the operator receives the text turns sent through its adapter.
