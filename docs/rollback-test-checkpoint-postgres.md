# Rollback test for `langgraph-checkpoint-postgres` bumps

A bump of `langgraph-checkpoint-postgres` can change LangGraph's own checkpoint schema
(ADR 0008 decision 7). Rollback is redeploying the previous image, and there are no
down-migrations, so the previous image must still work on the migrated schema. Run this
before merging any bump, including Dependabot's; such a PR is never auto-merged.

You need Docker (or any Postgres 16) and the old and new images or checkouts.

1. Start an empty Postgres and note its DSN. Use throwaway credentials.
2. Build the **previous** image (the current `main`). Run
   `python -m neuron_agent.persistence.cli setup` with `APP_ENV=development` and
   `APP_POSTGRES_MIGRATION_DSN` set to the DSN. Start the previous image with
   `APP_CHECKPOINTER=postgres` and create a thread with one `POST /v1/agent/invoke`.
   Keep its `thread_id`.
3. Build the **new** image (the PR). Run the same `setup` command with it. It must exit 0.
4. Stop the new image. Start the **previous** image again on the same database, without
   running `setup`.
5. Check that the previous image still works on the migrated schema:
   - `GET /health/ready` returns 200;
   - `GET /v1/threads/{thread_id}/messages` returns the thread from step 2;
   - a second `invoke` on that thread succeeds;
   - `GET /v1/me/threads` and `DELETE /v1/threads/{thread_id}` succeed.
6. Run the new image's `setup` once more; it must exit 0 and apply nothing.

If step 4 or 5 fails, the bump is not backward compatible. Do not merge it. Either hold
the bump until a release that ships it as two steps (an expand release, then the bump), or
document the incompatibility in the PR and the ADR. Record the result (image digests, the
checks above, pass or fail) in the PR description.
