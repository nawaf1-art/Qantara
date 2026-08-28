# Session Handoff

> [!NOTE]
> **Historical snapshot — not current product guidance.** This file summarizes the April-May 2026 public-release handoff. The original detailed checkpoint remains available in Git history; it contained obsolete scores, local-machine commands, and superseded release blockers.

Date: 2026-04-28, with a final checkpoint on 2026-05-11.

## Historical scope

The handoff covered:

- conversion from private development material to a clean public repository
- first public release readiness and LAN/auth hardening
- setup-page, browser auth, Docker, mesh/Wyoming, and language-routing corrections
- early MCP client/server and voice-control work
- OpenAI-compatible, Ollama, and OpenClaw bridge validation
- lifecycle cleanup before the later 0.3.x release line

## State at that time

The project was still moving through the 0.2.x release series. MCP and physical-device validation were incomplete, package publication was not finalized, and several local verification notes were still framed as future work.

Those statements are not the current Qantara status. In particular, Qantara now has a Python package/SDK, published GitHub Release artifacts, expanded release evidence, and later hardening work documented in the changelog and versioned release notes.

## Current sources instead

Use these documents for present work:

- [`README.md`](../README.md) — product and current release overview
- [`docs/FEATURES.md`](FEATURES.md) — shipped/experimental/planned status
- [`ARCHITECTURE.md`](../ARCHITECTURE.md) — current architecture and trust boundaries
- [`docs/CONFIGURATION.md`](CONFIGURATION.md) — current environment and limits
- [`docs/RELEASE_NOTES_0.3.1.md`](RELEASE_NOTES_0.3.1.md) — current release notes
- [`CHANGELOG.md`](../CHANGELOG.md) — version history
- [`ROADMAP.md`](../ROADMAP.md) — future direction
- [`docs/DOCUMENTATION_GOVERNANCE.md`](DOCUMENTATION_GOVERNANCE.md) — source-of-truth rules

Do not use the old handoff's scores, machine paths, IP addresses, test counts, commit ids, or “next steps” as current project instructions.
