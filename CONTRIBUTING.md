# Contributing to Qantara

Qantara is a public, pre-1.0 local voice gateway. Focused fixes, tests, documentation, and provider/adapter improvements are welcome.

For a change larger than a small fix, open an issue or discussion first. Architecture choices listed in [AGENTS.md](AGENTS.md) are deliberate; changing the adapter boundary, audio transport, full-duplex behavior, or local-first default needs an accepted design before implementation.

## Supported development environment

- Python 3.11 or 3.12
- Linux, macOS, or Windows
- Docker Compose v2 for Docker changes
- A Chromium-family browser for manual microphone testing

The latest tagged release and `main` are the maintained code lines. Qantara is pre-1.0, so compatibility-impacting changes are possible, but they must be called out in the PR and changelog.

## Set up a lightweight development environment

```bash
git clone https://github.com/nawaf1-art/Qantara.git
cd Qantara
python3 -m venv .venv
./.venv/bin/pip install -e ".[test,dev]"
```

This installs the unit-test and release tools without downloading speech models or the full ML stack. Add the relevant extra only when your change needs it:

```bash
./.venv/bin/pip install -e ".[speech]"
./.venv/bin/pip install -e ".[mcp]"
./.venv/bin/pip install -e ".[mesh]"
./.venv/bin/pip install -e ".[chatterbox]"
```

On Windows, use `.venv\Scripts\python.exe` and `.venv\Scripts\pip.exe`.

## Development rules

- Keep the default path fully local. External services may be optional but must never become required.
- Use async `aiohttp`; do not introduce another Python web framework.
- Keep the browser client vanilla JavaScript with no build tool.
- Preserve PCM16 mono 16 kHz at the gateway transport boundary.
- Use `QANTARA_` environment variables for operator configuration; never hardcode tokens, hosts, model paths, or credentials.
- Keep new Python files focused, typed, and preferably below 300 lines.
- Do not change adapter interfaces without updating every adapter, its contract tests, and protocol documentation.
- Treat user audio, transcripts, model output, tool arguments, URLs, and credentials as sensitive. Tests and diagnostics should use synthetic content.

## Test expectations

Run the smallest relevant tests while developing, then the complete lightweight suite before opening a PR:

```bash
python -m unittest tests.test_streaming -v
python -m unittest discover -s tests -v
ruff check .
python -m compileall -q qantara adapters gateway providers discovery tests
```

If packaging or public metadata changes, also run:

```bash
python scripts/check_release_consistency.py
python -m build
python -m twine check dist/*
python scripts/check_package_artifacts.py dist/*
python scripts/smoke_install.py --expected "$(cat VERSION)" dist/*.whl
python scripts/smoke_install.py --expected "$(cat VERSION)" dist/*.tar.gz
```

Additional expectations by change type:

- Adapter/provider changes: contract tests plus one success and one failure-path test.
- Streaming changes: fragmented, coalesced, malformed, oversized, and multibyte UTF-8 cases.
- Turn/cancellation changes: interruption, timeout, disconnect, and late-output tests.
- Browser changes: route smoke tests and a manual supported-browser check.
- Docker changes: `docker compose config` and, when practical, a clean build/health check.
- Documentation claims: link to an implemented behavior, a reproducible measurement, or mark the claim as planned/historical.

Real model, microphone, LAN, and device tests are not required for every patch. When they are relevant, list exactly what you tested and what you did not test in the PR.

## Compatibility and documentation

Public interfaces include:

- imports from `qantara`, `adapters`, `gateway`, `providers`, and `discovery`
- adapter/provider abstract contracts
- WebSocket and Voice API event shapes
- environment variable names
- packaged browser, identity, protocol, and schema resources

Avoid silent breaking changes. Add a migration note and changelog entry when behavior changes. Use only the status vocabulary **Beta**, **Experimental**, **Planned**, and **Deprecated** in current public docs.

## Pull requests

1. Create a focused branch and keep commits reviewable.
2. Add or update tests before changing public claims.
3. Complete the PR template, including security/privacy and compatibility impact.
4. Link the issue or explain why a small direct fix did not need one.
5. Do not include `.env` files, tokens, model weights, certificates, logs, audio captures, or private transcripts.

CI checks Python 3.11/3.12 on Ubuntu, macOS, and Windows, plus lint, compilation, dependencies, package contents, and clean artifact installs.

## AI-assisted contributions

AI-assisted work is welcome under the same standards as any other contribution. The human contributor remains responsible for understanding the change, reviewing the complete diff, running relevant checks, and responding to review.

Disclose substantial AI assistance in the PR when it materially generated or transformed code, tests, or prose. Do not submit private prompts, transcripts, credentials, logs, or third-party confidential material. Generated tests do not replace evidence that the behavior works.

## Bug and diagnostic reports

Use the bug issue form and include:

- Qantara version or commit
- operating system and Python version
- deployment mode and backend/provider names
- minimal reproduction steps
- expected and actual behavior

Default Qantara event logs are content-free, but bridge logs, external backend logs, traces, screenshots, and terminal history may still contain sensitive material. Redact tokens, URLs with credentials/query data, hostnames if sensitive, transcripts, model output, tool arguments, and personal data before sharing. Never attach raw audio unless maintainers explicitly request a synthetic reproduction.

Security vulnerabilities must use the private process in [SECURITY.md](SECURITY.md), not a public issue.

## License

By submitting a contribution, you agree that it is licensed under [Apache 2.0](LICENSE).
