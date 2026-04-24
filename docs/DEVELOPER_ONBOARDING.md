# Developer Onboarding

This guide is for contributors who want to modify Qantara.

## Repository Shape

```text
adapters/                 backend adapter contract and implementations
gateway/transport_spike/  main aiohttp gateway and WebSocket transport
gateway/*_backend/        managed session backend bridge processes
providers/                STT/TTS provider interfaces and implementations
client/                   setup, voice, and translation browser pages
identity/                 voice registry and avatar metadata
schemas/                  protocol and event documentation
tests/                    unittest suite
scripts/                  doctor, smoke, benchmark, and model-fetch helpers
docs/                     public documentation and release audit package
```

## Local Setup

```bash
python3 -m venv .venv
./.venv/bin/pip install -r gateway/transport_spike/requirements.txt
```

Run the gateway:

```bash
make spike-run-venv
```

Run with Docker:

```bash
docker compose up
```

## Validation Commands

```bash
# Full suite
make test

# One module
./.venv/bin/python -m unittest tests.test_gateway_http -v

# One class
./.venv/bin/python -m unittest tests.test_interruption.BargeInTests -v

# Lint
ruff check .

# Launch benchmark
./.venv/bin/python scripts/bench_launch.py --arabic
```

## Code Conventions

- Python 3.11+ with type hints on new function signatures.
- Async gateway code uses `aiohttp`.
- Browser code is vanilla JS. Do not add npm, webpack, Vite, React, or similar tooling.
- Config variables use the `QANTARA_` prefix.
- Keep new files focused. Split large modules when practical.
- Do not add cloud-only dependencies. Cloud backends may be optional adapters, but the default project must remain local-first.

## Where to Add Things

Add a backend adapter:

1. Implement `adapters/base.py:RuntimeAdapter`.
2. Register it in `adapters/factory.py`.
3. Add tests mirroring `tests/test_backend_contracts.py`.
4. Document env vars and limitations.

Add an STT provider:

1. Implement `providers/stt/base.py:STTProvider`.
2. Register it in `providers/factory.py`.
3. Add a test with known audio or a small provider fixture.

Add a TTS provider:

1. Implement `providers/tts/base.py:TTSProvider`.
2. Return PCM samples and a `VoiceSpec`.
3. Add registry entries only if voices are redistributable or downloaded by script.

Add setup UI:

- Edit `client/setup/index.html`.
- Keep it framework-free.
- Check syntax with:

```bash
awk '/<script>/{flag=1;next}/<\\/script>/{flag=0}flag' client/setup/index.html > /tmp/qantara-setup.js
node --check /tmp/qantara-setup.js
```

## Pull Request Expectations

Before opening a PR:

- run the relevant focused tests
- run `make test`
- run `ruff check .`
- update docs for behavior changes
- avoid unrelated refactors
- note any manual testing in the PR body

See `CONTRIBUTING.md` and `AGENTS.md` for the full contributor and agent guidance.
