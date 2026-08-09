# Qantara 0.3.1 Release Notes

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

The GitHub Release is the canonical evidence bundle for this version. It attaches
the wheel and source archive built by the tag-only workflow together with
`SHA256SUMS`, an SPDX SBOM, and `release-validation.json`; GitHub also records
provenance attestations for those artifacts. Verify downloads against the attached
checksums and confirm that the release tag resolves to the commit recorded in the
validation file.
