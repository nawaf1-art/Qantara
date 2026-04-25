# Troubleshooting

Common problems and how to fix them. If your issue isn't here, open a GitHub issue with the gateway log (stdout) and your OS / Python version.

## Install and startup

### `docker compose up` is stuck "pulling" for minutes

Expected on first run. The initial build downloads the Ollama image, a ~2 GB LLM (`qwen2.5:3b`), and builds the Qantara image with Python/ML speech dependencies. Plan for roughly 8–10 GB of disk, plus temporary Docker build cache, and 5–10 minutes on a reasonable connection. Subsequent runs start in seconds.

If you see no progress for 10+ minutes, check Docker Desktop's status and your disk space.

### Port 8765 already in use

```bash
QANTARA_PORT=9765 docker compose up
```

Or for the manual path, set `QANTARA_SPIKE_PORT` before `make spike-run`.

### `pip install` fails with dependency resolution errors

Qantara pins exact versions with hashes. If you're on Python 3.10 or older, upgrade to 3.11+. If you're using an unusual platform (ARM without wheels), you may need to build `faster-whisper` or `kokoro` from source — see those projects' docs.

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
- Using the manual path? Install Ollama separately, run `ollama pull qwen2.5:3b` (or your model), then start the gateway.

### OpenClaw does not appear in setup

Expected in most first-run setups. OpenClaw is an advanced optional bridge and only appears when the host `openclaw` CLI is installed and `openclaw health --json` reports a healthy gateway. It is not available inside the Qantara Docker container. Use the manual install path (`make spike-run`) only if you already run OpenClaw agents on the host.

### OpenAI-compatible backend rejects my server URL

- URL probe restricts to private/loopback IPs only (see SECURITY.md).
- Strip `/v1/chat/completions` from the URL — enter just the host + port (e.g., `http://localhost:8080`).
- Test with `curl http://<host>:<port>/v1/models` to confirm the server is up.

## Voice and STT/TTS

### First response is very slow (5+ seconds)

Cold-start penalty. First time each of STT, TTS, and the LLM run they load weights. Expected:
- `faster-whisper base.en`: 2–3s cold, ~100ms warm
- `kokoro`: 3–5s cold, ~800ms warm
- `qwen2.5:3b`: 5–10s cold, ~1s warm

After the first turn, subsequent responses are much faster.

### Voice sounds robotic or distorted

You may be using the Piper fallback instead of Kokoro. Check the gateway log for `tts_chunk_ready engine=piper`. If Kokoro failed to load, check:
- Is `espeak-ng` installed? Kokoro depends on it.
- Enough RAM? Kokoro needs ~1 GB free.

### Barge-in doesn't interrupt playback

- Make sure VAD is detecting your speech — watch the `vad_state` events in the browser console.
- If VAD works but playback doesn't stop, check browser console for WebSocket errors during the cancel message.
- Try a closer/louder mic setup; the default VAD threshold is tuned for headsets.

## Networking

### Can't reach gateway from another device on my LAN

By default the gateway binds to `127.0.0.1`. To expose to your LAN:
```bash
QANTARA_SPIKE_HOST=0.0.0.0 make spike-run
```
And in the browser on the other device, access `http://<your-host-ip>:8765`. For mic to work off-localhost you will need HTTPS — see the TLS note above.

### TLS cert not trusted on other devices

See `ops/TRUST_CERT_WINDOWS.md` (Windows) and the `ops/README.md` for macOS/Linux. Self-signed certs need to be trusted on each client device.

## Diagnostics

### How to gather a good bug report

```bash
# Gateway version
cat VERSION

# Gateway log — redirect stdout to a file and reproduce the issue
python3 gateway/transport_spike/server.py 2>&1 | tee /tmp/qantara.log

# Browser console log — open DevTools > Console, reproduce, right-click > Save as...
```

Include both logs, the exact steps to reproduce, your OS and Python version, and the backend you were using.
