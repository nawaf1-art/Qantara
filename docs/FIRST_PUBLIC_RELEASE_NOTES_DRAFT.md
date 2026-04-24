# Release Notes: v0.2.6

Qantara is a local-first real-time voice gateway for Ollama, local LLMs, and local AI agents. It turns a browser on your LAN into a full-duplex voice interface with local STT, local TTS, interruption handling, and backend adapters for local LLM engines and agent runtimes.

## Highlights

- Browser microphone capture and audio playback over WebSocket
- Local faster-whisper speech-to-text
- Piper, Kokoro, and Chatterbox text-to-speech provider paths
- Full-duplex listening and interruption-safe barge-in
- OpenAI-compatible backend adapter for Ollama, llama.cpp, vLLM, LM Studio, Jan, LiteLLM, and similar servers
- Ollama session bridge for the Qantara session contract
- Advanced optional OpenClaw bridge for existing OpenClaw agent setups
- Multilingual assistant and translation modes for English, Arabic, Spanish, French, and Japanese
- Arabic Piper voice routing via `ar_JO-kareem-medium`
- Multi-device mesh and Home Assistant Wyoming satellite support
- Local-first defaults, no telemetry, no analytics, and no Qantara-controlled cloud dependency

## Install

Docker:

```bash
docker compose up
```

Native:

```bash
python3 -m venv .venv
./.venv/bin/pip install -r gateway/transport_spike/requirements.txt
make spike-run-venv
```

Open:

```text
http://localhost:8765
```

## Benchmark Snapshot

Measured on Linux 6.17 / Python 3.12 with `scripts/bench_launch.py --arabic`:

| Metric | Median | p95 |
|---|---:|---:|
| Gateway barge-in cancel path | 0.09 ms | 0.11 ms |
| Piper English TTS synthesis (`lessac`) | 1533 ms | 1541 ms |
| Piper Arabic TTS synthesis (`ar_JO-kareem-medium`) | 1801 ms | 1832 ms |

Backend response time depends on the selected local model and hardware. CI validation passed on Linux, macOS, and Windows with Python 3.11 and 3.12 before this tag.

## Known Limitations

- Pre-1.0 project: APIs and config names may still change.
- First run downloads local model assets and can take several minutes.
- Browser microphone access from another LAN device requires HTTPS and certificate trust.
- Docker path does not include host-only OpenClaw CLI integration.
- Public internet exposure is not supported; use loopback or trusted LAN.
- PyPI packaging is not finalized; use Docker or the documented native install path.

## Security

Qantara is intended for local and trusted-LAN use. Report vulnerabilities through GitHub private vulnerability reporting. See `SECURITY.md`.

## Support Expectations

This is a small pre-1.0 project. Maintainers will prioritize reproducible install issues, security reports, and regressions in the local voice loop. Feature requests are welcome, but new cloud-only dependencies or frontend build tooling are out of scope for the default project.

## Upgrade Notes

This is the first public release. No migration steps are expected.
