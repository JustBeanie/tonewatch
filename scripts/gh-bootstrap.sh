#!/usr/bin/env bash
# M0.7: create the GitHub repo, apply repo settings and rulesets, then push main.
# Idempotent: safe to re-run. Features GitHub gates by plan are reported, not fatal.
# usage: VISIBILITY=private|public scripts/gh-bootstrap.sh
set -euo pipefail

owner="${GITHUB_OWNER:-JustBeanie}"
repo="${GITHUB_REPO:-tonewatch}"
visibility="${VISIBILITY:-private}"
slug="${owner}/${repo}"

try() {
  local label="$1"
  shift
  if "$@" >/dev/null 2>/tmp/gh-bootstrap.err; then
    echo "ok      ${label}"
  else
    echo "skipped ${label}: $(tr '\n' ' ' </tmp/gh-bootstrap.err | cut -c1-160)"
  fi
}

if gh repo view "${slug}" >/dev/null 2>&1; then
  echo "exists  ${slug}"
else
  # No --license/--add-readme: those create a remote commit and the first push would be rejected.
  gh repo create "${slug}" "--${visibility}" \
    --description "Clean-room two-tone and long-tone paging detector with Home Assistant integration"
  echo "created ${slug} (${visibility})"
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  git remote add origin "https://github.com/${slug}.git"
fi

try "merge settings (squash only, delete merged branches)" \
  gh api --method PATCH "repos/${slug}" \
  -F allow_squash_merge=true -F allow_merge_commit=false -F allow_rebase_merge=false \
  -F delete_branch_on_merge=true -f squash_merge_commit_title=PR_TITLE \
  -f squash_merge_commit_message=PR_BODY -F has_wiki=false

try "dependabot vulnerability alerts" gh api --method PUT "repos/${slug}/vulnerability-alerts"
try "dependabot security updates" gh api --method PUT "repos/${slug}/automated-security-fixes"
try "secret scanning + push protection" \
  gh api --method PATCH "repos/${slug}" \
  -f 'security_and_analysis[secret_scanning][status]=enabled' \
  -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled'
try "private vulnerability reporting" gh api --method PUT "repos/${slug}/private-vulnerability-reporting"

git push -u origin main

# Ruleset on main: PR required (no approvals: solo owner), required CI checks,
# linear history, no force-push/deletion. Repo admins may bypass for emergencies.
if gh api "repos/${slug}/rulesets" --jq '.[].name' 2>/dev/null | grep -qx "main-protection"; then
  echo "exists  ruleset main-protection"
else
  try "ruleset main-protection" gh api --method POST "repos/${slug}/rulesets" --input - <<'JSON'
{
  "name": "main-protection",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "bypass_actors": [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}],
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "required_linear_history"},
    {"type": "pull_request", "parameters": {
      "required_approving_review_count": 0,
      "dismiss_stale_reviews_on_push": false,
      "require_code_owner_review": false,
      "require_last_push_approval": false,
      "required_review_thread_resolution": true,
      "allowed_merge_methods": ["squash"]}},
    {"type": "required_status_checks", "parameters": {
      "strict_required_status_checks_policy": false,
      "required_status_checks": [
        {"context": "lint-python"}, {"context": "typecheck"}, {"context": "test-python"},
        {"context": "lint-web"}, {"context": "test-web"}]}}
  ]
}
JSON
fi

for label in "milestone:M0" "milestone:M1" "milestone:M2" "milestone:M3" "milestone:M4" "milestone:M5" \
  "milestone:M6" "milestone:M7" "milestone:M8" "milestone:M9" "milestone:M10" "milestone:M11" \
  "milestone:M12" "milestone:S" "area:dsp" "area:sources" "area:api" "area:web" "area:alerts" \
  "area:docker" "area:ha" "area:windows" "area:security" "blocked-on-user" "security"; do
  gh label create "${label}" --repo "${slug}" --force >/dev/null && echo "ok      label ${label}"
done
