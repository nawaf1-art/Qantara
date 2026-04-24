# Contributing to Qantara

Qantara is in pre-launch (`0.2.6-dev.1`). Early contributions are welcome, especially for small documentation, provider, adapter, and test improvements listed in [ROADMAP.md](ROADMAP.md). This guide covers how to file issues, propose changes, and submit patches.

If you're here to understand the codebase conventions, read [AGENTS.md](AGENTS.md) first — it's the definitive guide for both humans and AI coding agents.

## Ground rules

Before sending a change, open an issue or discussion when the work is larger than a small fix. This avoids duplicate effort and catches architectural mismatches early. The architecture decisions in [AGENTS.md](AGENTS.md) ("Architecture Decisions — Locked") are not up for change without discussion.

Every feature must work **locally with no cloud dependency**. Cloud providers can be optional add-ons, but the default install must run entirely on the user's machine.

## Getting started

Clone, install, and run the tests:

```bash
git clone https://github.com/nawaf1-art/Qantara.git
cd Qantara
python3 -m venv .venv
./.venv/bin/pip install -r gateway/transport_spike/requirements.txt
make test            # runs the unittest suite under tests/
```

To run the gateway against a local backend:

```bash
make spike-run-venv  # opens http://127.0.0.1:8765 — setup page guides backend choice
```

For the full flow with Ollama:

```bash
make real-backend-run-venv   # terminal 1 — Ollama bridge on :19120
QANTARA_ADAPTER=session_gateway_http \
  QANTARA_BACKEND_BASE_URL=http://127.0.0.1:19120 \
  make spike-run-venv         # terminal 2
```

## Development workflow

1. Fork and branch. Use a short descriptive branch name (`feature/vosk-stt`, `fix/barge-in-race`).
2. Match existing conventions. Python 3, aiohttp async, type hints on all function signatures, files under 300 lines.
3. Install the pre-commit hook so lint runs automatically on each commit:
   ```bash
   pip install pre-commit ruff
   pre-commit install
   ```
   Config lives in `.pre-commit-config.yaml` and `pyproject.toml`. The same `ruff check` runs in CI — a PR with lint errors will not pass.
4. Add tests. Place them in `tests/` mirroring the source layout. Run `make test` and confirm all pass.
5. Keep commits focused. One logical change per commit. Commit messages should describe the *why*, not just the *what*.
6. Open a pull request against `main` with a short description and a link to the relevant issue or roadmap item.

## Adding a provider or adapter

The three main extension points each have a worked example to copy from. See AGENTS.md section "Key Patterns" for the step-by-step for:

- **New STT provider** — subclass `providers/stt/base.py:STTProvider`
- **New TTS provider** — subclass `providers/tts/base.py:TTSProvider`
- **New backend adapter** — subclass `adapters/base.py:RuntimeAdapter`

Each requires a test that validates the contract (transcription works, synthesis returns valid PCM, adapter passes the backend-contract suite in `tests/test_backend_contracts.py`).

## Code style

- No JS build tooling. The browser client is vanilla JS — `client/transport-spike/index.html` is intentionally a single file.
- No framework dependencies on the Python side beyond aiohttp. No Flask, FastAPI, Django.
- No decorators that hide behavior, no dynamic imports, no metaprogramming.
- Environment variables are prefixed with `QANTARA_`. Never hardcode model paths, API keys, or host addresses.
- Audio format is PCM16 mono 16 kHz everywhere. Don't silently resample.

## Useful validation commands

Run the smallest useful check while developing, then run the full suite before opening a PR:

```bash
# One test module
./.venv/bin/python -m unittest tests.test_backend_discovery -v

# One test class
./.venv/bin/python -m unittest tests.test_interruption.BargeInTests -v

# Full suite
make test

# Lint everything
ruff check .

# Launch benchmark snapshot
./.venv/bin/python scripts/bench_launch.py --arabic
```

## Reporting bugs

Open an issue with:
- Qantara version (see `VERSION`)
- OS and Python version
- Backend in use (Ollama model, OpenClaw agent, OpenAI-compatible endpoint, mock, etc.)
- Steps to reproduce
- Gateway stdout log if relevant (it emits newline-delimited JSON event records)

For voice-quality or latency reports, include the `playback_metrics` line from the gateway log — it has `tts_to_first_audio_ms` and engine info.

## Security

If you find a security issue, please do **not** open a public issue. Use GitHub private vulnerability reporting when available, or contact the maintainer through the repo owner's GitHub profile. See [SECURITY.md](SECURITY.md) for scope and response expectations.

## License

By submitting a contribution, you agree it will be licensed under the project's Apache 2.0 license (see [LICENSE](LICENSE)).
