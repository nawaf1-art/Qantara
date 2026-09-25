# Troubleshooting

Common problems and how to fix them. Start with `qantara doctor` (or `python scripts/doctor.py` in a source checkout): it checks the Python version against Kokoro, the aiohttp version, whether the configured STT/TTS engines are importable, CPU vs CUDA PyTorch, and token/TLS settings for non-loopback binds. If your issue isn't here, open a GitHub issue with the doctor output, the gateway log (stdout) and your OS / Python version.

## Install and startup

### `docker compose up` is stuck "pulling" for minutes

Expected on first run. The initial build downloads the Ollama image, the ~2.7 GB `qwen3.5:2b` model, and builds the Qantara image with Python/ML speech dependencies. Plan for roughly 8–10 GB of disk, plus temporary Docker build cache, and 5–10 minutes on a reasonable connection. Speech model weights download on first use into the `qantara-model-cache` volume and are reused after `docker compose down` (only `docker compose down --volumes` deletes them). Subsequent runs start in seconds.

If you see no progress for 10+ minutes, check Docker Desktop's status and your disk space.

### Port 8765 already in use

```bash
QANTARA_PORT=9765 docker compose up
```

Or for the manual path, set `QANTARA_SPIKE_PORT` before `make spike-run`.

### `pip install` fails with dependency resolution errors

- **Python 3.13 or newer and Kokoro:** every Kokoro release requires Python <3.13. On 3.13+ `pip install -e ".[speech]"` installs speech-to-text only; for Kokoro recreate the venv with `python3.12 -m venv .venv`.
- **Python 3.10 or older:** upgrade to 3.11+.
- **Hash mismatch from `requirements.txt`:** only the lock files (`ops/docker/requirements.txt`, `gateway/transport_spike/requirements.txt`) are hash-pinned; they cover CPython 3.11/3.12 on Linux x86_64/aarch64, Windows amd64 and macOS arm64. The `pyproject.toml` extras use version ranges and are not hash-pinned. If a lock install fails, you may be on another interpreter or platform; use the extras instead.

### `pip install` downloads several GB of `nvidia-*` packages

On Linux, PyPI's default PyTorch wheel is the CUDA build. On CPU-only machines install the CPU build first: `pip install torch --index-url https://download.pytorch.org/whl/cpu`, then `pip install -e ".[speech]"` (or use `uv pip install --torch-backend=cpu ...`). `qantara doctor` warns when a CUDA build is installed.

### Docker Desktop not running (macOS / Windows)

Start Docker Desktop first. `docker compose up` needs the daemon.

## Microphone and browser

### "Microphone access blocked" in the browser

Browsers block mic access over plain HTTP on non-localhost origins. Options:
- Access the gateway via `http://127.0.0.1:8765` or `http://localhost:8765` (both allowed)
- Or enable TLS: set `QANTARA_TLS_CERT` and `QANTARA_TLS_KEY` to a self-signed cert + key and access via `https://`

On some corporate-managed browsers, the mic permission is disabled globally. Check site permissions in the browser settings.

### No audio reaches the gateway

Open the browser console. Look for:
- `getUserMedia not supported` — browser too old or not over a secure context
- `NotAllowedError` — permission denied; click the lock icon in the address bar to re-grant
- `NotFoundError` — no mic detected at the OS level

### I hear nothing when the assistant replies

Check the browser's sound settings. The page has a playback indicator — if it shows playback started but no sound, your system audio output is routed elsewhere. On macOS, check Output device in System Settings > Sound.

## Backends

### Ollama backend tile shows "not available"

- Is Ollama running? Test with `curl http://localhost:11434/api/tags`.
- Using Docker? The included compose file spins up Ollama automatically — wait for `qantara-ollama-pull` to finish.
- Using the manual path? Install Ollama separately, run `ollama pull qwen3.5:2b` (or your model), then start the gateway.

### OpenClaw does not appear in setup

Expected in most first-run setups. OpenClaw is an advanced optional bridge and only appears when the host `openclaw` CLI is installed and `openclaw health --json` reports a healthy gateway. It is not available inside the Qantara Docker container. Use the manual install path (`make spike-run`) only if you already run OpenClaw agents on the host.

### OpenAI-compatible backend rejects my server URL

- URL probe restricts to private/loopback IPs only (see SECURITY.md).
- Strip `/v1/chat/completions` from the URL — enter just the host + port (e.g., `http://localhost:8080`).
- Test with `curl http://<host>:<port>/v1/models` to confirm the server is up.

## Voice and STT/TTS

### First response is very slow (5+ seconds)

Cold-start penalty. First time each of STT, TTS, and the LLM run they load weights. Expected:
- `faster-whisper small` (the default `QANTARA_WHISPER_MODEL`; `tiny.en`/`base.en` are faster, English-only): a few seconds cold, faster warm
- `kokoro`: 3–5s cold, ~800ms warm
- `qwen3.5:2b`: timing varies by hardware; disable thinking for the lowest voice latency

After the first turn, subsequent responses are much faster.

### Voice sounds robotic, or you hear a tone instead of speech

The native default is `QANTARA_TTS_PROVIDER=auto`: at startup it routes by language when both Kokoro and a Piper voice are usable, uses Kokoro alone when only Kokoro is installed, and otherwise Piper. Docker sets `kokoro`. An explicit `piper`, `kokoro`, or `routed` value is used as-is. If no engine is usable, replies play a short synthetic tone instead of speech. Check the gateway log for the `engine=` field on playback events and run `qantara doctor`, then:
- **Piper:** install the Piper runtime (`pip install piper-tts`) and a voice (`scripts/fetch_piper_voices.sh`, or `QANTARA_PIPER_MODEL`), or switch to `QANTARA_TTS_PROVIDER=kokoro`.
- **Kokoro:** requires Python 3.11/3.12, `espeak-ng` on the system (the Docker image includes it), and the spaCy model (`python -m spacy download en_core_web_sm`); allow ~1 GB of free RAM. With `QANTARA_OFFLINE=1` a missing spaCy model is reported as an error instead of being downloaded.

The setup page's engine choice (including **Automatic**) switches the engine immediately; it is not saved across restarts.

### "No voice is installed for this reply's language"

The reply is in a language no installed voice can speak — typically Arabic with only Kokoro (Docker, or a native install without Piper). Qantara shows this note instead of reading the text with a voice for another script. Install `piper-tts` and run `scripts/fetch_piper_voices.sh` on a native install; the default `auto` provider then sends Arabic to Piper.

### The transcript is in the wrong language

Set `QANTARA_STT_LANGUAGES` to the languages you actually speak (for example `en,ar`) so detection cannot pick an unrelated language. In directional and live translation modes the declared source language is used directly.

### A backend error appears in the conversation, or long answers stop

Backend failures are shown as a turn failure with a plain message instead of silence. Check the gateway log for the matching `recoverable_error` event (`stage`, `failure_kind`). For custom session backends, a turn fails after `QANTARA_BACKEND_IDLE_TIMEOUT` (90 s) with no events at all; send keep-alive activity while working or raise the timeout. The bundled Ollama/OpenClaw bridges send keep-alives automatically.

### Barge-in doesn't interrupt playback

- Use the **Headset** audio mode (the default) when you can; **Speakers** raises the interruption threshold to avoid the assistant interrupting itself.
- Make sure VAD is detecting your speech — watch the `vad_state` events in the browser console.
- If VAD works but playback doesn't stop, check browser console for WebSocket errors during the cancel message.
- Try a closer/louder mic setup; the default VAD threshold is tuned for headsets.

## Networking

### Can't reach gateway from another device on my LAN

By default the gateway binds to `127.0.0.1`. To expose to your LAN:
```bash
QANTARA_AUTH_TOKEN="$(openssl rand -hex 24)" QANTARA_SPIKE_HOST=0.0.0.0 make spike-run
```
And in the browser on the other device, access `http://<your-host-ip>:8765`. For mic to work off-localhost you will need HTTPS — see the TLS note above.

The token is required: without `QANTARA_AUTH_TOKEN` the gateway answers HTTP 421 (`code: "lan_access_requires_token"`) to requests whose `Host` is not loopback (a LAN IP, `qantara.local`, or a reverse proxy's forwarded Host). If the gateway exits immediately after setting auth, confirm the token is at least 24 characters and contains no spaces or control characters.

### Login fails with HTTP 429

More than 10 different wrong credentials were tried from your address within a minute. Wait for the `Retry-After` interval and use the correct token. Behind a loopback reverse proxy each client is identified by its `X-Forwarded-For` address.

### The gateway refuses to start with a mesh error

A non-loopback `QANTARA_MESH_HOST` needs `QANTARA_MESH_TOKEN` (24+ characters), and `QANTARA_MESH_ROLE` / `QANTARA_MESH_NODE_ID` must be valid values. See [Mesh](MESH.md#startup-rules).

### Setup page says Qantara is locked

This means `QANTARA_AUTH_TOKEN` is enabled. Open `/setup`, enter the token, and the browser will receive an HttpOnly session cookie for a server-side session (12 hours by default). Sessions end at logout and when the gateway restarts, so you log in again after a restart. API clients can use `Authorization: Bearer <token>` instead.

### TLS cert not trusted on other devices

See `ops/TRUST_CERT_WINDOWS.md` (Windows) and the `ops/README.md` for macOS/Linux. Self-signed certs need to be trusted on each client device.

## Diagnostics

### How to gather a good bug report

```bash
# Gateway version and environment check
cat VERSION
python scripts/doctor.py        # or: qantara doctor

# Gateway log — redirect stdout to a file and reproduce the issue
python3 gateway/transport_spike/server.py 2>&1 | tee /tmp/qantara.log

# Browser console log — open DevTools > Console, reproduce, right-click > Save as...
```

Include both logs, the exact steps to reproduce, your OS and Python version, and the backend you were using.
