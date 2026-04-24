# Release Checklist

Use this before making the repository public and before tagging `v0.2.6`.

## Automated Checks

- [ ] `make test`
- [ ] `ruff check .`
- [ ] `./.venv/bin/python scripts/bench_launch.py --arabic`
- [ ] Docker build succeeds: `docker compose build`
- [ ] Docker first run reaches setup page: `docker compose up`
- [ ] CI passes on Linux, macOS, and Windows

## Manual First-Run Checks

- [ ] Fresh clone on a clean machine or VM
- [ ] Native install from `docs/INSTALLATION_AND_FIRST_RUN_GUIDE.md`
- [ ] Docker install from README quick start
- [ ] Setup page loads at `http://localhost:8765`
- [ ] OpenAI-compatible backend can be configured against a local private/loopback URL
- [ ] Microphone prompt appears on localhost
- [ ] One English voice turn completes
- [ ] Barge-in stops playback and accepts the next turn
- [ ] Arabic turn routes to `ar_JO-kareem-medium` when that Piper voice is installed
- [ ] `/api/status`, `/api/tts`, and `/api/languages` return valid JSON

## Publication Safety

- [ ] `git status --short` is clean
- [ ] `git grep -n -I -E 'ghp_|github_pat_|sk-[A-Za-z0-9]|BEGIN .*PRIVATE KEY' -- .` has no real secrets
- [ ] No tracked local certs or model weights: `git ls-files 'ops/certs/*' 'models/piper/*.onnx'`
- [ ] `docs/SECURITY_PUBLICATION_AUDIT.md` reviewed
- [ ] Public repository will be populated from `public-main`, not private `main`

## GitHub Repository Setup

Recommended description:

```text
Local-first real-time voice gateway for Ollama and other local LLMs, including local AI agents: browser speech, STT, barge-in, TTS.
```

Recommended topics:

```text
voice-ai, local-first, self-hosted, ollama, speech-to-text, text-to-speech, websocket, home-assistant, piper-tts, faster-whisper
```

Before publishing:

- [ ] Set repository description
- [ ] Set topics
- [ ] Add a social preview image if available. Suggested content: Qantara wordmark, "Local voice for Ollama and local LLMs", browser mic -> gateway -> local backend diagram.
- [ ] Enable Issues
- [ ] Enable Discussions only if you intend to monitor them
- [ ] Enable private vulnerability reporting after repository is public
- [ ] Publish good-first issues from the draft list in `docs/PUBLISHING_READINESS_AUDIT.md`

## Tag and Release

Recommended first public tag:

```text
v0.2.6
```

Commands:

```bash
git tag -a v0.2.6 -m "v0.2.6 public launch"
git push <public-remote> public-main:main
git push <public-remote> v0.2.6
gh release create v0.2.6 \
  --title "v0.2.6 - Public launch" \
  --notes-file docs/FIRST_PUBLIC_RELEASE_NOTES_DRAFT.md
```

Do not run these until the blockers in `docs/PUBLISHING_READINESS_AUDIT.md` are resolved or explicitly accepted.
