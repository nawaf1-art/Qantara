# Qantara Quickstart

This guide gets a fresh clone to a working local browser voice session.

## Requirements

- Docker with Docker Compose, or Python 3.11+
- A browser with microphone support
- Optional: Ollama or another OpenAI-compatible local LLM server

Browsers allow microphone access on `localhost` or HTTPS origins. For LAN testing from a phone or another computer, use the HTTPS/WSS setup below.

## Option 1: Docker Compose

```bash
git clone https://github.com/nawaf1-art/Qantara.git
cd Qantara
docker compose up
```

Open:

```text
http://localhost:8765
```

Choose **Demo** to test the voice UI without a backend. Choose **OpenAI-Compatible** when you have Ollama, llama.cpp, LM Studio, Jan, vLLM, LiteLLM, or another local `/v1/chat/completions` server running.

First startup downloads and builds speech dependencies. Expect roughly 5-10 minutes and 8-10 GB of disk on a fresh machine.

## Option 2: Native Python

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

## Ollama Setup

For the simplest Ollama path, expose Ollama through its OpenAI-compatible API and choose **OpenAI-Compatible** in the Qantara setup page.

```bash
ollama pull qwen3.5:2b
ollama serve
```

Then configure Qantara with:

```text
Base URL: http://127.0.0.1:11434/v1
Model: qwen3.5:2b
API key: any local placeholder if your server requires a value
```

Qantara also includes an Ollama session bridge for advanced session-contract testing:

```bash
make real-backend-run-venv
QANTARA_ADAPTER=session_gateway_http \
  QANTARA_BACKEND_BASE_URL=http://127.0.0.1:19120 \
  make spike-run-venv
```

## OpenAI-Compatible Backend Setup

Use this path for local servers that implement `/v1/chat/completions`, including Ollama, llama.cpp, LM Studio, Jan, vLLM, and LiteLLM.

1. Start your local server.
2. Open `http://localhost:8765`.
3. Choose **OpenAI-Compatible**.
4. Enter the base URL, model name, and API key if needed.
5. Click the test button before entering voice mode.

Qantara rejects public backend URLs in the setup flow by default. This keeps the browser setup path local-first.

## Test Your Microphone

1. Open `http://localhost:8765`.
2. Select **Demo**.
3. Allow microphone access when the browser asks.
4. Speak a short phrase.
5. Confirm the orb reacts, captions appear, and playback starts.
6. Speak again while Qantara is talking to test barge-in.

## LAN Testing

LAN browser microphone testing requires HTTPS unless the browser is on `localhost`.

```bash
QANTARA_AUTH_TOKEN="$(openssl rand -hex 24)" \
QANTARA_SPIKE_HOST=0.0.0.0 \
QANTARA_SPIKE_PORT=8899 \
QANTARA_TLS_CERT=ops/certs/qantara-cert.pem \
QANTARA_TLS_KEY=ops/certs/qantara-key.pem \
make spike-run-venv
```

Open:

```text
https://<your-lan-ip>:8899/spike
```

Enter the token if prompted. For Docker LAN exposure, set `QANTARA_DOCKER_BIND=0.0.0.0` and `QANTARA_AUTH_TOKEN` before `docker compose up`.

## Microphone Permission Troubleshooting

- Use `http://localhost:8765` for local testing.
- Use HTTPS for LAN testing.
- Check the browser address bar for a blocked microphone icon.
- Close other apps that may hold exclusive microphone access.
- Confirm the selected input device works in the operating system.
- In Chrome, open `chrome://settings/content/microphone` and verify the site is allowed.
- If audio meters never move, reload the page after granting permission.

More troubleshooting lives in [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
