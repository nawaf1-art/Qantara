# Support

Qantara is maintained as an open-source project without a guaranteed response or resolution SLA.

## Before opening an issue

1. Check the [Quickstart](docs/QUICKSTART.md), [Troubleshooting](docs/TROUBLESHOOTING.md), and [FAQ](docs/FAQ.md).
2. Confirm the problem still occurs on the latest tagged release or `main` when practical.
3. Run `python scripts/doctor.py` from a source checkout.
4. Reduce the report to a synthetic, non-sensitive reproduction.

Use the structured bug or feature issue form. Include Qantara version/commit, OS, Python version, deployment mode, backend/provider names, steps, and the smallest relevant diagnostic metadata.

## What maintainers can reasonably help with

- reproducible Qantara defects
- documented installation and configuration paths
- adapter/provider contract questions
- scoped feature proposals consistent with the roadmap
- release artifact and documentation problems

Maintainers may not be able to diagnose unsupported public exposure, heavily modified forks, arbitrary model quality, third-party backend behavior, device-specific audio routing, or upstream package/runtime defects.

## Sensitive information

Do not post auth tokens, API keys, `.env` files, private URLs, certificate keys, browser profiles, raw audio, private transcripts, model output, tool arguments, or unredacted logs. Default Qantara event logs redact content, but external runtime and opt-in bridge logs may not.

Security vulnerabilities must use the private process in [SECURITY.md](SECURITY.md), not a support issue.
