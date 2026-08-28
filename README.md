# Qantara

Local-first, real-time voice for local LLMs and agent backends.

Current source version: `0.3.1`

Qantara is a browser-first voice gateway. It captures microphone audio, handles speech recognition, turn-taking, interruption, speech synthesis, and playback, then sends text turns through a small adapter boundary to Ollama, an OpenAI-compatible server, MCP, or another local agent backend.

Qantara is the voice layer, not an agent framework. Your backend continues to own reasoning, tools, memory, and application behavior.

> Project status: **Beta**. The core local browser-to-gateway path is tested on Python 3.11 and 3.12 across Linux, macOS, and Windows. Optional integrations remain Experimental where noted.

## Why Qantara

- Local-first by default: no Qantara-operated cloud service and no telemetry.
- Full-duplex voice loop with VAD, endpointing, auto-submit, and barge-in.
- A clean adapter contract for local model servers and agent runtimes.
- Local STT/TTS provider boundaries with English and Arabic voice routing.
- Browser client built with vanilla JavaScript and WebAudio; no frontend build step.
- HTTP Voice API for applications that do not need the browser transport.
- Loopback-safe defaults with an authenticated HTTPS/WSS path for trusted LAN use.

## First run

The most complete first run is Docker Compose:

```bash
git clone https://github.com/nawaf1-art/Qantara.git
cd Qantara
docker compose up
```

Open [http://localhost:8765](http://localhost:8765), choose **Demo** to inspect the UI or configure the local Ollama service started by Compose, then allow microphone access.

The first build downloads a large local speech stack and an Ollama model. See the [installation guide](docs/INSTALLATION_AND_FIRST_RUN_GUIDE.md) for disk, browser, and native-install requirements.

### Native source install

```bash
git clone https://github.com/nawaf1-art/Qantara.git
cd Qantara
python3 -m venv .venv
./.venv/bin/pip install -e ".[speech]"
./.venv/bin/python cli.py --backend mock
```

Open [http://localhost:8765](http://localhost:8765). To use Ollama directly, start Ollama and run:

```bash
ollama pull qwen3.5:2b
./.venv/bin/python cli.py --backend http://127.0.0.1:11434 --model qwen3.5:2b
```

Windows PowerShell uses `.venv\Scripts\python.exe` in place of `./.venv/bin/python`.

## Installation choices

| Mode | Intended use | Includes |
|---|---|---|
| Docker Compose | Complete local evaluation | Gateway, speech dependencies, Ollama bridge, pinned Ollama release line |
| Source + `.[speech]` | Native browser voice development | Gateway, CLI, faster-whisper, Kokoro dependencies; Piper executable/voices remain operator-supplied |
| Source + `.[mcp]` | MCP client/server development | MCP adapter and voice-control server dependencies |
| Source + `.[mesh]` | Multi-device and Home Assistant labs | Zeroconf mesh and Wyoming dependencies |
| GitHub Release wheel | Reproducible SDK/package evaluation | `aiohttp`, Python SDK, gateway assets; optional extras available, no model assets |
| `.[chatterbox]` | Expressive TTS experiments | Optional Chatterbox runtime; resource-heavy and Experimental |

The [installation guide](docs/INSTALLATION_AND_FIRST_RUN_GUIDE.md#extras-reference) is the authoritative extras/platform matrix.

Qantara is not published to PyPI in this release line. The published `v0.3.1` GitHub Release contains the validated wheel, source archive, `SHA256SUMS`, SPDX SBOM, and `release-validation.json`. Verify the downloaded artifact, then install the wheel directly:

```bash
python -m pip install \
  "qantara @ https://github.com/nawaf1-art/Qantara/releases/download/v0.3.1/qantara-0.3.1-py3-none-any.whl"

python -m pip install \
  "qantara[speech] @ https://github.com/nawaf1-art/Qantara/releases/download/v0.3.1/qantara-0.3.1-py3-none-any.whl"
```

A tagged source install remains available when a source build is specifically desired:

```bash
pip install "qantara @ git+https://github.com/nawaf1-art/Qantara.git@v0.3.1"
pip install "qantara[speech] @ git+https://github.com/nawaf1-art/Qantara.git@v0.3.1"
```

The wheel exposes `qantara.VoiceGateway`, gateway/adapters/providers, browser and identity assets, and public protocol/schema resources. Root utilities such as `cli.py`, `mcp_server.py`, Docker files, operations examples, tests, and development scripts require a source checkout.

### Python SDK

```python
from qantara import VoiceGateway

gateway = VoiceGateway(host="127.0.0.1", port=8765)
gateway.run()
```

See the [Python SDK reference](docs/PYTHON_SDK.md) for application construction, configuration timing, and package boundaries.

## How it fits together

```text
Browser microphone/speaker
          |
          | WebSocket: PCM16 mono 16 kHz + control events
          v
Qantara aiohttp gateway
  VAD · endpointing · STT · session state · barge-in · TTS
          |
          | RuntimeAdapter session contract
          v
Local model or agent backend
  OpenAI-compatible · Ollama bridge · MCP · OpenClaw · custom · mock
```

The gateway owns the voice loop. Adapters implement five explicit operations: start/resume a session, submit a user turn, stream assistant output, cancel a turn, and report health. See [Architecture](ARCHITECTURE.md), the [adapter contract](adapters/CONTRACT.md), and [agent protocol v1](protocols/agent.md).

## Supported surfaces

| Surface | Status | Notes |
|---|---|---|
| Browser WebSocket voice path | Beta | Primary headset-first interface; PCM16 mono 16 kHz |
| VAD, endpointing, auto-submit, barge-in | Beta | Covered by lifecycle and interruption tests |
| Source-checkout CLI | Beta | High-level backend/YAML launcher; environment variables override flags |
| OpenAI-compatible adapter | Beta | Local `/v1/chat/completions` servers, including Ollama-compatible mode |
| Session HTTP adapter | Beta | Custom local backends implementing Qantara's session contract |
| Ollama session bridge | Beta | Native Ollama streaming contract path |
| Piper and Kokoro TTS | Beta | Local engines; model/runtime installation varies |
| faster-whisper STT | Beta | Local model download on first use unless pre-cached |
| Voice-as-API | Beta | Speak, transcribe, and converse endpoints |
| Python SDK | Beta | Embeddable aiohttp application; base wheel excludes speech models |
| MCP client and voice server | Experimental | Stdio and streamable HTTP paths |
| OpenClaw bridge | Experimental | Advanced, host-side optional integration |
| Mesh and Wyoming satellite | Experimental | Validate authentication and LAN behavior for each deployment |
| Chatterbox TTS | Experimental | Optional, heavier expressive-speech path |

The canonical status vocabulary is **Beta**, **Experimental**, **Planned**, and **Deprecated**. See the full [feature matrix](docs/FEATURES.md).

## Voice API

Qantara also exposes one-shot local HTTP endpoints:

```text
POST /api/v1/speak       JSON text -> WAV or PCM16
POST /api/v1/transcribe  WAV or raw PCM16 -> transcript metadata
POST /api/v1/converse    JSON text -> Server-Sent Events
```

When `QANTARA_AUTH_TOKEN` is set, use `Authorization: Bearer <token>`. Request bodies, text, generated output, and stream lines have explicit size/time bounds. See [Voice API](docs/VOICE_API.md) for examples.

## Security and privacy boundary

Qantara is designed for loopback or a trusted LAN, not direct public-internet exposure.

- Native and Docker entry points bind to loopback by default.
- Set a strong `QANTARA_AUTH_TOKEN` before LAN exposure; use a separate `QANTARA_ADMIN_TOKEN` for administrative diagnostics.
- Browser microphone access from another device requires HTTPS/WSS. Follow the documented Caddy/local-certificate path.
- Browser-origin checks compare host and port. Host-header checks allow loopback, private IPs, and conventional LAN names; custom internal DNS names can be added with `QANTARA_ALLOWED_HOSTS`.
- Browser backend setup accepts only loopback/private targets and pins resolved IPs. Runtime configuration outside that UI remains operator-controlled.
- Default gateway event logs retain operational metadata but redact transcripts, model text, tool parameters, and credentials. Bridge output logging is opt-in with `QANTARA_BRIDGE_LOG_OUTPUT=1`.
- Session transcripts and histories are bounded in memory. The browser keeps non-secret preferences and session identifiers in local storage.
- Qantara has no telemetry. Speech/model providers may download artifacts, and any backend you configure receives the text turns sent to it.

Read [Privacy](docs/PRIVACY.md), [Security](SECURITY.md), and [Supply chain](docs/SUPPLY_CHAIN.md) before a LAN or sensitive-data deployment.

## Configuration

Configuration uses `QANTARA_` environment variables, an optional YAML file, CLI flags, and runtime setup choices. For CLI startup values, the implemented precedence is environment variables over explicit flags, then YAML, then defaults.

Do not put tokens in command history, screenshots, issue reports, or checked-in files. See [Configuration](docs/CONFIGURATION.md) and the [CLI reference](docs/CLI.md).

## Validation

For a source checkout:

```bash
python -m pip install ".[test,dev]"
python -m unittest discover -s tests -v
ruff check .
python scripts/check_release_consistency.py
python scripts/check_docs_links.py
python scripts/check_docs_consistency.py
python -m build
python -m twine check dist/*
python scripts/check_package_artifacts.py dist/*
```

CI runs the unit suite on Python 3.11/3.12 across Ubuntu, macOS, and Windows. It separately checks lint, compilation, release/documentation consistency, wheel/sdist contents, clean artifact installs, dependency changes, and the base dependency set.

Published releases are prepared manually from an existing owner-selected tag. The workflow rebuilds once, repeats release checks, generates checksums and an SPDX SBOM, records validation evidence, creates provenance attestations, and opens a draft GitHub Release. It does not publish to PyPI.

## Documentation

- [Documentation index](docs/README.md) and [governance/completeness contract](docs/DOCUMENTATION_GOVERNANCE.md)
- [Quickstart](docs/QUICKSTART.md)
- [Installation and first run](docs/INSTALLATION_AND_FIRST_RUN_GUIDE.md)
- [CLI launcher](docs/CLI.md) and [configuration](docs/CONFIGURATION.md)
- [Python SDK](docs/PYTHON_SDK.md) and [Voice API](docs/VOICE_API.md)
- [Architecture and trust boundaries](ARCHITECTURE.md)
- [Ollama compatibility](docs/OLLAMA_COMPATIBILITY.md)
- [MCP](docs/MCP.md)
- [Mesh](docs/MESH.md) and [Home Assistant/Wyoming](docs/HOMEASSISTANT.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Release process](docs/RELEASE_PROCESS.md)
- [Roadmap](ROADMAP.md) and [changelog](CHANGELOG.md)

## Contributing

Small fixes, tests, provider/adapter improvements, and documentation corrections are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md), use the issue templates, and discuss architecture changes before implementation. Security reports belong in GitHub's private vulnerability-reporting flow, not a public issue.

Qantara is licensed under [Apache 2.0](LICENSE).
