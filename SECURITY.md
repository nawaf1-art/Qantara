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
- **Authentication bypass** in the gateway's token, browser-session, Host, or Origin checks, or in the session-gateway HTTP adapter's `auth_token` path
- **Mesh frame forgery** when `QANTARA_MESH_TOKEN` is configured (replay of captured signed frames is a known, tracked gap: [#26](https://github.com/nawaf1-art/Qantara/issues/26))

## Out of scope

- Denial-of-service by a local user against their own machine
- Issues that require physical access to the host
- Vulnerabilities in upstream dependencies (report those upstream — faster-whisper, Kokoro, Piper, aiohttp)
- Configurations that explicitly expose Qantara to the public internet (Qantara is designed for LAN; this is a user-choice risk)

## Deployment defaults

These are the boundaries a report should be measured against (see [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for every setting):

- **No token, no LAN.** Without `QANTARA_AUTH_TOKEN` the gateway answers only `localhost`, `127.0.0.0/8`, `::1`, and `QANTARA_ALLOWED_HOSTS` `Host` values; everything else gets HTTP 421 `lan_access_requires_token`. With a token, private-LAN hosts are accepted too.
- **Tokens.** Gateway, admin, and mesh tokens must be at least 24 characters; tokens containing whitespace or control characters are rejected at startup. Tokens are compared in constant time as UTF-8 bytes.
- **Browser sessions.** Each login creates a server-side session (default lifetime 12 h, at most 256, lost on restart) referenced by an HttpOnly, SameSite cookie; logout revokes it. More than 10 distinct wrong credentials per minute from one client get HTTP 429 with `Retry-After`.
- **Cross-site requests.** Origin must match the request authority (or `QANTARA_ALLOWED_ORIGINS`) for `/ws`, state-changing requests, and backend discovery; `/api/*` requests labelled `Sec-Fetch-Site: cross-site` are refused. Pages carry a CSP with `connect-src 'self'`.
- **Outbound probes.** Backend URLs from the browser must resolve to an explicit private allowlist (RFC 1918, loopback, `fc00::/7`); link-local and cloud-metadata addresses, 6to4, multicast, and `0.0.0.0/8` are refused. CGNAT needs `QANTARA_ALLOW_CGNAT=1`.
- **Mesh.** A non-loopback mesh bind requires `QANTARA_MESH_TOKEN` unless `QANTARA_MESH_ALLOW_INSECURE=1`.
- **MCP voice server.** Streamable HTTP binds to `127.0.0.1` (also when the host is empty); `0.0.0.0`, `::`, or any non-loopback host requires `QANTARA_MCP_SERVER_ALLOW_INSECURE=1` because that control plane has no inbound authentication.
- **Removed surface.** The Wyoming bridge, which bypassed authentication, was removed in `0.4.0`.

Reports that depend on an operator explicitly disabling one of these (for example `QANTARA_MESH_ALLOW_INSECURE=1` or `QANTARA_MCP_SERVER_ALLOW_INSECURE=1`) are still welcome when the documentation understates the risk.

## Supply chain

See [docs/SUPPLY_CHAIN.md](docs/SUPPLY_CHAIN.md) for what Qantara downloads, who verifies integrity, and how to run an air-gapped / audited install.

## Response expectations

Qantara is maintained by a small team. Expect response times in the order of days, not hours. We'll:

1. Acknowledge the report privately.
2. Work with you on a fix and disclosure timeline.
3. Credit you in release notes if you want to be named.

## Supported versions

Security fixes target `main` and the latest tagged release. The immediately
previous release line may receive a critical fix when the maintainers determine
that a safe backport is practical. Older tags are unsupported; upgrade before
reporting an issue that is already fixed in the current release.

Release-preparation branches and untagged version metadata are not supported
releases. The GitHub Releases page is the source of truth for the latest tag.
