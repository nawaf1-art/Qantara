# Supply Chain and Artifact Integrity

Qantara combines ordinary Python packages, large ML wheels, speech/model artifacts, container images, and operator-supplied runtimes. This document distinguishes what the repository pins from what still depends on an upstream mutable reference.

## Dependency surfaces

| Surface | Current safeguard | Remaining operator consideration |
|---|---|---|
| Base Python package | Narrow runtime dependency range in `pyproject.toml`; CI strictly audits the resolved third-party base set | Normal package installs resolve compatible releases at install time |
| Development/test tools | Exact versions in the `dev` extra and CI; CI upgrades to a reviewed `pip` version before installing | Update intentionally through reviewed dependency PRs |
| Full native speech lock | Generated, version-and-hash locked `gateway/transport_spike/requirements.txt` | Regenerate and review when changing speech packages |
| Docker Python/ML lock | Generated, version-and-hash locked `ops/docker/requirements.txt`; pip uses `--require-hashes` | Large multi-index lock requires careful regeneration |
| Docker Python base | Multi-platform image index pinned by SHA256 digest in `Dockerfile` | Debian packages installed during build still come from the configured live apt repository |
| Docker installer | Exact PyPI `pip` wheel URL and SHA256 in `Dockerfile` | Review the official PyPI artifact and audit result before updating |
| spaCy English model in Docker | Exact model release URL and SHA256 fragment | Review compatibility when spaCy changes |
| Ollama container | `ollama/ollama:0.32.3` plus its reviewed multi-architecture manifest digest | Review and update the tag and digest together; Dependabot may propose digest refreshes |
| GitHub Actions | Every third-party Action invocation is pinned to a full commit SHA with a version comment | Dependabot proposes reviewed updates |

## Model downloads

| Artifact | Typical source | Trigger |
|---|---|---|
| faster-whisper model | Hugging Face Hub | First STT model load unless pre-cached |
| Kokoro model/voices | Hugging Face Hub or provider dependency | First TTS use unless pre-cached |
| Piper voice and config | Operator-selected Piper voice source | Manual installation |
| Ollama model | Ollama registry | `ollama pull` or Compose initialization |
| Chatterbox assets | Its configured runtime/upstream | Optional provider initialization |

Qantara does not yet maintain a first-party manifest that pins every model repository revision and file digest. Upstream clients may use content-addressed caches, but a model name or branch alone is not an immutable Qantara guarantee. For sensitive environments, pre-download a reviewed revision, record file hashes, transfer it through a trusted channel, and disable runtime egress.

## Release artifact controls

The manual release workflow runs only from an existing matching `vX.Y.Z` tag selected by an owner. It:

1. verifies tag and source version metadata
2. runs lint, compilation, and the full lightweight unit suite
3. builds wheel and sdist once
4. validates metadata and forbidden/required archive contents
5. installs each artifact into a clean virtual environment and exercises public routes/resources
6. creates an SPDX JSON SBOM
7. writes SHA256 checksums and machine-readable validation evidence
8. generates GitHub build-provenance attestations
9. attaches those exact files to a draft GitHub Release

The workflow does not upload to PyPI and refuses to replace artifacts when a release already exists for the tag. Maintainers review the draft before publication. See [Release process](RELEASE_PROCESS.md).

Until Qantara itself is registered on PyPI, `pip-audit --strict` cannot resolve
an advisory identity for the local `qantara` distribution. CI therefore installs
Qantara to resolve its dependency set, uninstalls only that local distribution,
and audits the third-party packages left in the environment. This is a narrow,
documented exception—not a vulnerability-ID ignore.

## Regenerating hash locks

The runtime locks are generated from their adjacent `.in` files for the minimum supported Python version:

```bash
uv pip compile --universal --generate-hashes --python-version 3.11 \
  --index-strategy unsafe-best-match --emit-index-url \
  --output-file gateway/transport_spike/requirements.txt \
  gateway/transport_spike/requirements.in

uv pip compile --universal --generate-hashes --python-version 3.11 \
  --index-strategy unsafe-best-match --emit-index-url \
  --output-file ops/docker/requirements.txt \
  ops/docker/requirements.in
```

The PyTorch CPU index also mirrors some transitive packages. Pip treats the two
indexes as one candidate pool, so every accepted artifact hash selected from
either reviewed index must be present in the lock. After regeneration, run a
clean `--require-hashes` install (including a no-cache Docker build) and review
any additional artifact hash against its actual index URL before committing it.
Then run tests, package checks, and the dependency audit before merging.

## Offline preparation

For an egress-restricted deployment:

1. Resolve package, container, and model artifacts on a trusted staging machine.
2. Record SHA256 digests and upstream revisions in deployment records.
3. Scan artifacts according to your organization’s policy.
4. Populate the target’s wheelhouse, container store, Hugging Face/provider caches, Piper voice directory, and Ollama model store.
5. Run Qantara with egress denied and verify startup plus one synthetic turn.

Do not copy browser profiles, `.env` files, tokens, private keys, transcripts, audio captures, or unrelated caches as part of this process.

## Maintainer safeguards outside the repository

For the `0.3.1` release line, repository settings enforce safeguards that cannot
be expressed solely in source:

- `main` requires a pull request, an up-to-date branch, all nine CI checks, and
  resolved review conversations; linear history is required and force-pushes or
  branch deletion are blocked, including for administrators
- `v*` release-tag creation is restricted to the repository owner, and matching
  tags cannot be updated or deleted after creation
- Dependency Graph, vulnerability alerts, Dependabot security updates, secret
  scanning, push protection, and private vulnerability reporting are enabled
- release publication remains manual after review of the draft assets and
  validation evidence

The approval count is intentionally zero while no independent trusted reviewer
is designated, because GitHub does not allow a pull-request author to approve
their own change. Increase it to one when another maintainer can reliably review
release and dependency changes.

## Reporting a concern

Suspected malicious or tampered Qantara artifacts should be reported privately through [SECURITY.md](../SECURITY.md). Do not post tokens, suspicious payload contents, or private deployment details in a public issue.
