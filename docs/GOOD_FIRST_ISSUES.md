# Good First Issue Candidates

> [!NOTE]
> Maintainer planning material. Re-check the current implementation, open issues, and feature matrix before filing any item; this list is not a statement that a defect is still open.

These candidates are intentionally small and should preserve Qantara's local-first defaults, framework-free browser client, bounded inputs/state, and existing public contracts.

## Documentation and diagnostics

1. Add JSON output to `scripts/doctor.py` without changing the human-readable default.
2. Add a trusted-LAN readiness mode to `scripts/doctor.py` covering token, TLS, Host/Origin, and bind settings.
3. Add one backend-specific example under `docs/examples/` after verifying it against a current local server.
4. Add troubleshooting for browser autoplay/output-device selection using reproducible browser steps.
5. Add a voice-registry contribution guide covering licensing, locale, sample rate, defaults, transforms, and fetch policy.

## Tests and contributor experience

6. Add a small deterministic provider fixture that demonstrates the STT/TTS contract without downloading a real model.
7. Add focused tests for a documented configuration edge case that is not already covered.
8. Add a setup-page smoke assertion for one current advanced-backend badge or error state.
9. Improve targeted-test examples in developer documentation when a genuinely useful missing pattern is identified.
10. Add a repository test ensuring a newly documented public asset is present in both wheel/sdist as appropriate.

## Before filing

For each proposed issue:

- verify the work is not already implemented or covered by an open PR
- cite the current file/test/guide that establishes the gap
- define acceptance criteria and non-goals
- identify required documentation and tests
- avoid bundling unrelated refactors
- mark any real model, browser, OS, or device validation that cannot run in CI

Use the repository's issue forms rather than copying this file verbatim.
