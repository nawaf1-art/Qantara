# Release Checklist

Use this checklist with [Release process](RELEASE_PROCESS.md) and [Documentation governance](DOCUMENTATION_GOVERNANCE.md). It is version-neutral.

## Source preparation

- [ ] Version matches in `VERSION`, `pyproject.toml`, changelog, README, roadmap, and current release notes.
- [ ] Changelog entry is complete and upgrade notes identify compatibility/security changes.
- [ ] README, feature matrix, configuration, install, API/protocol, and component docs describe implemented behavior only.
- [ ] Every top-level `docs/*.md` document is classified and linked by `docs/README.md`.
- [ ] Historical snapshots carry the standard not-current-guidance marker.
- [ ] Dependency/lock changes were reviewed and audited.
- [ ] No secrets, certificates, logs, model weights, audio, private notes, caches, or unintended large files are tracked or packaged.

## Pull request validation

- [ ] `check_release_consistency.py`, `check_docs_links.py`, and `check_docs_consistency.py` pass.
- [ ] Required CI jobs pass on the exact release commit.
- [ ] Wheel and sdist pass metadata/content checks and clean-install smoke tests.
- [ ] The source distribution contains the current feature matrix and intended public documentation.
- [ ] Docker configuration is valid; a clean build/health check was run when Docker or its dependencies changed.
- [ ] Relevant real backend/browser/device checks and gaps are recorded.
- [ ] Security/privacy, migration, compatibility, and rollback implications were reviewed.

## Owner-controlled release

- [ ] Release PR is merged without rewriting published history.
- [ ] Owner creates the exact protected `vX.Y.Z` tag on the intended commit.
- [ ] Manual release workflow is dispatched from that tag with matching `X.Y.Z` input.
- [ ] Draft assets include wheel, sdist, checksums, SPDX SBOM, validation evidence, and provenance.
- [ ] `sha256sum --check SHA256SUMS` succeeds from the release download directory without path rewriting.
- [ ] The SPDX SBOM identifies `qantara` at the release version and includes the required `aiohttp` runtime dependency.
- [ ] Checksums and validation commit/tag are reviewed independently.
- [ ] Draft notes contain accurate install, upgrade, security, status, and known-gap guidance.
- [ ] GitHub Release is published manually; PyPI remains a separate explicit decision.

## After publication

- [ ] Fresh base and intended-extra installs from the published artifact succeed.
- [ ] README/package install commands name the published version and resolve.
- [ ] Release links, documentation links, checksums, SBOM, validation evidence, and attestations resolve.
- [ ] Version/tag/release are recorded in the project's normal public channels.
- [ ] Any correction uses a new version; published tags and artifacts are not silently replaced.
