# Qantara Quickstart

## Docker path

```bash
git clone https://github.com/nawaf1-art/Qantara.git
cd Qantara
docker compose up
```

Open [http://localhost:8765](http://localhost:8765). Allow microphone access, use **Demo** for a UI/transport check, or select the local Ollama backend started by Compose.

Docker binds Qantara to `127.0.0.1` by default. First startup downloads substantial container, speech, and model artifacts; duration and disk use vary by platform and network.

## Native path

```bash
git clone https://github.com/nawaf1-art/Qantara.git
cd Qantara
python3 -m venv .venv
./.venv/bin/pip install -e ".[speech]"
./.venv/bin/python cli.py --backend mock
```

Open [http://localhost:8765](http://localhost:8765).

With Ollama running locally:

```bash
ollama pull qwen3.5:2b
./.venv/bin/python cli.py --backend http://127.0.0.1:11434 --model qwen3.5:2b
```

The CLI selects the direct OpenAI-compatible adapter for an HTTP URL. The setup page can configure the same path interactively.

## Check the voice loop

1. Confirm the status/setup page loads.
2. Allow microphone access.
3. Speak a short synthetic or non-sensitive phrase.
4. Confirm input activity and a final transcript appear.
5. Confirm assistant text and audio playback arrive.
6. Speak while playback is active to check barge-in.

If no local STT/TTS provider is available, the UI and mock backend can still exercise control flow, but they do not prove a complete speech-model installation.

## LAN use

Microphone access from another machine requires HTTPS/WSS. Set a strong auth token and follow [ops/README.md](../ops/README.md); do not publish port 8765 directly to the internet.

For Docker, changing `QANTARA_DOCKER_BIND` from loopback is an explicit exposure decision. For native use, changing `QANTARA_SPIKE_HOST` has the same effect.

## Next steps

- [Installation details](INSTALLATION_AND_FIRST_RUN_GUIDE.md)
- [Configuration reference](CONFIGURATION.md)
- [Ollama compatibility](OLLAMA_COMPATIBILITY.md)
- [Troubleshooting](TROUBLESHOOTING.md)
- [Privacy boundary](PRIVACY.md)
