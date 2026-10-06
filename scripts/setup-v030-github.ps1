# One-off GitHub housekeeping after v0.2.0 / before v0.3.0 work starts:
#   1. Push the v0.2.0 tag (if it is not on the remote yet).
#   2. Close issue #11 (v0.2.0 release gate) once the tag exists.
#   3. Create the "v0.3.0 - Stateful + Streaming" milestone and assign #20-#30.
#   4. Give the auto-created v0.3.0 labels proper colors and descriptions.
#
# Run from a clone of the repo with git and an authenticated gh CLI:
#   .\scripts\setup-v030-github.ps1            # do everything
#   .\scripts\setup-v030-github.ps1 -DryRun    # print what would happen
#   .\scripts\setup-v030-github.ps1 -SkipTag   # leave the tag and issue #11 alone
#
# Every step is idempotent: re-running it is safe.

param(
    [switch]$DryRun,
    [switch]$SkipTag
)

$ErrorActionPreference = "Stop"

$repo = "Md-Nisar/neuron"
$tag = "v0.2.0"
$releaseGateIssue = 11
$milestoneTitle = "v0.3.0 - Stateful + Streaming"
$milestoneDescription = "Conversations + real-time responses: thread persistence, multi-turn continuity, SSE streaming, cancellation, thread lifecycle, telemetry, tests, and docs."
$issues = 20..30

$labels = @(
    @{ Name = "v0.3.0";       Color = "5319E7"; Description = "Work targeted for Neuron v0.3.0" },
    @{ Name = "architecture"; Color = "1D76DB"; Description = "Architecture decisions and ADRs" },
    @{ Name = "state";        Color = "FBCA04"; Description = "Conversation state, persistence, and thread lifecycle" },
    @{ Name = "streaming";    Color = "C5DEF5"; Description = "Real-time response streaming (SSE)" }
)

# Run a native command, or only print it in dry-run mode. Fails on non-zero exit.
function Invoke-Step {
    param([string]$Exe, [string[]]$Arguments)
    if ($DryRun) {
        Write-Host "[dry-run] $Exe $($Arguments -join ' ')" -ForegroundColor DarkGray
        return
    }
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $Exe $($Arguments -join ' ')"
    }
}

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " Neuron v0.3.0 GitHub Setup" -ForegroundColor Cyan
Write-Host "==============================================" -ForegroundColor Cyan
if ($DryRun) { Write-Host " (dry run: nothing will be changed)" -ForegroundColor DarkGray }
Write-Host ""

# ------------------------------------------------------------
# 0. Verify tools
# ------------------------------------------------------------

Write-Host "[0/4] Checking git and GitHub CLI..." -ForegroundColor Yellow

foreach ($tool in @("git", "gh")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "$tool not found on PATH."
    }
}
gh auth status
if ($LASTEXITCODE -ne 0) { throw "gh is not authenticated. Run 'gh auth login'." }

Write-Host "Tools OK." -ForegroundColor Green


# ------------------------------------------------------------
# 1. Push the v0.2.0 tag
# ------------------------------------------------------------

if ($SkipTag) {
    Write-Host ""
    Write-Host "[1/4] Skipping tag (-SkipTag)." -ForegroundColor DarkGray
    Write-Host "[2/4] Skipping issue #$releaseGateIssue (-SkipTag)." -ForegroundColor DarkGray
}
else {
    Write-Host ""
    Write-Host "[1/4] Checking tag $tag on origin..." -ForegroundColor Yellow

    git ls-remote --exit-code --tags origin "refs/tags/$tag" | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Tag $tag already on origin." -ForegroundColor Green
    }
    else {
        git fetch origin main --quiet
        if ($LASTEXITCODE -ne 0) { throw "git fetch failed." }

        # Only tag main if it actually carries the v0.2.0 version bump.
        $pyproject = git show "origin/main:pyproject.toml"
        $versionLine = $pyproject | Where-Object { $_ -match '^version = "(.+)"' } | Select-Object -First 1
        $version = if ($versionLine -match '^version = "(.+)"') { $Matches[1] } else { "" }
        if ("v$version" -ne $tag) {
            throw "origin/main is at version '$version', expected $($tag.TrimStart('v')). Is PR #19 merged?"
        }

        git rev-parse -q --verify "refs/tags/$tag" | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Local tag $tag exists; pushing it." -ForegroundColor Yellow
        }
        else {
            $mainSha = git rev-parse --short origin/main
            Write-Host "Creating annotated tag $tag at origin/main ($mainSha)." -ForegroundColor Yellow
            Invoke-Step git @("tag", "-a", $tag, "origin/main", "-m", "Neuron $tag - Reliable Agent Runtime")
        }

        Invoke-Step git @("push", "origin", "refs/tags/$tag")
        Write-Host "Tag $tag pushed." -ForegroundColor Green
    }


    # ------------------------------------------------------------
    # 2. Close the v0.2.0 release-gate issue
    # ------------------------------------------------------------

    Write-Host ""
    Write-Host "[2/4] Closing issue #$releaseGateIssue..." -ForegroundColor Yellow

    $state = gh issue view $releaseGateIssue --repo $repo --json state -q .state
    if ($state -eq "CLOSED") {
        Write-Host "Issue #$releaseGateIssue already closed." -ForegroundColor Green
    }
    else {
        $comment = "Release gate complete: evidence in ``docs/releases/v0.2.0-release-verification.md``, shipped in #19, tagged ``$tag``. Known limitation: live OpenAI smoke test not yet run with credentials."
        Invoke-Step gh @("issue", "close", "$releaseGateIssue", "--repo", $repo, "--reason", "completed", "--comment", $comment)
        Write-Host "Issue #$releaseGateIssue closed." -ForegroundColor Green
    }
}


# ------------------------------------------------------------
# 3. Milestone + issue assignment
# ------------------------------------------------------------

Write-Host ""
Write-Host "[3/4] Checking milestone..." -ForegroundColor Yellow

$milestones = gh api "repos/$repo/milestones?state=all&per_page=100" | ConvertFrom-Json
$existingMilestone = $milestones | Where-Object { $_.title -eq $milestoneTitle }

if ($existingMilestone) {
    Write-Host "Milestone already exists: #$($existingMilestone.number)" -ForegroundColor Green
}
else {
    Write-Host "Creating milestone: $milestoneTitle" -ForegroundColor Yellow
    Invoke-Step gh @("api", "--method", "POST", "repos/$repo/milestones",
        "-f", "title=$milestoneTitle", "-f", "description=$milestoneDescription", "-f", "state=open", "--silent")
    Write-Host "Milestone created." -ForegroundColor Green
}

foreach ($issue in $issues) {
    Invoke-Step gh @("issue", "edit", "$issue", "--repo", $repo, "--milestone", $milestoneTitle)
    Write-Host "  #$issue -> $milestoneTitle"
}


# ------------------------------------------------------------
# 4. Labels
# ------------------------------------------------------------

Write-Host ""
Write-Host "[4/4] Updating label colors and descriptions..." -ForegroundColor Yellow

foreach ($label in $labels) {
    Invoke-Step gh @("label", "create", $label.Name, "--repo", $repo,
        "--color", $label.Color, "--description", $label.Description, "--force")
    Write-Host "  $($label.Name)"
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
