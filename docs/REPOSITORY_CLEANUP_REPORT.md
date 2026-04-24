# Repository Cleanup Report

Date: 2026-04-24

## Summary

The repository was not publish-ready at the start of this pass because tracked `docs/internal/` files contained private development history, local network references, machine paths, and agent-specific validation notes. The public docs also still over-emphasized OpenClaw even though Qantara's current objective is a standalone local-first voice gateway.

Safe cleanup was applied directly. Approval-sensitive or history-level remediation is documented below.

## Changes Made

- Removed tracked `docs/internal/` development notes from the public repository surface.
- Replaced internal handoff/runbook material with public-facing docs under `docs/`.
- Added `.env.example` with safe placeholders.
- Expanded `.gitignore` for `.env.*`, `.ruff_cache/`, `.pytest_cache/`, and `.mypy_cache/`.
- Sanitized LAN IP examples in ops docs and OpenSSL config.
- Changed OpenClaw examples/defaults from a local agent name to the generic `main`.
- Updated the architecture document so Qantara is described as backend-agnostic, not OpenClaw-bound.
- Added public docs map, installation guide, configuration guide, developer onboarding, release checklist, release notes draft, and audit reports.
- Kept downloaded model weights and local TLS certs untracked and ignored.

## Items That Should Stay

- `README.md`, `ARCHITECTURE.md`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`, `ROADMAP.md`
- `.github/` workflows and templates
- `adapters/`, `gateway/`, `providers/`, `client/`, `identity/`, `schemas/`, `ops/`, `scripts/`, `tests/`
- `qantara.example.yml` and `.env.example`
- `docs/` public guides and audit package

## Items Removed From Tracked Public Surface

- `docs/internal/` historical planning and session handoff notes

Reason: the content was useful during private development but mixed public roadmap material with local IPs, personal filesystem paths, host-specific validation notes, and private workflow details. Keeping it would look unprofessional and unnecessarily expose local context.

## Items That Should Remain Ignored

- `.venv/`
- `.ruff_cache/`
- `__pycache__/`
- `.env`
- `.env.*` except `.env.example`
- `ops/certs/`
- `models/piper/*.onnx`
- `models/piper/*.onnx.json`

## Remaining Cleanup Recommendations

- Consider moving generated requirement lock files into a clearer dependency strategy before PyPI packaging.
- Keep `docs/DEMO.md` only as optional maintainer material; it is no longer a launch blocker.
- Keep avatar preset names generic and avoid tying them to private agent identities.
- Publish from the clean `public-main` branch, not from private `main`. See `SECURITY_PUBLICATION_AUDIT.md`.
- Keep the `/spike` route and `transport_spike` module name for the first public release, but consider adding a `/voice` or `/app` alias before a future rename. The current names are historical and broadly referenced, so renaming them during this pass would add release risk.

## Not Done Deliberately

- Did not delete source code for OpenClaw because it is now advanced/optional and isolated behind the bridge boundary.
- Did not remove Docker support because it is the best first-run path for public users.
- Did not add npm or frontend tooling.
- Did not attempt PyPI packaging because the project is not yet structured as an installable Python package.
- Did not rename `gateway/transport_spike` or `client/transport-spike`; public-facing text was cleaned, and the compatibility debt is documented above.
