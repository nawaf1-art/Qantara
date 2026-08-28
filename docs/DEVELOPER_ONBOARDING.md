# Developer Onboarding

This guide is for contributors who want to modify Qantara without breaking its local-first, pre-1.0 contracts.

## Repository shape

```text
qantara/                  public Python facade and security/http helpers
adapters/                 backend adapter contract and implementations
gateway/transport_spike/  primary aiohttp gateway and WebSocket transport
gateway/*_backend/        session-backend bridge processes
providers/                STT/TTS provider interfaces and implementations
client/                   setup, voice, and translation browser pages
identity/                 voice registry and avatar metadata
protocols/                versioned public protocol specifications
schemas/                  public JSON schemas
tests/                    unittest suite
scripts/                  validation, doctor, smoke, benchmark, and asset helpers
docs/                     current guides, maintainer material, releases, and snapshots
```

Start with [Documentation governance](DOCUMENTATION_GOVERNANCE.md), [Architecture](../ARCHITECTURE.md), and the relevant component contract before changing behavior.

## Local setup

```bash
python3 -m venv .venv
./.venv/bin/pip install -e ".[test,dev]"
```

That environment runs unit, documentation, release, and package checks without downloading speech models. Install `.[speech]` only when working on local STT/TTS. It installs faster-whisper and Kokoro; Piper's Python runtime and voice files remain operator-supplied.

Run the source-checkout launcher:

```bash
./.venv/bin/python cli.py --backend mock
```

Run the complete Docker evaluation stack:

```bash
docker compose up
```

## Validation commands

```bash
# Full unit suite
python -m unittest discover -s tests -v

# Focused module/class
python -m unittest tests.test_gateway_http -v
python -m unittest tests.test_interruption.BargeInTests -v

# Lint and compile
ruff check .
python -m compileall -q qantara adapters gateway providers discovery tests

# Release/documentation invariants
python scripts/check_release_consistency.py
python scripts/check_workflow_pins.py
python scripts/check_docs_links.py
python scripts/check_docs_consistency.py
python scripts/check_tracked_artifacts.py

# Build/package evidence
python -m build
python -m twine check dist/*
python scripts/check_package_artifacts.py dist/*

# Optional benchmark
python scripts/bench_launch.py --arabic
```

`make test` remains a convenient unit-test wrapper. CI is authoritative for the cross-platform matrix and clean artifact installs.

## Code conventions

- Python 3.11+ with type hints on new public/function boundaries.
- Async gateway and HTTP code uses `aiohttp`.
- Browser code is vanilla JavaScript; do not add npm, webpack, Vite, React, or similar tooling.
- Operator configuration uses the `QANTARA_` prefix and must be documented in [Configuration](CONFIGURATION.md).
- Keep files focused; split large modules when it reduces lifecycle or ownership ambiguity.
- Do not add a cloud-only dependency to the default path. Cloud-compatible backends may remain optional adapters.
- Preserve loopback-safe defaults and explicit bounds.

## Where to add things

### Backend adapter

1. Implement `adapters/base.py:RuntimeAdapter` and follow [`adapters/CONTRACT.md`](../adapters/CONTRACT.md).
2. Register the selector/aliases in `adapters/factory.py`.
3. Add focused contract, failure, cancellation, and bounded-state tests.
4. Update adapter/component docs, configuration, feature matrix, architecture, and changelog as required by the governance matrix.

### STT provider

1. Implement `providers/stt/base.py:STTProvider`.
2. Register it in `providers/factory.py`.
3. Add a deterministic fixture or clearly bounded real-provider test.
4. Document package/model requirements, availability behavior, and supported platforms.

### TTS provider

1. Implement `providers/tts/base.py:TTSProvider`.
2. Return PCM samples plus a `VoiceSpec` and preserve provider sample rate.
3. Add registry entries only for redistributable assets or assets fetched by an explicit script.
4. Document voice/model licensing, transforms, fallbacks, and resource cost.

### Setup or browser UI

Edit the relevant HTML file under `client/` and keep it framework-free. For setup-page JavaScript syntax:

```bash
awk '/<script>/{flag=1;next}/<\\/script>/{flag=0}flag' client/setup/index.html > /tmp/qantara-setup.js
node --check /tmp/qantara-setup.js
```

## Documentation ownership

A behavior change owns its documentation change in the same pull request. Current guidance must be reconciled against implementation/tests; historical snapshots are preserved with the standard warning marker rather than silently rewritten into current status.

Before opening a pull request:

- run focused tests, the full unit suite, lint, and the documentation checks
- update every document required by the governance matrix
- avoid unrelated refactors
- record real/manual validation and untested surfaces in the PR body
- use a new version for corrections to published artifacts; never rewrite release evidence

See [`CONTRIBUTING.md`](../CONTRIBUTING.md) and [`AGENTS.md`](../AGENTS.md) for contributor and repository-agent rules.
