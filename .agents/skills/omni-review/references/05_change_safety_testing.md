# Pass 5: Change Safety, Tests, Migrations and Dependencies

Correct code can still cause an incident on the way to production. This pass asks: will this
change deploy, roll out, and roll back safely, and will the tests catch the next regression?

## 1. Test Adequacy
- **Changed behavior without tests:** for each behavioral change in the diff, find a test that
  would fail if the change were reverted. If none exists, report it under Test Gaps with the
  cheapest test that would cover it.
- Missing negative and edge cases: authorization denial, empty input, boundary values, error
  paths, concurrent access, retries/redelivery.
- **Tests that cannot fail:** no assertions, assertions on mocks only, `assert True`, catching the
  exception the test should surface, snapshot tests blindly updated.
- **Over-mocking:** mocking the ORM or HTTP layer so thoroughly that query bugs, serialization
  issues, or transaction behavior are never exercised; a small integration test (e.g.
  Testcontainers or an in-memory server) may be warranted.
- **Flakiness sources:** `sleep`-based waits, real wall-clock time, test-order dependence, shared
  global state, unseeded randomness, reliance on network.
- Tests disabled or skipped in the diff (`@Disabled`, `.skip`, `xit`, `pytest.mark.skip`)
  without an explanation or tracking ticket.

## 2. Database Migrations
- **Locking DDL on large or hot tables:** adding columns with volatile defaults or `NOT NULL`
  without defaults on engines that rewrite the table, creating indexes without `CONCURRENTLY`
  (Postgres) or online DDL (MySQL), changing column types, adding foreign keys that validate
  existing rows in one step.
- Data backfills inside schema migrations (long transactions, deploy timeouts); do them in
  batched jobs instead.
- **Mixed-version safety:** during a rolling deploy, old and new code run against the same
  schema. Dropping or renaming a column that old code still reads breaks the old pods. Use
  expand → migrate → contract across releases.
- Irreversible migrations with no documented rollback; down-migrations that silently lose data.
- Constraints added without checking that existing data satisfies them.

## 3. Rollout and Rollback
- New serialized formats (cache entries, queue messages, stored JSON, cookies) that the old
  version cannot read; rolling back would break.
- Behavior changes for existing users with no feature flag or gradual rollout on risky paths.
- Feature flags without a safe default or a removal plan.
- Order-of-deploy dependencies between services that are not documented or enforced (consumer
  must deploy before producer).

## 4. Dependencies and Supply Chain
- New dependencies: is the capability already available in the repo or the standard library? Is
  the package maintained, widely used, and appropriately licensed for this project?
- Version changes in lockfiles: major-version bumps hiding breaking changes; known-vulnerable
  versions (recommend running the ecosystem's audit tool: `npm audit`, `pip-audit`,
  `mvn dependency-check`, `govulncheck`, `cargo audit`).
- Unpinned or floating versions (`latest`, `*`, broad ranges) in production builds; Docker images
  without pinned tags or digests.
- Install scripts or build plugins with network access added without justification.

## 5. Configuration and Infrastructure
- New environment variables or config keys without defaults, documentation, or startup validation.
- Secrets added to config files, CI files, or Dockerfiles instead of a secret manager.
- IaC changes granting overly broad permissions (`*` actions/resources, public ingress, public
  buckets), or removing encryption or logging.
- Resource limits (memory, CPU, timeouts, concurrency) changed without justification for the
  new load profile.

## 6. Operability
- Breaking or user-visible changes without changelog or migration notes.
- New failure modes without alerts or runbook guidance when the area already has them.

## Common False Positives in This Pass
- Missing tests for trivial code (getters, pure wiring) or code already covered by higher-level
  tests; check before flagging.
- Index creation or DDL on tables known to be small (state the size when dismissing).
- Lockfile churn from routine tooling updates with no version changes of substance.
