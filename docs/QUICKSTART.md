# Qantara Quickstart

## Docker path

```bash
git clone https://github.com/nawaf1-art/Qantara.git
cd Qantara
docker compose up
```

Open [http://localhost:8765](http://localhost:8765). Allow microphone access, use **Demo** for a UI/transport check, or select the local Ollama backend started by Compose.

Docker binds Qantara to `127.0.0.1` by default. The Docker image speaks English, Spanish, and French with Kokoro; it does not include Piper, so Arabic replies are shown as text with a "no voice installed" note. First startup downloads substantial container, speech, and model artifacts; duration and disk use vary by platform and network. Model weights are kept in the `qantara-model-cache` volume across `docker compose down`.

## Native path

```bash
git clone https://github.com/nawaf1-art/Qantara.git
cd Qantara
python3.12 -m venv .venv
./.venv/bin/pip install -e ".[speech]"
./.venv/bin/python -m spacy download en_core_web_sm
./.venv/bin/qantara doctor
./.venv/bin/qantara --backend mock
```

Open [http://localhost:8765](http://localhost:8765).

- Use Python 3.12 (or 3.11): Kokoro, the default voice in Docker, does not install on Python 3.13+. On 3.13+ the `speech` extra installs speech-to-text only.
- On a Linux machine without an NVIDIA GPU, avoid the multi-GB CUDA build of PyTorch by running `./.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu` before the extra (or `uv pip install --python .venv --torch-backend=cpu -e ".[speech]"`). See [Installation](INSTALLATION_AND_FIRST_RUN_GUIDE.md#option-2-native-source-checkout).
- The default `QANTARA_TTS_PROVIDER=auto` uses Kokoro for English, Spanish, and French. For Arabic speech output also run `./.venv/bin/pip install piper-tts` and `scripts/fetch_piper_voices.sh`; Qantara then routes Arabic to Piper automatically.
- `./.venv/bin/python cli.py ...` is equivalent to `./.venv/bin/qantara ...` in a source checkout.

With Ollama running locally:

```bash
ollama pull qwen3.5:2b
./.venv/bin/qantara --backend http://127.0.0.1:11434 --model qwen3.5:2b
```

The CLI selects the direct OpenAI-compatible adapter for an HTTP URL. The setup page can configure the same path interactively.

## Check the voice loop

1. Confirm the page loads on the conversation view and connects automatically.
2. Press **Start** once (this unlocks audio playback and starts the microphone) and allow microphone access.
3. Speak a short synthetic or non-sensitive phrase.
4. Confirm input activity and a final transcript appear.
5. Confirm assistant text and audio playback arrive.
6. Speak while playback is active to check barge-in.

If no local STT/TTS provider is available, the UI and mock backend can still exercise control flow, but they do not prove a complete speech-model installation.

## LAN use

Microphone access from another machine requires HTTPS/WSS. A strong `QANTARA_AUTH_TOKEN` is required: the gateway refuses requests whose `Host` is not loopback when no token is set. Follow [ops/README.md](../ops/README.md); do not publish port 8765 directly to the internet.

For Docker, changing `QANTARA_DOCKER_BIND` from loopback is an explicit exposure decision. For native use, changing `QANTARA_SPIKE_HOST` has the same effect.

## Next steps

- [Installation details](INSTALLATION_AND_FIRST_RUN_GUIDE.md)
- [Configuration reference](CONFIGURATION.md)
- [Ollama compatibility](OLLAMA_COMPATIBILITY.md)
- [Troubleshooting](TROUBLESHOOTING.md)
- [Privacy boundary](PRIVACY.md)
