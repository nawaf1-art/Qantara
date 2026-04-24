# Installation and First Run

This guide assumes you are cloning Qantara for the first time.

## What Qantara Runs

Qantara runs a local Python gateway and a browser client. It also needs an AI backend. The easiest backend path is an OpenAI-compatible local server such as Ollama's `/v1/chat/completions` endpoint.

Speech-to-text and text-to-speech run locally by default. First runs may download model files.

## Supported Platforms

Known-good development path:

- Linux with Python 3.11 or newer
- Docker with Compose v2
- Chromium/Chrome/Edge for browser microphone testing

Expected but should be validated before release:

- macOS with Python 3.11 or newer
- Windows via Docker Desktop or WSL2

## Prerequisites

For native install:

- Python 3.11+
- `pip`
- `make`
- `curl`
- enough disk for Python dependencies and speech models

For Docker install:

- Docker Desktop or Docker Engine
- Docker Compose v2
- roughly 5 GB free disk for the first build and model pull

Optional:

- Ollama for a local LLM backend
- Caddy or local TLS certs for microphone access from another LAN device
- OpenClaw CLI only if using the advanced optional OpenClaw bridge

## Fastest Start: Docker

```bash
git clone https://github.com/nawaf1-art/Qantara.git
cd Qantara
docker compose up
```

Open:

```text
http://localhost:8765
```

The first Docker run downloads the Ollama image, a small local model, and Python speech dependencies. Expect several minutes.

## Native Start

```bash
git clone https://github.com/nawaf1-art/Qantara.git
cd Qantara
python3 -m venv .venv
./.venv/bin/pip install -r gateway/transport_spike/requirements.txt
make spike-run-venv
```

Open:

```text
http://localhost:8765
```

## Backend Setup

Recommended local backend:

```bash
ollama pull qwen2.5:3b
ollama serve
```

Then choose **OpenAI-Compatible** in the setup page and use:

```text
http://127.0.0.1:11434
```

Qantara expects the base server URL. Do not paste `/v1/chat/completions`.

## LAN Microphone Testing

Browsers require HTTPS for microphone access from another device on your LAN.

Generate a local certificate:

```bash
mkdir -p ops/certs
openssl req -x509 -nodes -days 30 \
  -newkey rsa:2048 \
  -keyout ops/certs/qantara-key.pem \
  -out ops/certs/qantara-cert.pem \
  -config ops/openssl-qantara.cnf
```

Run the gateway:

```bash
QANTARA_SPIKE_HOST=0.0.0.0 \
QANTARA_SPIKE_PORT=8899 \
QANTARA_TLS_CERT=ops/certs/qantara-cert.pem \
QANTARA_TLS_KEY=ops/certs/qantara-key.pem \
make spike-run-venv
```

Open:

```text
https://<your-lan-ip>:8899
```

The client device must trust the certificate. See `ops/TRUST_CERT_WINDOWS.md` for Windows.

## Verify Your Install

Run:

```bash
make doctor
make test
ruff check .
```

Optional launch benchmark:

```bash
./.venv/bin/python scripts/bench_launch.py --arabic
```

## Common First-Run Problems

- Microphone blocked: use `localhost` or HTTPS, then check browser site permissions.
- No backend detected: start Ollama or enter an OpenAI-compatible private/loopback URL manually.
- First response slow: STT, TTS, and LLM models may be cold-loading.
- No audio: check browser output device, muted tab state, and OS audio routing.

More details: [Troubleshooting](TROUBLESHOOTING.md).
