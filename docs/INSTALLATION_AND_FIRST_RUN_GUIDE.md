# Installation and First Run

Qantara runs an aiohttp gateway, a browser client, local speech providers, and an operator-selected model or agent backend. It does not require a Qantara cloud account.

## Supported environment

- Python 3.11 or 3.12
- Linux, macOS, or Windows
- Docker Compose v2 for the complete container path
- A current Chromium-family browser for the primary microphone UI

Browser microphone access works on `localhost` or a secure HTTPS origin. Another LAN device therefore needs HTTPS/WSS and certificate trust.

## Choose an installation mode

| Mode | Best for | Network/download behavior |
|---|---|---|
| Docker Compose | Complete local evaluation | Pulls base images, Python dependencies, speech assets, and the configured Ollama model |
| Editable source + `speech` | Native voice development | Installs Python speech dependencies; providers may download models on first use |
| Base wheel/source package | SDK embedding and API/package evaluation | Installs only `aiohttp`; no functioning STT model is included |
| `mcp`, `mesh`, `chatterbox` extras | Optional integrations | Adds only the selected integration dependencies; Chatterbox is resource-heavy |

Qantara is not published to PyPI as of `0.3.1`. GitHub source and GitHub Release artifacts are the supported distribution surfaces.

## Extras reference

This table is the authoritative summary of package extras. “CI” means the
lightweight fake/provider contract suite; CI does not download or execute real
speech models.

| Extra | Purpose and major dependencies | External requirement / installation impact | Platform validation |
|---|---|---|---|
| `speech` | faster-whisper, Kokoro, NumPy, SoundFile | Large ML/runtime downloads. Piper is selectable by Qantara but its executable and voice files are **not** installed by this extra. | Interfaces run in Linux/macOS/Windows CI; real model execution requires local validation. |
| `mcp` | MCP Python SDK 1.28.x | Adds MCP stdio and streamable-HTTP client/server support; an MCP server or command is still operator-supplied. | Contract tests run in Linux/macOS/Windows CI. |
| `mesh` | Zeroconf and Wyoming | Adds discovery, multi-device mesh, and Home Assistant/Wyoming surfaces; LAN authentication and multicast behavior remain deployment-specific. | Unit/regression tests run in Linux/macOS/Windows CI; real LAN topology is not emulated. |
| `chatterbox` | Chatterbox TTS | Resource-heavy Experimental speech stack with model downloads. | Linux is the practical reference environment; other platforms are not claimed as validated. |
| `test` | JSON Schema, MCP, NumPy, Wyoming, Zeroconf | Lightweight repository test dependencies; excludes speech model runtimes. | Used by the full Python 3.11/3.12 CI matrix. |
| `dev` | Build, Ruff, pip-audit, Twine | Exact-version release and quality tools; combine with `test` for contributor setup. | Quality/release job runs on Linux; Ruff and build tooling are cross-platform. |

## Option 1: Docker Compose

```bash
git clone https://github.com/nawaf1-art/Qantara.git
cd Qantara
docker compose up
```

Open [http://localhost:8765](http://localhost:8765). Docker publishes the gateway on loopback unless `QANTARA_DOCKER_BIND` is changed.

The first build is large and depends on registry/model download speed. Keep sufficient disk for container layers, the Python ML stack, and Ollama models. `docker system df` shows current Docker usage.

To require authentication, set a strong token in your local shell or an untracked `.env` file before startup:

```bash
export QANTARA_AUTH_TOKEN="replace-with-a-random-value-of-at-least-24-characters"
docker compose up
```

Do not commit `.env` files or paste real tokens into issue reports.

## Option 2: Native source checkout

```bash
git clone https://github.com/nawaf1-art/Qantara.git
cd Qantara
python3 -m venv .venv
./.venv/bin/pip install -e ".[speech]"
./.venv/bin/python cli.py --backend mock
```

Open [http://localhost:8765](http://localhost:8765).

For development checks without speech models:

```bash
./.venv/bin/pip install -e ".[test,dev]"
python -m unittest discover -s tests -v
ruff check .
```

Windows PowerShell equivalents:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[speech]"
.venv\Scripts\python.exe cli.py --backend mock
```

Piper requires its executable and compatible voice files outside the base package. Kokoro and faster-whisper may download model artifacts on first use. See [Supply chain](SUPPLY_CHAIN.md) for offline preparation.

## Option 3: Tagged package source

Install from the published `v0.3.1` tag:

```bash
pip install "qantara @ git+https://github.com/nawaf1-art/Qantara.git@v0.3.1"
pip install "qantara[speech] @ git+https://github.com/nawaf1-art/Qantara.git@v0.3.1"
```

Use the first command for the base SDK/gateway package or the second for the
native speech dependency set. Piper's executable and voice files remain a
separate operator installation.

The package exposes:

```python
from qantara import VoiceGateway

gateway = VoiceGateway(host="127.0.0.1", port=8765)
gateway.run()
```

The wheel contains the SDK, gateway/adapters/providers, browser assets, identity registry, and public protocols/schemas. The root CLI, MCP server launcher, Docker configuration, repository tests, and operations scripts require a source checkout.

## Configure Ollama

Start Ollama and pull a model you have capacity to run:

```bash
ollama pull qwen3.5:2b
ollama serve
```

Then either select **OpenAI-Compatible** in Qantara’s setup page or launch from source:

```bash
./.venv/bin/python cli.py \
  --backend http://127.0.0.1:11434 \
  --model qwen3.5:2b
```

Qantara accepts the base URL and probes `/v1/models`; do not include `/chat/completions`. See [Ollama compatibility](OLLAMA_COMPATIBILITY.md) for the native session-bridge option.

## Trusted-LAN microphone access

Do not expose Qantara directly to the public internet. For a trusted LAN:

1. Set a strong `QANTARA_AUTH_TOKEN`.
2. Use HTTPS/WSS through the included Caddy configuration or local TLS settings.
3. Trust the local certificate on each client device.
4. Bind only to the interface/network that needs access.

The operations guide is [ops/README.md](../ops/README.md). If you use a custom internal DNS suffix rather than a private IP, single-label host, `.local`, `.lan`, or `.home.arpa`, add that exact hostname to `QANTARA_ALLOWED_HOSTS`. If a reverse proxy intentionally changes browser origin, configure exact origins in `QANTARA_ALLOWED_ORIGINS`.

## Verify the installation

From a source checkout:

```bash
./.venv/bin/python scripts/doctor.py
./.venv/bin/python scripts/smoke_test.py
./.venv/bin/python -m unittest discover -s tests -v
```

For Docker configuration:

```bash
docker compose config
```

## Common first-run problems

- **Microphone blocked:** use `localhost` locally or HTTPS on the LAN, then review browser site permissions.
- **No backend:** start the model server and confirm its private/loopback base URL is reachable from the gateway’s deployment namespace.
- **First turn is slow:** local STT, TTS, and model weights may be downloading or cold-loading.
- **No Piper voice:** install the Piper executable and voice/config pair, or choose another configured TTS provider.
- **Docker cannot reach host Ollama:** container loopback is not host loopback; use the Compose service path or an explicit host gateway appropriate for your platform.

Continue with [Quickstart](QUICKSTART.md), [Configuration](CONFIGURATION.md), or [Troubleshooting](TROUBLESHOOTING.md).
