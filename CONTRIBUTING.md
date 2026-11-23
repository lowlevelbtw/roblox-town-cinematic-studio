# Contributing

Thanks for considering a contribution to Roblox Town Cinematic Studio.

## Before opening a change

1. Check existing issues and documentation to avoid duplicate work.
2. Keep changes focused; separate unrelated refactors.
3. Explain the user or production problem the change addresses.
4. Include a reproducible test or evaluation path.

## Development checks

Run the relevant tests from the repository root:

```bash
python3 -m unittest discover -s tests -v
```

For changes to skill behaviour, update the relevant evaluation scenario or add a new one. For script changes, include regression coverage where practical.

## Documentation and claims

- Distinguish implemented, configured, mocked, blocked, and live-verified behaviour.
- Do not report tests as passing unless they were actually run.
- Do not claim an external integration works without verifying it in that environment.
- Keep examples original and respect asset, music, and participant rights.

## Pull requests

A useful pull request includes:
- **Problem:** what is wrong or missing?
- **Approach:** what changed and why?
- **Validation:** exact commands run and their results.
- **Limitations:** anything not tested or still dependent on external access.

By contributing, you agree that your contribution is submitted under the repository's MIT license.
