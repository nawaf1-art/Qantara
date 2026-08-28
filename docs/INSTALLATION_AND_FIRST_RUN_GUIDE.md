# Installation and First Run

Qantara runs an aiohttp gateway, browser client, local speech providers, and an operator-selected model or agent backend. It does not require a Qantara cloud account.

## Supported environment

- Python 3.11 or 3.12
- Linux, macOS, or Windows
- Docker Compose v2 for the complete container path
- A current Chromium-family browser for the primary microphone UI

Browser microphone access works on `localhost` or a secure HTTPS origin. Another LAN device therefore needs HTTPS/WSS and certificate trust.

## Distribution status

Qantara `0.3.1` is published as a GitHub Release, not on PyPI. The release contains:

- `qantara-0.3.1-py3-none-any.whl`
- `qantara-0.3.1.tar.gz`
- `SHA256SUMS`
- `qantara-0.3.1.spdx.json`
- `release-validation.json`
- GitHub provenance attestations

Use Docker or a source checkout for the complete CLI/operations experience. Use the wheel for the SDK, package, embedded gateway, and optional-extra evaluation.

## Choose an installation mode

| Mode | Best for | Network/download behavior |
|---|---|---|
| Docker Compose | Complete local evaluation | Pulls base images, Python dependencies, speech assets, and the configured Ollama model |
| Editable source + `speech` | Native voice development | Installs Python speech dependencies; providers may download models on first use |
| GitHub Release wheel | Reproducible SDK/package evaluation | Base install adds only `aiohttp`; selected extras add their dependencies; no model assets are bundled |
| Tagged source package | Auditable source-based package install | Builds from the immutable tag; requires Git/build tooling |
| `mcp`, `mesh`, `chatterbox` extras | Optional integrations | Adds only the selected integration dependencies; Chatterbox is resource-heavy |

## Extras reference

“CI” means the lightweight fake/provider contract suite; CI does not download or execute real speech models.

| Extra | Purpose and major dependencies | External requirement / installation impact | Platform validation |
|---|---|---|---|
| `speech` | faster-whisper, Kokoro, NumPy, SoundFile | Large ML/runtime downloads. Piper is selectable but its executable/module and voice files are **not** installed by this extra. | Interfaces run in Linux/macOS/Windows CI; real model execution requires local validation. |
| `mcp` | MCP Python SDK 1.28.x | Adds MCP stdio and streamable-HTTP client/server support; an MCP server or command is still operator-supplied. | Contract tests run in Linux/macOS/Windows CI. |
| `mesh` | Zeroconf and Wyoming | Adds discovery, multi-device mesh, and Home Assistant/Wyoming surfaces; LAN authentication and multicast remain deployment-specific. | Unit/regression tests run in Linux/macOS/Windows CI; real LAN topology is not emulated. |
| `chatterbox` | Chatterbox TTS | Resource-heavy Experimental speech stack with model downloads. | Linux is the practical reference environment; other platforms are not claimed as validated. |
| `test` | JSON Schema, MCP, NumPy, Wyoming, Zeroconf | Lightweight repository test dependencies; excludes speech model runtimes. | Used by the full Python 3.11/3.12 CI matrix. |
| `dev` | Build, Ruff, pip-audit, Twine | Exact-version release and quality tools; combine with `test` for contributor setup. | Quality/release job runs on Linux; tools are generally cross-platform. |

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
./.venv/bin/python -m unittest discover -s tests -v
ruff check .
```

Windows PowerShell equivalents:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[speech]"
.venv\Scripts\python.exe cli.py --backend mock
```

Piper requires its module/executable and compatible voice files outside the package extras. Kokoro and faster-whisper may download model artifacts on first use. See [Supply chain](SUPPLY_CHAIN.md) for offline preparation.

## Option 3: Published GitHub Release wheel

Download the wheel and `SHA256SUMS` from the `v0.3.1` release. Verify the wheel checksum before installation. The release validation file records the source commit used to build the attached artifacts.

Install the base wheel directly:

```bash
python -m pip install \
  "qantara @ https://github.com/nawaf1-art/Qantara/releases/download/v0.3.1/qantara-0.3.1-py3-none-any.whl"
```

Install the same validated wheel with speech dependencies:

```bash
python -m pip install \
  "qantara[speech] @ https://github.com/nawaf1-art/Qantara/releases/download/v0.3.1/qantara-0.3.1-py3-none-any.whl"
```

The package exposes:

```python
from qantara import VoiceGateway

VoiceGateway(host="127.0.0.1", port=8765).run()
```

The wheel contains the SDK, gateway/adapters/providers, browser assets, identity registry, and public protocols/schemas. It does **not** install `cli.py`, `mcp_server.py`, Docker/operations files, tests, or development scripts as command-line surfaces. See [Python SDK](PYTHON_SDK.md).

## Option 4: Tagged package source

Use the immutable tag when a source build is specifically required:

```bash
python -m pip install \
  "qantara @ git+https://github.com/nawaf1-art/Qantara.git@v0.3.1"

python -m pip install \
  "qantara[speech] @ git+https://github.com/nawaf1-art/Qantara.git@v0.3.1"
```

This installs the Python package from source; it is not equivalent to cloning the repository for root scripts and operations files.

## Configure Ollama

Start Ollama and pull a model you have capacity to run:

```bash
ollama pull qwen3.5:2b
ollama serve
```

From a source checkout, use the direct OpenAI-compatible path:

```bash
./.venv/bin/python cli.py \
  --backend http://127.0.0.1:11434 \
  --model qwen3.5:2b
```

Qantara accepts the base URL and probes `/v1/models`; do not append `/chat/completions`. See [Ollama compatibility](OLLAMA_COMPATIBILITY.md) for the managed/native session-bridge option.

## Trusted-LAN microphone access

Do not expose Qantara directly to the public internet. For a trusted LAN:

1. Set a strong `QANTARA_AUTH_TOKEN`.
2. Use HTTPS/WSS through Caddy or local TLS settings.
3. Trust the local certificate on each client device.
4. Bind only to the interface/network that needs access.

Follow [`ops/README.md`](../ops/README.md). If a custom internal DNS suffix falls outside private IPs, single-label names, `.local`, `.lan`, or `.home.arpa`, add the exact hostname to `QANTARA_ALLOWED_HOSTS`. If a deliberate proxy topology changes browser origin, configure exact origins in `QANTARA_ALLOWED_ORIGINS`.

## Verify the installation

From a source checkout:

```bash
./.venv/bin/python scripts/doctor.py
./.venv/bin/python scripts/smoke_test.py
./.venv/bin/python scripts/check_release_consistency.py
./.venv/bin/python scripts/check_docs_links.py
./.venv/bin/python scripts/check_docs_consistency.py
./.venv/bin/python -m unittest discover -s tests -v
```

For Docker configuration:

```bash
docker compose config
```

For the installed wheel:

```bash
python -c "import qantara; print(qantara.__version__)"
```

Expected release version: `0.3.1`.

## Common first-run problems

- **Microphone blocked:** use `localhost` locally or HTTPS on the LAN, then review browser site permissions.
- **No backend:** start the model server and confirm its private/loopback base URL is reachable from the gateway's deployment namespace.
- **First turn is slow:** local STT, TTS, and model weights may be downloading or cold-loading.
- **No Piper voice:** install Piper and a voice/config pair, or select another configured TTS provider.
- **Docker cannot reach host Ollama:** container loopback is not host loopback; use the Compose service path or an explicit host gateway appropriate for the platform.
- **A CLI flag appears ignored:** an existing environment variable has higher startup precedence; see [CLI](CLI.md).

Continue with [Quickstart](QUICKSTART.md), [Configuration](CONFIGURATION.md), or [Troubleshooting](TROUBLESHOOTING.md).
