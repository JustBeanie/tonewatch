#!/usr/bin/env bash
set -euo pipefail

# M0.7 user gate: review this script before running it after creating a GitHub
# token with the required repository administration permissions.
owner="${GITHUB_OWNER:-JustBeanie}"
repo="${GITHUB_REPO:-tonewatch}"
gh repo create "${owner}/${repo}" --public --description "Clean-room two-tone radio notification tool" --license apache-2.0
gh api --method PUT "repos/${owner}/${repo}/branches/main/protection" --input - <<'JSON'
{"required_status_checks":{"strict":true,"contexts":["lint-python","typecheck","test-python","lint-web","test-web"]},"enforce_admins":true,"required_pull_request_reviews":{"required_approving_review_count":1},"restrictions":null}
JSON
gh api --method PUT "repos/${owner}/${repo}/vulnerability-alerts"
gh api --method PATCH "repos/${owner}/${repo}" -f 'security_and_analysis[secret_scanning][status]=enabled' -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled'
git push -u origin main
