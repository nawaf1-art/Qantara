# Security Publication Audit

Date: 2026-04-24

## Scope

Reviewed tracked source, docs, examples, scripts, config, workflows, ignored local artifacts, and recent repository history indicators for publication-sensitive data.

## Result

No real API keys, passwords, SSH keys, private TLS keys, or cloud credentials were found in tracked files during this pass.

The private development branch did contain tracked local/private context in historical `docs/internal/` files. Those files were removed from the current public tree. The intended publication path is the `public-main` orphan branch, which starts from the cleaned tree instead of carrying the private branch history.

## Sensitive-Data Findings

### Fixed in Current Tree

- Removed tracked internal documents containing local LAN IPs, personal filesystem paths, and private validation notes.
- Replaced LAN IP examples in ops docs and OpenSSL config with placeholders.
- Changed OpenClaw examples/defaults from a local agent-specific value to `main`.
- Added `.env.example` with safe placeholders.
- Expanded `.gitignore` to reduce future accidental commits of env/cache files.

### Ignored but Present Locally

These files may exist in a developer working tree but are ignored and should not be published:

- `ops/certs/qantara-key.pem`
- `ops/certs/qantara-cert.pem`
- `models/piper/*.onnx`
- `models/piper/*.onnx.json`
- `.venv/`
- `.ruff_cache/`
- `__pycache__/`

Before publishing, verify:

```bash
git ls-files 'ops/certs/*' 'models/piper/*.onnx' 'models/piper/*.onnx.json' '.env' '.env.*'
```

Expected output: only `.env.example` may appear from env files; no certs or model weights should be tracked.

### Allowed Test Secrets

The test suite uses dummy values such as `voice-secret` and `admin-secret`. These are not real credentials and are safe to publish.

## Git History Risk

The private `main` branch still includes prior commits with:

- local LAN IP references
- local filesystem paths
- historical internal notes
- OpenClaw agent validation names

These are not credential leaks, but they are personal/local context. Do not publish that branch history.

Preferred publication path:

1. Publish `public-main` as the public repository's `main` branch.
2. Keep the private `main` branch local/private.
3. Use `git filter-repo` only if you later decide to rewrite the private repo itself.

## Re-Run Commands

```bash
git grep -n -I -E 'ghp_|github_pat_|sk-[A-Za-z0-9]|BEGIN .*PRIVATE KEY|Authorization: Bearer [A-Za-z0-9._-]{20,}' -- .
git grep -n -I -E '/home/|/Users/|192\\.168\\.|10\\.|172\\.|\\.claude' -- .
git ls-files 'ops/certs/*' 'models/piper/*.onnx' 'models/piper/*.onnx.json' '.env' '.env.*'
```

## Security Recommendations Before Public Release

- Publish from `public-main` to avoid exposing private-development history.
- Enable GitHub private vulnerability reporting after the repo is public.
- Keep `QANTARA_AUTH_TOKEN` documented as recommended for LAN use.
- Do not support public internet exposure until explicit threat modeling and rate limiting are done.
- Keep downloaded model files out of git; fetch them with scripts or first-run download flows.
