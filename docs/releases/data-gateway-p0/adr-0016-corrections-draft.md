# ADR 0016 corrections (approved and applied)

| Field | Value |
| --- | --- |
| Status | **Approved and applied** to ADR 0016 on 2026-11-25, all five corrections (D30). Drafted under D14 and D29 |
| Date | 2026-11-25 |
| Source | The P0 spike: [`design-spike-log.md`](design-spike-log.md), findings F1, F6, F9, F11, F12; decisions D13, D18, D28 |
| Changes | Decision 3 (one sentence), decision 5 (replaced), decision 7 (two bullets), decision 8 (one sentence), one new consequence. Status, context, product requirement and every other decision are unchanged |

Each correction gives the current text, the proposed text and the evidence. Corrections 1 to 4
are what the spike found the ADR to state wrongly. Correction 5 is optional: it writes the
owner's D28 rule into the ADR, and the owner may prefer to leave it to P1.

## 1. Decision 5, database hardening (F1, F1b, F1c, F6, D18)

**Current:**

> 5. **Database hardening.** Required in Neuron's test mart and reference deployment, and
>    recommended to customers:
>    - `set_config` is revoked from PUBLIC;
>    - row-level security is forced and fails closed;
>    - claims are set only by the gateway.
>
>    Role-level mapping comes first; `neuron.user_sub` is set for customers who key policies on
>    the subject.

**Proposed:**

> 5. **Database hardening.** Required in Neuron's test mart and reference deployment, and
>    recommended to customers:
>    - row-level security is forced and fails closed;
>    - policies are keyed on the database role (`current_user`), through a mapping table only an
>      administrator can write. No policy reads a session setting;
>    - each data role has its own login, which is a member of that role only, so neither `SET
>      ROLE` nor `RESET ROLE` can widen what a session sees.
>
>    Per-user policies (keyed on the subject) are not supported. They need claims the session
>    cannot forge, and a new decision.

**Why.** The current text describes a design the spike showed unsafe:

- **F1.** `SET LOCAL app.regions = ...` rewrites a claim without `set_config`. Revoking
  `set_config` does not cover the `SET` command, and an EMEA analyst saw 1,057 APAC orders.
- **F1b.** `RESET ROLE` returns to the login, which can call the claims function with any regions.
  Signing the claims does not help, since it protects a value, not who chose it.
- **The fix the mart uses (F1 resolution, option A').** Role-keyed policies and one login per
  data role. The checker passes 158 checks and catches three deliberate breaks.
- **F6 and D18.** Revoking `set_config` stops Auto Ontology from running any read-only query,
  because its connector sets `read_only` with `set_config`. Under A' no authorization depends on
  a setting, so the revoke protects nothing, and the spike granted it back to Auto Ontology's
  login.

`neuron.user_sub` is dropped for the same reason as the claims (F1): a setting the session can
write cannot carry identity. Option B' (signed claims plus a per-login entitlement check) is
recorded in the log as the path, if a customer needs per-user policies.

## 2. Decision 3, the statement timeout (F1c)

**Current:**

> - with a statement timeout and a row cap.

**Proposed:**

> - with a statement timeout the executor sets inside the transaction (`SET LOCAL`), immediately
>   before the statement, and a row cap. A role's default timeout is not relied on.

**Why (F1c).** `SET LOCAL statement_timeout = 0` lifts a role's default, and PostgreSQL 16 has no
`transaction_timeout`. Only the executor's own setting, plus one validated statement, holds. The
spike's checker reports this as `KNOWN`, not as a pass.

## 3. Decision 7, certification and Ossie (D13, F11)

**Current:**

> - Semantic content is Apache Ossie YAML under version control, and only certified terms are
>   served.

**Proposed:**

> - Semantic content is Apache Ossie YAML under version control, and only certified terms are
>   served. Ossie core has no notion of certification, so certified status is recorded in a
>   `neuron` entry under `nonportable_extensions`. Neuron's files are the only source of
>   certification: an engine's own flags and exports are never read for it.

**Why.**
- **D13.** Ossie (`main` at `91689e6`, spec `0.3.0.dev0`) has no "certified" field.
- **F11.** Auto Ontology's export, native or Ossie, carries no certification flag: after a round
  trip all 16 terms and all 13 SQL attributes came back uncertified.

## 4. Decision 7 and decision 8, Auto Ontology (F9, F12, section 13)

**Current (decision 7):**

> - NVIDIA Auto Ontology is an optional adapter, pinned to a commit, and only after spike S2
>   passes.

**Proposed:**

> - NVIDIA Auto Ontology is an optional adapter, pinned to a commit, and only after spike S2
>   passes. It is loaded one way, from Neuron's Ossie files; Neuron never relies on exporting a
>   model back out of it.

**Current (decision 8):**

> By default an engine sends the model only the schema and certified terms; sample values and rows
> need the source's policy.

**Proposed:**

> By default an engine sends the model only the schema and certified terms; sample values and rows
> need the source's policy. An engine that sends sample values while compiling (Auto Ontology,
> F9) may be used only on sources whose policy allows it, or with every column the policy excludes
> tagged so the engine skips it.

**Why.**
- **F12.** The Ossie round trip loses content:
  - 9 of the hand-written model's 12 metrics are dropped (the dataset-scoped ones);
  - two relationships between the same pair of tables fail the import;
  - a database Auto Ontology has already catalogued cannot be imported;
  - the export writes metrics as fields, so it exports 0 metrics.
- **S4 failed for this reason** (decision record). So the one-way load is the only direction the
  measurements support.
- **F9 and section 13.** Compilation puts sample column values in the model prompt. Release 1.3.0
  lets columns tagged as PII skip this, so the rule can be "tag the excluded columns" rather than
  "never".

## 5. Optional: values outside the caller's scope (D28)

**Proposed addition to the product requirement**, after "Otherwise they receive an explicit
statement that the data does not hold the answer":

> A question about a named value that exists only outside the caller's data permissions (for
> example a customer in another region) is refused with that reason, not answered with zero.

**Why.** The owner's D28 rule. The spike's value check v4 enforces it under the caller's own role,
with no lookup outside their permissions. Leave it out if the owner prefers to settle it in P1
design.

## New consequence (with correction 1)

> - Each data scope is a database role with its own login, so the gateway holds one credential
>   per scope, and roles grow with scopes. Per-user row policies wait for a decision on
>   unforgeable claims.

## Not ADR text: items for Auto Ontology's security review

These findings bear on the conditional GO, but they are operating conditions, not decisions. They
belong in the security review the decision record keeps open:

- **F7.** The MCP server has no service credential. A gateway would call the REST routes with a
  user's API token.
- **F8.** The backend trusts an unauthenticated user header and binds `0.0.0.0`. It must be
  reachable only through its own gateway.
- **F14.** Every worker opens a pool to every connected database.
