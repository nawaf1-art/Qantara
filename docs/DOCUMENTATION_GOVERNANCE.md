# Documentation Governance

This document defines how Qantara documentation is organized, which documents are authoritative, and what “documentation complete” means for a pre-1.0 release.

Current source and published release line: `0.3.1`.

## Authority order

Documentation explains the implementation; it does not override it. When two sources disagree, resolve the conflict in this order and update the lower-level source in the same change:

1. Executable implementation, schemas, and tests
2. Versioned protocol and public API contracts
3. Current architecture, feature, configuration, security, and installation guides
4. Release changelog and tagged release evidence
5. Maintainer planning material
6. Historical snapshots

The most useful canonical entry points are:

| Question | Canonical source |
|---|---|
| What version is this? | `VERSION`, `pyproject.toml`, `qantara/version.py`, then the checked markers in `README.md`, `CHANGELOG.md`, and `ROADMAP.md` |
| What is shipped? | `docs/FEATURES.md` plus `CHANGELOG.md` |
| How is the system divided? | `ARCHITECTURE.md` |
| What does an adapter implement? | `adapters/base.py`, `adapters/CONTRACT.md`, and `protocols/agent.md` |
| How do sessions behave? | `gateway/transport_spike/runtime.py`, `gateway/SESSION_MODEL.md`, and `protocols/agent.md` |
| How is Qantara installed? | `docs/INSTALLATION_AND_FIRST_RUN_GUIDE.md` |
| How is startup configured? | `docs/CONFIGURATION.md` and `docs/CLI.md` |
| What does the Python package expose? | `docs/PYTHON_SDK.md` |
| What are the HTTP Voice API contracts? | `docs/VOICE_API.md` and `docs/examples/clients/` |
| What are the trust boundaries? | `SECURITY.md`, `docs/PRIVACY.md`, and `docs/SUPPLY_CHAIN.md` |
| What proves a release? | The tagged GitHub Release, `SHA256SUMS`, SPDX SBOM, `release-validation.json`, and `docs/releases/` |
| What is planned rather than shipped? | `ROADMAP.md` |

## Document classes

### Current guidance

Current guidance describes the checked-out source and the current release line. It must use the status vocabulary in `docs/FEATURES.md`: **Beta**, **Experimental**, **Planned**, and **Deprecated**.

### Versioned release history

Release notes and changelog entries describe a named historical version. They may retain version-specific commands and limitations, but must not imply that an old version is the current release.

### Maintainer material

Demo scripts, marketing copy, issue candidates, and release checklists are working material. They must defer product-availability claims to the feature matrix and must be revalidated before public reuse.

### Historical snapshot

Audits, cleanup reports, draft release notes, and handoffs preserve what was known at a specific date. Every historical snapshot must begin with this marker:

```markdown
> [!NOTE]
> **Historical snapshot — not current product guidance.** ...
```

Historical snapshots are evidence, not backlog or status. Open items in an old audit are not automatically current work.

## Required update matrix

| Change type | Documentation that must be reviewed |
|---|---|
| User-visible feature | README, feature matrix, relevant guide, changelog |
| Adapter or backend | Architecture, adapter contract/README, configuration, feature matrix, relevant integration guide |
| STT/TTS provider | Provider README, configuration, installation extras, feature matrix |
| HTTP/WebSocket/protocol behavior | Relevant API/protocol document, examples, architecture, tests |
| Environment variable or CLI flag | Configuration reference, CLI reference, example config/env files |
| Security or privacy boundary | Security policy, privacy guide, architecture, configuration, changelog |
| Package contents or extras | `pyproject.toml`, installation guide, Python SDK guide, package checks |
| Release workflow | Release process, checklist, supply-chain guide, workflow documentation |
| Status or roadmap change | Feature matrix, roadmap, README, changelog when shipped |

## Completeness gate

Qantara treats documentation as reconciled when all of the following are true:

- every top-level document under `docs/` is classified and linked from `docs/README.md`
- current guides agree with the implementation and current release line
- historical snapshots carry the standard warning marker
- component READMEs and contracts use current terminology
- local Markdown links resolve across the repository
- the feature matrix is included in source distributions
- startup precedence is documented exactly as implemented
- release metadata consistency, package-content checks, and documentation checks pass in CI

Run the documentation checks from a source checkout:

```bash
python scripts/check_release_consistency.py
python scripts/check_docs_links.py
python scripts/check_docs_consistency.py
```

These checks prevent known classes of drift. They do not replace review of behavior-specific claims when implementation changes.

## Review ownership

A pull request that changes behavior owns its documentation update. Documentation-only corrections should cite the implementation, test, schema, or release evidence used to resolve the discrepancy. Architecture changes require an accepted decision record before current architecture guidance is rewritten.
