# Publishing Readiness Audit

Date: 2026-04-24

## Verdict

Qantara is almost ready to publish, but not until clean-machine validation, CI, and GitHub repository setup are complete.

Current readiness score after the clean public branch step: **88 / 100**.

## Blockers

1. **Publish the clean branch, not private `main`**
   - The `public-main` orphan branch is intended for GitHub publication.
   - Do not push the private `main` branch to a public repository because it keeps the old private development history.

2. **Clean-machine validation**
   - Docker and native install instructions need one final run on a machine or VM that has not accumulated local models, certs, and Python caches.

3. **Cross-OS CI/public release validation**
   - CI should pass on Linux, macOS, and Windows after the public-ready cleanup.

4. **GitHub repository settings**
   - Set description, topics, Issues, and private vulnerability reporting after publication.

## Non-Blocking Improvements

- Add actual screenshots or a short demo later if desired.
- Add a small `docs/examples/openai-compatible.md` with backend-specific examples.
- Publish the good-first issues listed below.
- Add a proper Python package layout only if PyPI distribution becomes a goal.
- Add a Home Assistant add-on package after the public release if users ask for it.
- Add a `/voice` or `/app` alias later so the historical `/spike` URL can be retired cleanly.

## What Was Audited

- Repository tree and tracked files
- Public docs and old internal docs
- Source comments and config examples
- `.gitignore`, `.dockerignore`, local generated artifacts
- GitHub community files
- Install paths and first-run docs
- Security posture and sensitive-data exposure
- Versioning, packaging, and release checklist
- Test and benchmark coverage

## What Was Fixed

- Removed tracked `docs/internal/` private-development notes from the public tree.
- Added clean publication audit and handoff documents.
- Added `.env.example`.
- Sanitized local IP and OpenClaw agent examples.
- Rewrote `ARCHITECTURE.md` as backend-agnostic public architecture.
- Added public documentation map.
- Added installation, configuration, developer onboarding, release checklist, and release notes draft docs.
- Updated README to point to the new public docs.
- Updated `.gitignore` for common local artifacts.
- Created the `public-main` orphan branch plan so the first public commit can avoid private development history.

## Installability Assessment

Status: **Good, with clean-machine validation still required**.

Strengths:

- Docker quick start exists.
- Native venv path exists.
- Setup page guides backend selection.
- Troubleshooting covers microphone, backend, voice, and LAN issues.

Risks:

- First-run dependency/model downloads are large and may surprise users.
- Docker build depends on several large Python/ML packages.
- Browser mic behavior depends on HTTPS when accessed from another LAN device.

## Documentation Assessment

Status: **Good after this pass**.

Public docs now have:

- README overview
- documentation map
- install guide
- config guide
- architecture overview
- troubleshooting
- developer onboarding
- release checklist
- security policy
- supply-chain notes
- first release notes draft

## Open Source Community Readiness

Present:

- `LICENSE`
- `CONTRIBUTING.md`
- `CODE_OF_CONDUCT.md`
- `SECURITY.md`
- issue templates
- PR template
- changelog
- release-drafter workflow

Recommended repo description:

```text
Local-first real-time voice gateway for AI agents: browser mic, STT, barge-in, TTS, and local backend adapters.
```

Recommended topics:

```text
voice-ai, local-first, self-hosted, ollama, speech-to-text, text-to-speech, websocket, home-assistant, piper-tts, faster-whisper
```

## Packaging and Versioning

Status: **Ready for GitHub release, not ready for PyPI distribution**.

Current source of truth:

- `VERSION`
- `pyproject.toml`
- `CHANGELOG.md`

Recommended first public tag:

```text
v0.2.6
```

Do not advertise `pip install qantara` yet. The repo currently uses direct script execution and Docker, not a finalized package/module layout.

## Test Confidence

Automated confidence is solid for a pre-1.0 release:

- gateway HTTP and WebSocket behavior
- backend contracts
- interruption/barge-in regressions
- language routing
- TTS provider contracts
- mesh and Wyoming protocol pieces
- voice registry schema

Validation run during this pass:

- `ruff check .`
- `./.venv/bin/python -m unittest discover -s tests -v` — 156 tests passed
- `./.venv/bin/python -m compileall -q adapters gateway providers scripts tests cli.py config.py discovery`
- `./.venv/bin/python scripts/bench_launch.py --json --barge-in-iterations 3 --tts-iterations 1`
- `git diff --check`

Remaining manual validation:

- fresh Docker first run
- fresh native install
- browser mic permission on localhost
- LAN HTTPS with trusted cert
- one real local backend voice conversation
- Arabic voice route if Arabic Piper voice installed

## Good-First Issue Drafts

Use these as first public issues:

1. Add JSON output to `scripts/doctor.py`
2. Add a LAN readiness mode to `scripts/doctor.py`
3. Document OpenAI-compatible backend examples
4. Add a setup-page smoke test for advanced backend badges
5. Add troubleshooting for browser autoplay and output-device issues
6. Add a voice registry contribution guide
7. Add a demo recording checklist for Arabic voice routing
8. Add backend discovery contract docs
9. Improve `make test` docs for targeted test runs
10. Add a minimal provider fixture for contributor tests

## Signoff Needed

- Confirm that the public repository will be populated from `public-main`, not private `main`.
- Confirm repository owner/name and public GitHub URL.
- Confirm whether screenshots/demo media are intentionally deferred.
- Confirm first public version tag: `v0.2.6`.
- Confirm whether OpenClaw bridge remains included as advanced optional.
