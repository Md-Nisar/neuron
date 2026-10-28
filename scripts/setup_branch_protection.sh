#!/usr/bin/env bash
# Protect the default branch as described in docs/AI_CODE_VERIFICATION.md.
# Usage: scripts/setup_branch_protection.sh [owner/repo] [branch]
# Needs the GitHub CLI (`gh auth login`) with admin rights on the repository.
# Status checks must have run at least once on a PR before GitHub can require them.
set -euo pipefail

repo="${1:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
branch="${2:-main}"
# Set CODE_OWNER_REVIEWS=false while the repository has a single maintainer.
code_owners="${CODE_OWNER_REVIEWS:-true}"

for label in large-pr-approved new-dependency-approved; do
  gh label create "$label" --repo "$repo" --color FBCA04 \
    --description "Maintainer override for the ai-code-verification gate" 2>/dev/null || true
done

gh api --method PUT "repos/$repo/branches/$branch/protection" --input - <<JSON
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "checks (ubuntu-latest)",
      "checks (windows-latest)",
      "secrets-scan",
      "dependency-review",
      "new-dependencies",
      "pr-hygiene",
      "analyze (python)",
      "analyze (actions)"
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": $code_owners,
    "require_last_push_approval": true
  },
  "required_conversation_resolution": true,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
echo "Branch protection applied to $repo@$branch."
