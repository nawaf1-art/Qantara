# Qantara 0.3.1 Release Notes (Draft)

Qantara `0.3.1` is a hardening and release-readiness update. It keeps the existing browser-first, WebSocket PCM, adapter, and provider architecture while tightening network/input/process boundaries and making package/release evidence repeatable.

## Highlights

- Content-free default event logging and opt-in bridge output.
- Exact origin authority checks, LAN-safe Host validation, browser security headers, and sanitized public URLs.
- Explicit bounds for WebSocket frames/control data, Voice API text/audio, stream lines, generated text, backend responses, and MCP progress queues.
- Redirect-disabled, proxy-independent local backend/probe requests and cleanup of timed-out subprocesses.
- Reproducible package checks, clean wheel/sdist smoke installs, immutable Action pins, dependency safeguards, and a manual tag-only draft-release workflow.
- Public privacy, governance, support, architecture-debt, and release-process documentation.

## Upgrade notes

- Custom internal hostnames outside the built-in local/LAN policy require `QANTARA_ALLOWED_HOSTS`.
- Bridge stdout/stderr is hidden by default; set `QANTARA_BRIDGE_LOG_OUTPUT=1` only for controlled local diagnostics.
- Use the new lightweight `.[test,dev]` source environment for unit/release work; install speech/model extras only when needed.

## Compatibility

No namespace migration, audio transport change, adapter-interface change, or broad turn-lifecycle rewrite is included. Those changes remain design-first future work.

## Validation evidence

Do not fill this section from memory. Before publication, copy the exact tag, commit, check outcome, artifact hashes, SBOM, and provenance links from the successful release-preparation run and attached `release-validation.json`.
