# Security Policy

Thank you for helping keep Qantara and its users safe.

## Reporting a vulnerability

**Please do not open a public GitHub issue for security reports.**

Use GitHub's private vulnerability reporting flow:

1. Go to the [Security tab](https://github.com/nawaf1-art/Qantara/security/advisories) of the Qantara repo
2. Click **Report a vulnerability**
3. Describe the issue, how to reproduce it, and the impact you observed

You'll get a private advisory thread that only the maintainers and invited collaborators can see. We'll confirm receipt within a few days.

If you cannot use GitHub's flow for any reason, contact the maintainer via the email on the repo owner's [GitHub profile](https://github.com/nawaf1-art).

## Scope

Qantara is a local-first voice gateway. The following are in scope:

- **SSRF / request forgery** in the adapter layer or `/api/test-url` probe
- **Command injection** in the managed bridge subprocess paths (Ollama, OpenClaw)
- **Path traversal** in any file-serving route (`/setup`, `/spike`, `/identity`)
- **WebSocket protocol abuse** (malformed binary frames, control message injection)
- **Trust boundary violations** between the browser client and gateway, or gateway and adapter
- **Model download integrity** (ONNX/model file tampering)
- **Authentication bypass** in the session-gateway HTTP adapter's `auth_token` path

## Out of scope

- Denial-of-service by a local user against their own machine
- Issues that require physical access to the host
- Vulnerabilities in upstream dependencies (report those upstream — faster-whisper, Kokoro, Piper, aiohttp)
- Configurations that explicitly expose Qantara to the public internet (Qantara is designed for LAN; this is a user-choice risk)

## Supply chain

See [docs/SUPPLY_CHAIN.md](docs/SUPPLY_CHAIN.md) for what Qantara downloads, who verifies integrity, and how to run an air-gapped / audited install.

## Response expectations

Qantara is maintained by a small team and this is a pre-launch project. Expect response times in the order of days, not hours. We'll:

1. Acknowledge the report privately.
2. Work with you on a fix and disclosure timeline.
3. Credit you in release notes if you want to be named.

## Supported versions

During pre-launch, only the `main` branch is supported. Once `v0.2.6` (public launch) ships, the policy will be updated to cover the most recent minor release.
