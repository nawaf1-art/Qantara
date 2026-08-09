## Summary

Describe the user-visible outcome and why the change is needed.

## Linked issue or design

Link the issue/ADR, or explain why this is a small direct fix.

## Validation

- [ ] Relevant focused tests pass
- [ ] `python -m unittest discover -s tests -v` passes
- [ ] `ruff check .` passes
- [ ] Packaging/release checks run when metadata or artifacts changed
- [ ] Manual backend/browser/device checks are listed below when relevant

Manual validation and known gaps:

## Compatibility, security, and privacy

- [ ] Public imports, events, environment variables, and resource paths remain compatible, or migration notes are included
- [ ] No secrets, private data, logs, audio captures, model weights, or certificates are included
- [ ] Input, output, queue, task, subprocess, and network boundaries were considered
- [ ] Documentation and feature status changed with public behavior

## AI assistance

Disclose substantial AI-assisted generation or transformation, if any, and confirm the complete diff was human-reviewed:
