# Contributing

1. Run `uv sync`.
2. Make focused changes that preserve module boundaries.
3. Add tests for behavior and failure modes.
4. Run `make format lint typecheck test security`.
5. Update docs and ADRs when architecture changes.
6. Follow `docs/AI_CODE_VERIFICATION.md` when AI tools wrote any of the change, and fill in the pull request template.

## Release freeze (ADR 0012, decision 11)

The freeze starts when v0.9.0 is tagged and holds until v1.0.0. Until then `main` takes only:

- bug fixes, documentation, tests, and dependency and security updates;
- changes that keep the `/v1` API, stream protocol version 1, `APP_*` setting names and every
  existing migration compatible. New migrations must be additive (expand, then contract later).

A change that does not fit needs the owner's approval, recorded in the pull request, or waits
until after v1.0.0. v1.0.0 is preceded by release candidates tagged `vX.Y.Z-rc.N` from `main`;
they are published as GitHub pre-releases and never deploy to production.
