# AI Code Verification

How changes to Neuron are verified when AI assistants (Claude Code, Copilot, others) write
some or all of the code. The policy is based on what well-run engineering organizations do
(Google, Meta, Microsoft, Uber, Atlassian, Cloudflare, the Linux kernel, Mozilla) and on the
evidence summarized in the research doc
[Verifying and Reviewing AI-Generated Code](https://claude.ai/code/artifact/d004ef16-157a-41e3-bd63-790b9173c615).

See also [ai-code-verification/research.md](ai-code-verification/research.md) (the research) and
[ai-code-verification/implementation.md](ai-code-verification/implementation.md) (what was built here).

## Principles

1. **Same bar for all code.** AI-written code is held to the same standard as human code
   (NIST SP 800-218A). Review depth follows risk, not authorship.
2. **A human owns every merge.** The PR author must be able to explain every changed line
   without the AI. AI tools may comment, suggest and fix; they never approve or merge.
3. **Machines first.** Nothing reaches a human reviewer until the deterministic gates pass.
4. **Tests must prove they catch bugs.** AI-written tests are checked for strength, not just
   for passing.
5. **Measure outcomes.** Revert rate and escaped defects matter more than review speed.

## The pipeline

| Layer | What runs | Where | Blocking |
| --- | --- | --- | --- |
| 1. Local | `make format lint typecheck test security`; Claude Code hooks format and lint every edit and block writes to `.env` and `uv.lock` | Developer machine, `.claude/settings.json` | Yes (by convention) |
| 2. Deterministic gates | ruff (incl. bandit `S` rules), mypy strict, unit/graph/security/resilience/eval tests on Linux and Windows, bandit, pip-audit | `ci.yml` | Yes |
| 2. Deterministic gates | Secret scanning (gitleaks), dependency review (vulnerabilities, licenses), new-package check against PyPI (hallucinated or brand-new packages), PR size limit, PR description check | `ai-code-verification.yml` | Yes |
| 2. Deterministic gates | CodeQL `security-extended` for Python and workflows | `codeql.yml` | Yes |
| 3. Test strength | Mutation testing of `security/` and `tools/` (mutmut), weekly | `mutation-testing.yml` | Report only, for now |
| 3. Test strength | Live agent evals with a pass^k = 100% security gate, nightly | `nightly-eval.yml` | Yes (nightly) |
| 4. AI review | A frontier model from NVIDIA's free API catalog reviews the diff against `.claude/agents/*`, `AGENTS.md` and `SECURITY.md`; a second call verifies each finding; survivors are posted as one comment-only review | `ai-review.yml`, `scripts/ai_review.py` | No, advisory |
| 5. Human review | Code owner review for critical paths, one reviewer otherwise | `CODEOWNERS`, branch protection | Yes |

## Risk tiers

| Tier | Paths | Required before merge |
| --- | --- | --- |
| Critical | `src/neuron_agent/security/`, `config/`, `tools/`, `prompts/`, `persistence/`, `api/`, `tests/security/`, `.github/`, `.claude/`, `Dockerfile`, `deploy/`, `pyproject.toml`, `uv.lock`, `SECURITY.md`, `AGENTS.md`, `docs/decisions/` | All gates, AI review findings resolved or answered, code owner approval. Tools and graph changes follow the `add-tool` / `add-graph-node` skills. |
| Standard | `services/`, `graphs/`, `agents/`, `models/`, `observability/`, `schemas/`, `state/` | All gates, one human approval |
| Low | Docs, tests only, comments | All gates, one human approval |

The PR template asks the author to pick the tier; reviewers correct it if it is wrong.

## Rules for AI-assisted changes

- Disclose AI assistance in the PR template. Keep the `Co-Authored-By:` trailer that Claude
  Code adds to commits; it is the provenance record.
- Work in small batches. PRs over 400 changed lines get a warning and over 1,000 fail
  unless a maintainer adds the `large-pr-approved` label. Generated files do not count.
- Write or review the tests first. A new behaviour needs a test that fails without the change.
- New dependencies: the `new-dependencies` job fails if a package does not exist on PyPI
  (a likely hallucination) or its first release is under 90 days old. A maintainer who has
  vetted a young package adds the `new-dependency-approved` label. Either way, a reviewer
  confirms the package is the intended project.
- Never let an agent edit `.env`, `uv.lock` or the virtualenv directly (enforced by the
  Claude Code `PreToolUse` hook); run `uv lock` / `uv sync` instead.
- The forbidden patterns in `AGENTS.md` apply unchanged: no `eval` or shell tools, no
  prompt-only security controls, no live LLM calls in unit tests, no committed secrets.

## Reviewer checklist

- Does the change do what the PR says, and nothing else? AI tends to add unrequested code.
- Would the tests still pass if the change were reverted?
- Is untrusted input (user input, tool output, model output) validated in code?
- Are failure modes handled (timeouts, provider errors, empty results)?
- Is there duplicated logic that already exists elsewhere in the codebase?
- For each AI review finding: fixed, or answered with a reason.

Approving means you would have been comfortable writing this code yourself.

## One-time GitHub setup

1. Make sure the `NVIDIA_API_KEY` repository secret exists (it is already used by
   `nightly-eval`; get a free key at build.nvidia.com). Optionally set the repository
   variable `AI_REVIEW_MODELS` to a comma-separated list of model ids to try in order;
   the default is `z-ai/glm-5.3,moonshotai/kimi-k3,deepseek-ai/deepseek-v4.1-flash`.
   Free-tier models change often, so confirm the ids with
   `curl -s -H "Authorization: Bearer $NVIDIA_API_KEY" https://integrate.api.nvidia.com/v1/models`.
   The free tier is rate limited (about 40 requests a minute) and is not meant for
   production; each review uses two requests. Without the key the review skips itself.
2. Create the labels `large-pr-approved` and `new-dependency-approved`.
3. Enable the dependency graph and, for a private repository, GitHub Advanced Security
   (needed by `dependency-review` and CodeQL).
4. Protect `main`: run `scripts/setup_branch_protection.sh` (needs the `gh` CLI with admin
   rights) or set it by hand: require a PR, one approval, code owner review, dismissal of
   stale approvals, conversation resolution, and these status checks: `checks (ubuntu-latest)`,
   `checks (windows-latest)`, `secrets-scan`, `dependency-review`, `new-dependencies`,
   `pr-hygiene`, `analyze (python)`, `analyze (actions)`.
5. With a single maintainer, code owner review cannot be satisfied by the author; add a
   second maintainer or a team to `CODEOWNERS` before turning that setting on.

## Metrics

Review monthly, starting from a baseline taken before rollout.

| Metric | Source | Watch for |
| --- | --- | --- |
| Revert rate and hotfixes per release | git history, `CHANGELOG.md` | Any rise after more AI-written code |
| Escaped defects and security findings | issues, CodeQL, AI review | Findings per 1,000 changed lines |
| AI review comments acted on | PR comments | Below about 40% means it is noisy; tune the prompt |
| PR size and time to first review | GitHub insights | Large PRs reviewed in minutes suggest rubber-stamping |
| Surviving mutants in `security/` and `tools/` | `mutation-testing` summary | Survivors are missing tests |
| Live eval pass rates | `nightly-eval` reports | Regressions against the baseline |

## Rollout

1. **Now:** merge these files; add the secret and labels; turn on branch protection with the
   existing `ci` checks plus `secrets-scan`, `new-dependencies` and `pr-hygiene`.
2. **After two weeks:** add `dependency-review` and CodeQL as required checks once they run
   clean; review AI comment quality and tune the prompts in `scripts/ai_review.py` or switch models.
3. **After a month:** triage surviving mutants, add tests, and consider making mutation
   testing a blocking check for `security/` with a minimum score.
