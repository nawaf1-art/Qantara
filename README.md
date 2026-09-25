# Qantara

Local-first, real-time voice for local LLMs and agent backends.

Current source version: `0.4.0`

Qantara is a browser-first voice gateway. It captures microphone audio, handles speech recognition, turn-taking, interruption, speech synthesis, and playback, then sends text turns through a small adapter boundary to Ollama, an OpenAI-compatible server, MCP, or another local agent backend.

Qantara is the voice layer, not an agent framework. Your backend continues to own reasoning, tools, memory, and application behavior.

> Project status: **Beta**. The core local browser-to-gateway path is unit-tested on Python 3.11–3.14 across Linux, macOS, and Windows; the full local speech stack (Kokoro) needs Python 3.11 or 3.12. Optional integrations remain Experimental where noted.

## Why Qantara

- Local-first by default: no Qantara-operated cloud service and no telemetry.
- Full-duplex voice loop with VAD, endpointing, auto-submit, and barge-in.
- A clean adapter contract for local model servers and agent runtimes.
- Local STT/TTS provider boundaries with per-language voice routing: by default Kokoro speaks English, Spanish, and French and Piper speaks Arabic when both are installed.
- Browser client built with vanilla JavaScript and WebAudio; no frontend build step.
- HTTP Voice API for applications that do not need the browser transport.
- Loopback-safe defaults: without an auth token the gateway answers only loopback requests; an authenticated HTTPS/WSS path covers trusted LAN use.

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

Use Python 3.12 (or 3.11): Kokoro does not install on Python 3.13+. On a CPU-only Linux machine, run `./.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu` after creating the venv and before installing `.[speech]`, to avoid several GB of CUDA packages.

```bash
git clone https://github.com/nawaf1-art/Qantara.git
cd Qantara
python3.12 -m venv .venv
./.venv/bin/pip install -e ".[speech]"
./.venv/bin/python -m spacy download en_core_web_sm
./.venv/bin/qantara doctor
./.venv/bin/qantara --backend mock
```

The spaCy model is required by Kokoro's English pipeline; installing it up front stops Kokoro from trying to download it at first use. For Arabic speech output, also install Piper (`./.venv/bin/pip install piper-tts`) and fetch the pinned, checksum-verified voices with `scripts/fetch_piper_voices.sh`. The [installation guide](docs/INSTALLATION_AND_FIRST_RUN_GUIDE.md#option-2-native-source-checkout) has the details.

Open [http://localhost:8765](http://localhost:8765). To use Ollama directly, start Ollama and run:

```bash
ollama pull qwen3.5:2b
./.venv/bin/qantara --backend http://127.0.0.1:11434 --model qwen3.5:2b
```

`./.venv/bin/python cli.py ...` is equivalent from a source checkout. Windows PowerShell uses `py -3.12 -m venv .venv` and `.venv\Scripts\qantara.exe`.

## Installation choices

| Mode | Intended use | Includes |
|---|---|---|
| Docker Compose | Complete local evaluation | Gateway, faster-whisper and Kokoro speech stack (no Piper, so no Arabic speech output), Ollama bridge, pinned Ollama release line |
| Source + `.[speech]` | Native browser voice development | Gateway, `qantara` CLI, faster-whisper, Kokoro (Python 3.11/3.12 only); Piper runtime/voices remain operator-supplied |
| Source + `.[mcp]` | MCP client/server development | MCP adapter and voice-control server dependencies |
| Source + `.[mesh]` | Multi-device labs | Zeroconf mesh discovery |
| GitHub Release wheel | Reproducible SDK/package evaluation | `aiohttp`, Python SDK, `qantara` launcher, gateway assets; optional extras available, no model assets |
| `.[chatterbox]` | Expressive TTS experiments | Optional Chatterbox runtime; resource-heavy and Experimental |

The [installation guide](docs/INSTALLATION_AND_FIRST_RUN_GUIDE.md#extras-reference) is the authoritative extras/platform matrix.

Qantara is not published to PyPI in this release line. `0.4.0` is the current source version; its `v0.4.0` GitHub Release is prepared by the owner-controlled release process and, once published, contains the validated wheel, source archive, `SHA256SUMS`, SPDX SBOM, and `release-validation.json`. Until then, the latest published GitHub Release is `v0.3.1`. Verify the downloaded artifact, then install the wheel directly:

```bash
python -m pip install \
  "qantara @ https://github.com/nawaf1-art/Qantara/releases/download/v0.4.0/qantara-0.4.0-py3-none-any.whl"

python -m pip install \
  "qantara[speech] @ https://github.com/nawaf1-art/Qantara/releases/download/v0.4.0/qantara-0.4.0-py3-none-any.whl"
```

A tagged source install remains available when a source build is specifically desired:

```bash
pip install "qantara @ git+https://github.com/nawaf1-art/Qantara.git@v0.4.0"
pip install "qantara[speech] @ git+https://github.com/nawaf1-art/Qantara.git@v0.4.0"
```

The wheel exposes `qantara.VoiceGateway`, the `qantara.control.VoiceControl` client, the `qantara` / `qantara doctor` / `qantara-doctor` commands, gateway/adapters/providers, browser and identity assets, and public protocol/schema resources. `mcp_server.py`, Docker files, operations examples, lock files, tests, and development scripts require a source checkout.

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
| `qantara` CLI launcher | Beta | Backend/YAML launcher and `qantara doctor`; explicit flags override environment variables |
| OpenAI-compatible adapter | Beta | Local `/v1/chat/completions` servers, including Ollama-compatible mode |
| Session HTTP adapter | Beta | Custom local backends implementing Qantara's session contract |
| Ollama session bridge | Beta | Native Ollama streaming contract path |
| Piper and Kokoro TTS | Beta | Local engines; default `auto` selection routes Kokoro (en/es/fr) and Piper (ar) when both are installed |
| faster-whisper STT | Beta | Local model download on first use unless pre-cached |
| Voice-as-API | Beta | Speak, transcribe, and converse endpoints |
| Python SDK | Beta | Embeddable aiohttp application; base wheel excludes speech models |
| MCP client and voice server | Experimental | Stdio and streamable HTTP paths |
| OpenClaw bridge | Experimental | Advanced, host-side optional integration |
| Multi-device mesh | Experimental | LAN binds require `QANTARA_MESH_TOKEN`; not yet validated across physical devices |
| Chatterbox TTS | Experimental | Optional, heavier expressive-speech path |

The canonical status vocabulary is **Beta**, **Experimental**, **Planned**, and **Deprecated**. See the full [feature matrix](docs/FEATURES.md).

## Voice API

Qantara also exposes one-shot local HTTP endpoints:

```text
POST /api/v1/speak       JSON text -> WAV or PCM16
POST /api/v1/transcribe  WAV or raw PCM16 -> transcript metadata
POST /api/v1/converse    JSON text -> Server-Sent Events
```

When `QANTARA_AUTH_TOKEN` is set, use `Authorization: Bearer <token>`. Request bodies, text, generated output, and stream lines have explicit size/time bounds. `?format=pcm` responses use the content type `audio/pcm;rate=N;channels=1;encoding=signed-int;bits=16;endian=little`. See [Voice API](docs/VOICE_API.md) for examples.

## Security and privacy boundary

Qantara is designed for loopback or a trusted LAN, not direct public-internet exposure.

- Native and Docker entry points bind to loopback by default.
- Without `QANTARA_AUTH_TOKEN` the gateway fails closed: it answers only requests whose `Host` is `localhost`, a loopback address, or a `QANTARA_ALLOWED_HOSTS` entry. Every other request gets HTTP 421 with `code: "lan_access_requires_token"`, including a reverse proxy that forwards `Host: qantara.local` and Docker accessed by LAN IP.
- Set a strong `QANTARA_AUTH_TOKEN` before LAN exposure; use a separate `QANTARA_ADMIN_TOKEN` for administrative diagnostics. Browser logins are server-side sessions (12 h by default) that logout revokes, and repeated wrong credentials are rate-limited.
- Browser microphone access from another device requires HTTPS/WSS. Follow the documented Caddy/local-certificate path.
- Browser-origin checks compare host and port, and cross-site `/api/*` requests are refused. With a token set, Host-header checks allow loopback, private IPs, and conventional LAN names; custom internal DNS names can be added with `QANTARA_ALLOWED_HOSTS`.
- Browser backend setup accepts only loopback/private targets (an explicit allowlist that excludes link-local and cloud-metadata addresses) and pins resolved IPs. Runtime configuration outside that UI remains operator-controlled.
- Default gateway event logs retain operational metadata but redact transcripts, model text, tool parameters, and credentials. Bridge output logging is opt-in with `QANTARA_BRIDGE_LOG_OUTPUT=1`.
- Session transcripts and histories are bounded in memory. The browser keeps non-secret preferences and session identifiers in local storage.
- Qantara has no telemetry. Speech/model providers may download artifacts, and any backend you configure receives the text turns sent to it.

Read [Privacy](docs/PRIVACY.md), [Security](SECURITY.md), and [Supply chain](docs/SUPPLY_CHAIN.md) before a LAN or sensitive-data deployment.

## Configuration

Configuration uses `QANTARA_` environment variables, an optional YAML file, CLI flags, and runtime setup choices. For CLI startup values, the implemented precedence is explicit CLI flags > environment variables > selected YAML file > built-in defaults. A `--config` or `QANTARA_CONFIG` path that does not exist stops startup with exit code 2.

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

CI runs the unit suite on Python 3.11–3.14 across Ubuntu, macOS, and Windows. It separately checks lint, compilation, release/documentation consistency, wheel/sdist contents, clean artifact installs, lock-file hashes and extras resolution, the Docker image build, dependency changes, and the base dependency set.

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
- [Mesh](docs/MESH.md) and [Home Assistant (Wyoming bridge removed in 0.4.0)](docs/HOMEASSISTANT.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Release process](docs/RELEASE_PROCESS.md)
- [Roadmap](ROADMAP.md) and [changelog](CHANGELOG.md)

## Contributing

Small fixes, tests, provider/adapter improvements, and documentation corrections are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md), use the issue templates, and discuss architecture changes before implementation. Security reports belong in GitHub's private vulnerability-reporting flow, not a public issue.

Qantara is licensed under [Apache 2.0](LICENSE).
