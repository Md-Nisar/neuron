$ErrorActionPreference = "Stop"

$repo = "Md-Nisar/neuron"
$milestoneTitle = "v0.2.0 - Reliable Agent Runtime"

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " Neuron v0.2.0 Issue Bootstrap" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

# ------------------------------------------------------------
# 1. Verify GitHub CLI
# ------------------------------------------------------------

Write-Host "[1/5] Checking GitHub CLI authentication..." -ForegroundColor Yellow

gh auth status

Write-Host ""
Write-Host "GitHub authentication OK." -ForegroundColor Green


# ------------------------------------------------------------
# 2. Create milestone if it does not exist
# ------------------------------------------------------------

Write-Host ""
Write-Host "[2/5] Checking milestone..." -ForegroundColor Yellow

$milestonesJson = gh api "repos/$repo/milestones?state=all&per_page=100"
$milestones = $milestonesJson | ConvertFrom-Json

$existingMilestone = $milestones |
    Where-Object { $_.title -eq $milestoneTitle }

if ($existingMilestone) {

    $milestoneNumber = $existingMilestone.number

    Write-Host "Milestone already exists: #$milestoneNumber" -ForegroundColor Green
}
else {

    Write-Host "Creating milestone: $milestoneTitle" -ForegroundColor Yellow

    $milestoneNumber = gh api `
        --method POST `
        "repos/$repo/milestones" `
        -f "title=$milestoneTitle" `
        -f "description=Reliable Agent Runtime for Neuron v0.2.0" |
        ConvertFrom-Json |
        Select-Object -ExpandProperty number

    Write-Host "Created milestone #$milestoneNumber" -ForegroundColor Green
}


# ------------------------------------------------------------
# 3. Create labels
# ------------------------------------------------------------

Write-Host ""
Write-Host "[3/5] Creating labels..." -ForegroundColor Yellow

$labels = @(
    @{
        name = "v0.2.0"
        color = "5319E7"
        description = "Work targeted for Neuron v0.2.0"
    },
    @{
        name = "priority:p0"
        color = "B60205"
        description = "Critical for the release"
    },
    @{
        name = "priority:p1"
        color = "D93F0B"
        description = "Important for the release"
    },
    @{
        name = "reliability"
        color = "0E8A16"
        description = "Runtime reliability and resilience"
    },
    @{
        name = "security"
        color = "B60205"
        description = "Security and abuse prevention"
    },
    @{
        name = "testing"
        color = "1D76DB"
        description = "Tests and verification"
    },
    @{
        name = "observability"
        color = "5319E7"
        description = "Logging, tracing and telemetry"
    },
    @{
        name = "evaluation"
        color = "7057FF"
        description = "Agent quality evaluation"
    },
    @{
        name = "documentation"
        color = "0075CA"
        description = "Documentation and operational guidance"
    }
)

foreach ($label in $labels) {

    try {

        gh label create $label.name `
            --repo $repo `
            --color $label.color `
            --description $label.description `
            --force | Out-Null

        Write-Host "  OK: $($label.name)" -ForegroundColor DarkGreen
    }
    catch {

        Write-Host "  Warning: $($label.name)" -ForegroundColor DarkYellow
    }
}


# ------------------------------------------------------------
# 4. Issue definitions
# ------------------------------------------------------------

Write-Host ""
Write-Host "[4/5] Creating v0.2.0 issues..." -ForegroundColor Yellow

$issues = @(

    @{
        key = "01"
        title = "Define Runtime Error Taxonomy"
        labels = @("v0.2.0", "priority:p0", "reliability")
        body = @"
## Goal

Define a stable application error taxonomy for Neuron so provider,
tool, validation, timeout, structured-output, and internal failures
are distinguishable and consistently handled.

## Scope

Define typed/domain errors for:

- configuration errors
- request validation errors
- provider failures
- rate-limit failures
- provider timeouts
- tool failures
- structured-output failures
- agent execution failures
- unexpected internal failures

Define which failures are:

- retryable
- non-retryable
- safe to expose to clients
- internal-only

Define a consistent mapping to HTTP responses.

## Acceptance Criteria

- [ ] Error hierarchy is documented.
- [ ] Domain/application errors are typed.
- [ ] HTTP mapping is centralized.
- [ ] Sensitive provider details are not leaked.
- [ ] Retryability is explicit.
- [ ] Tests cover representative failure classes.
- [ ] Existing API behavior remains backward compatible where appropriate.
"@
    },

    @{
        key = "02"
        title = "Harden Configuration and Runtime Limits"
        labels = @("v0.2.0", "priority:p0", "reliability")
        body = @"
## Goal

Make Neuron's runtime boundaries explicit, enforced, and testable.

## Current limits

- APP_MAX_OUTPUT_TOKENS
- APP_REQUEST_TIMEOUT_SECONDS
- APP_TOOL_TIMEOUT_SECONDS
- APP_MAX_AGENT_ITERATIONS

## Scope

Verify and enforce:

- request timeout
- tool timeout
- maximum output tokens
- maximum agent iterations / recursion
- maximum prompt size
- safe configuration ranges
- environment-specific configuration

## Acceptance Criteria

- [ ] Every configured limit is actually enforced.
- [ ] Limits have unit/integration coverage.
- [ ] Exceeding a limit produces a predictable error.
- [ ] No unbounded agent loop is possible.
- [ ] Documentation matches actual behavior.
- [ ] Development/test/production configuration is consistent.
"@
    },

    @{
        key = "03"
        title = "Implement Provider Retry and Backoff"
        labels = @("v0.2.0", "priority:p0", "reliability")
        body = @"
## Goal

Add bounded retry handling for transient model-provider failures.

## Scope

Identify retryable conditions such as:

- transient provider errors
- rate limits where retry is appropriate
- temporary network failures
- retryable HTTP 5xx responses

Do not retry:

- invalid requests
- authentication failures
- malformed configuration
- deterministic application errors
- permanently invalid tool arguments

Use bounded exponential backoff with jitter where appropriate.

## Acceptance Criteria

- [ ] Retry policy is centralized.
- [ ] Maximum attempts are bounded.
- [ ] Backoff is bounded.
- [ ] Retryable/non-retryable errors are tested.
- [ ] Rate-limit behavior is tested.
- [ ] Logs identify retry attempts without exposing secrets.
- [ ] Total request timeout remains authoritative.
"@
    },

    @{
        key = "04"
        title = "Harden Tool Execution Boundaries"
        labels = @("v0.2.0", "priority:p0", "reliability", "security")
        body = @"
## Goal

Make tool execution isolated, bounded, validated, and observable.

## Scope

Harden:

- calculator
- utc_now

Ensure every tool has:

- explicit registration
- argument validation
- execution timeout
- failure isolation
- structured error handling
- safe logging

## Acceptance Criteria

- [ ] Tool failures cannot crash unrelated request handling.
- [ ] Tool timeout is enforced.
- [ ] Invalid tool arguments are rejected safely.
- [ ] Tool errors map to stable application errors.
- [ ] Tool invocation metadata is logged safely.
- [ ] Tests cover success, invalid input, timeout, and failure.
"@
    },

    @{
        key = "05"
        title = "Harden Request Validation and Input Limits"
        labels = @("v0.2.0", "priority:p0", "security", "reliability")
        body = @"
## Goal

Protect the agent endpoint from malformed, oversized, and abusive input.

## Scope

Review and enforce:

- request schema validation
- message length
- request body size
- empty/whitespace-only messages
- malformed JSON
- excessive metadata
- unexpected fields
- Unicode edge cases where relevant

## Acceptance Criteria

- [ ] Invalid requests return stable 4xx responses.
- [ ] Oversized input is rejected before expensive model execution.
- [ ] Error responses do not leak internals.
- [ ] Input limits are configurable.
- [ ] Tests cover malformed and oversized requests.
- [ ] README/API documentation reflects limits.
"@
    },

    @{
        key = "06"
        title = "Add Application-Level Rate Limiting"
        labels = @("v0.2.0", "priority:p1", "reliability", "security")
        body = @"
## Goal

Protect Neuron and upstream model-provider quotas from excessive request volume.

## Scope

Introduce a minimal rate-limiting abstraction without prematurely
adding distributed infrastructure.

The design should support future replacement with a distributed backend.

Define:

- request identity
- rate-limit window
- burst behavior
- response status
- Retry-After behavior
- configuration

## Acceptance Criteria

- [ ] Rate limiting exists at the API boundary.
- [ ] Limits are configurable.
- [ ] Exceeded requests return 429.
- [ ] Retry-After behavior is defined.
- [ ] Tests cover normal and exceeded limits.
- [ ] Design documents the future distributed implementation.
"@
    },

    @{
        key = "07"
        title = "Expand Failure and Resilience Test Suite"
        labels = @("v0.2.0", "priority:p0", "testing", "reliability")
        body = @"
## Goal

Build a deterministic regression suite proving Neuron fails safely.

## Test categories

- missing API configuration
- invalid requests
- oversized requests
- provider timeout
- provider 429
- provider 5xx
- provider authentication failure
- malformed structured output
- tool timeout
- tool failure
- agent iteration limit
- rate limiting
- unexpected internal exception

## Acceptance Criteria

- [ ] Tests are deterministic.
- [ ] Tests do not require live OpenAI credentials.
- [ ] Provider behavior is mocked/faked at the appropriate boundary.
- [ ] Error response contracts are asserted.
- [ ] Sensitive information leakage is tested.
- [ ] Full deterministic suite passes.
"@
    },

    @{
        key = "08"
        title = "Establish Agent Evaluation Dataset v1"
        labels = @("v0.2.0", "priority:p1", "evaluation", "testing")
        body = @"
## Goal

Create the first curated evaluation dataset for Neuron's core agent behavior.

## Dataset categories

Include representative examples for:

- direct factual responses
- calculator tool selection
- UTC tool selection
- unnecessary tool avoidance
- structured output compliance
- invalid/ambiguous requests
- adversarial/tool-abuse attempts
- concise response behavior

## Acceptance Criteria

- [ ] Dataset is version-controlled or reproducibly generated.
- [ ] Each case has an expected behavior.
- [ ] Tool selection is evaluable.
- [ ] Output structure is evaluable.
- [ ] At least one quality evaluator is defined.
- [ ] Evaluation can run independently from deterministic unit tests.
- [ ] Results can be compared across prompt/model changes.
"@
    },

    @{
        key = "09"
        title = "Improve Structured Logging and Error Telemetry"
        labels = @("v0.2.0", "priority:p1", "observability", "reliability")
        body = @"
## Goal

Make runtime failures diagnosable without exposing secrets or sensitive data.

## Required correlation fields

Where available:

- request_id
- thread_id
- run_id
- model
- tool
- error type
- latency
- retry count

## Acceptance Criteria

- [ ] Correlation IDs are consistently propagated.
- [ ] Failures contain actionable structured context.
- [ ] API keys and secrets are never logged.
- [ ] User prompts are not logged indiscriminately.
- [ ] Logging behavior is documented.
- [ ] Tests cover correlation propagation.
"@
    },

    @{
        key = "10"
        title = "Document Runtime Reliability and Operations"
        labels = @("v0.2.0", "priority:p1", "documentation")
        body = @"
## Goal

Document how Neuron behaves under normal and failure conditions.

## Documentation

Update:

- README.md
- OPERATIONS.md
- DEVELOPMENT.md
- SECURITY.md
- ARCHITECTURE.md
- relevant ADRs

Document:

- timeout configuration
- retry behavior
- rate limits
- failure taxonomy
- API error responses
- tool failure behavior
- live integration testing
- local troubleshooting
- production configuration expectations

## Acceptance Criteria

- [ ] Documentation matches implementation.
- [ ] PowerShell and Unix development commands are documented.
- [ ] Failure modes are documented.
- [ ] Live API testing is clearly separated from deterministic tests.
- [ ] No secrets or real credentials appear in documentation.
"@
    },

    @{
        key = "11"
        title = "v0.2.0 Release Verification and Reliability Gate"
        labels = @("v0.2.0", "priority:p0", "testing", "reliability")
        body = @"
## Goal

Perform the final release gate for Neuron v0.2.0.

## Required checks

- uv sync
- ruff format --check
- ruff check
- mypy
- deterministic pytest suite
- security checks
- package build
- live OpenAI smoke test
- API smoke tests
- failure-path verification
- evaluation dataset v1

## Release evidence

Record:

- exact commands
- exact results
- test counts
- live model result
- latency observations
- known limitations
- remaining risks

## Exit Criteria

- [ ] All P0 issues are closed.
- [ ] No known critical reliability/security defect remains.
- [ ] Deterministic CI is green.
- [ ] Live smoke test succeeds when credentials are supplied.
- [ ] Documentation is current.
- [ ] Release notes are prepared.
- [ ] v0.2.0 tag/release is ready.
"@
    }
)


# ------------------------------------------------------------
# Create issues
# ------------------------------------------------------------

Write-Host ""
Write-Host "Creating issues..." -ForegroundColor Yellow

$createdIssues = @()

foreach ($issue in $issues) {

    Write-Host ""
    Write-Host "[$($issue.key)] $($issue.title)" -ForegroundColor Cyan

    $arguments = @(
        "issue",
        "create",
        "--repo", $repo,
        "--title", $issue.title,
        "--body", $issue.body,
        "--milestone", $milestoneTitle
    )

    foreach ($label in $issue.labels) {
        $arguments += "--label"
        $arguments += $label
    }

    $result = & gh @arguments

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create issue: $($issue.title)"
    }

    Write-Host $result -ForegroundColor Green

    if ($result -match "/issues/(\d+)") {

        $createdIssues += [PSCustomObject]@{
            Key = $issue.key
            Number = [int]$Matches[1]
            Title = $issue.title
        }
    }
}


# ------------------------------------------------------------
# Summary
# ------------------------------------------------------------

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " v0.2.0 Issues Created" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

$createdIssues | Format-Table -AutoSize

Write-Host ""
Write-Host "Milestone #$milestoneNumber" -ForegroundColor Yellow
Write-Host "https://github.com/$repo/milestone/$milestoneNumber"

Write-Host ""
Write-Host "Done." -ForegroundColor Green