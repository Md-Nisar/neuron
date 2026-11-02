## Summary

<!-- What changes and why. Link the issue. -->

## AI assistance

<!-- Pick one and name the tool and model. Disclosure is for audit, not judgment:
     every PR meets the same bar. -->
- [ ] None
- [ ] Assisted (AI suggested parts; I wrote or rewrote the rest)
- [ ] Agent-generated (an AI agent wrote most of the change)

Tool / model:

## Risk tier

<!-- docs/AI_CODE_VERIFICATION.md#risk-tiers -->
- [ ] Critical: security/, config/, tools/, prompts/, persistence/, auth, API surface, CI, Dockerfile, deploy/
- [ ] Standard: features, services/, graphs/, agents/, models/, observability/
- [ ] Low: docs, tests only, comments, formatting

## Verification

- [ ] I have read every changed line and can explain it without the AI
- [ ] New behaviour has tests that fail without this change
- [ ] `make format lint typecheck test security` passes locally
- [ ] No new dependency, or each new one is necessary and verified as the intended project
- [ ] Security-relevant changes checked against SECURITY.md and AGENTS.md forbidden patterns
- [ ] Docs and ADRs updated where architecture or behaviour changed

## Notes for the reviewer

<!-- Where to look hardest, what you are unsure about, what you did not test. -->
