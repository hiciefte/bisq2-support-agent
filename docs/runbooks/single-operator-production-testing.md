# Single-operator production-testing profile

This is a temporary repository-governance profile for an experimental,
privately accessed production test using the existing production stack and
data. It lets one trusted operator open and merge pull requests, approve the
protected AI-quality jobs they dispatched, and manage reviewed release refs.
It is not launch-ready and does not authorize a production change by itself.

The canonical launch profiles remain:

- `branch-protection.json`;
- `release-ai-quality-environment.json`; and
- `release-ai-quality-release-branch-changes.json`.

This profile changes only the human separation controls:

| Control | Canonical launch profile | Single-operator testing |
| --- | --- | --- |
| Main pull-request approvals | 1 | 0 |
| Environment self-review | blocked | allowed |
| Release pull-request approvals | 1 | 0 |
| Release last-push approval | required | not required |

Pull requests, the five exact strict checks, stale-review dismissal,
release-branch review-thread resolution, administrator enforcement,
squash-only release merges, non-fast-forward protection, signed commits, and
force-push/deletion blocks remain required. The protected environment still
requires a manual approval; the change is that the workflow initiator may
supply it.

The quality-marker writer remains a repository-scoped GitHub App. The operator
must not replace it with a personal access token or become the marker ruleset
bypass actor.

## Boundaries that this profile never relaxes

Before any production update, all requirements in
`production-gate-transition.md` still apply. In particular:

- fresh answers must pass for the exact commit and configured production model;
- the sanitized quality report must be reviewed manually;
- the exact commit/model marker must be written by the restricted GitHub App;
- an encrypted off-host backup must pass full scratch restoration;
- the checkout and Docker project must pass the clean-source and continuity
  checks;
- rollback ownership and post-update verification remain human decisions;
- public ingress stays blocked and HTTP stays loopback-only, reached through an
  operator SSH tunnel; and
- all of these switches remain explicit:
  `AUTONOMOUS_DELIVERY_ENABLED=false`, `MATRIX_SYNC_ENABLED=false`,
  `MATRIX_CHATOPS_ENABLED=false`, `BISQ2_CHANNEL_ENABLED=false`,
  `BISQ2_CHATOPS_ENABLED=false`, and
  `ESCALATION_BISQ2_WS_ENABLED=false`.

Do not use this profile for public clearnet exposure, channel shadowing,
allowlisted channel delivery, autoresponse testing, or launch. Temporary
browser access to the website and `/admin` remains the loopback-and-tunnel mode
documented in the transition runbook; it requires no domain or TLS lifecycle.

## Apply the profile

Run from the exact reviewed checkout with an authenticated repository
administrator. Set `OPERATOR_LOGIN` in the protected operator shell. These
commands change repository controls only; they do not touch a deployment.

The App, variables, secrets, deployment policies, lifecycle ruleset, and marker
ruleset from `release-ai-quality-protection.md` must be complete before the
quality workflow can pass. The main-branch relaxation may be applied earlier to
merge the implementation pull request, but that does not waive those remaining
hard stops.

```bash
set -euo pipefail

OWNER="$(gh repo view --json owner --jq '.owner.login')"
REPOSITORY="$(gh repo view --json name --jq '.name')"
BRANCH="$(gh repo view --json defaultBranchRef --jq '.defaultBranchRef.name')"
ENVIRONMENT="release-ai-quality"
OPERATOR_LOGIN=""

test "$BRANCH" = main
test -n "$OPERATOR_LOGIN"
OPERATOR_ID="$(gh api "users/${OPERATOR_LOGIN}" --jq '.id')"
[[ "$OPERATOR_ID" =~ ^[1-9][0-9]*$ ]]

RELEASE_CHANGES_RULESET_ID="$(
  gh api --paginate "repos/${OWNER}/${REPOSITORY}/rulesets" \
    --jq '.[] | select(.name == "Release branch reviewed changes") | .id'
)"
[[ "$RELEASE_CHANGES_RULESET_ID" =~ ^[1-9][0-9]*$ ]]

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

jq --argjson id "$OPERATOR_ID" \
  '.reviewers[0].id = $id' \
  docs/runbooks/release-ai-quality-environment.single-operator-testing.json \
  > "$WORK_DIR/environment.json"

gh api --method PUT \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  "repos/${OWNER}/${REPOSITORY}/environments/${ENVIRONMENT}" \
  --input "$WORK_DIR/environment.json"

gh api --method PUT \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  "repos/${OWNER}/${REPOSITORY}/rulesets/${RELEASE_CHANGES_RULESET_ID}" \
  --input \
    docs/runbooks/release-ai-quality-release-branch-changes.single-operator-testing.json

gh api --method PUT \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  "repos/${OWNER}/${REPOSITORY}/branches/${BRANCH}/protection" \
  --input docs/runbooks/branch-protection.single-operator-testing.json
```

Main protection is applied last because it is the control that removes the
independent pull-request approval. If any apply or verification step fails,
stop and restore the canonical payloads below. Do not weaken another control to
make the profile fit.

## Verify the profile

Read back every changed surface and inspect the results:

```bash
gh api \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  "repos/${OWNER}/${REPOSITORY}/branches/${BRANCH}/protection" \
  --jq '{
    strict: .required_status_checks.strict,
    contexts: .required_status_checks.contexts,
    approvals:
      .required_pull_request_reviews.required_approving_review_count,
    dismiss_stale_reviews:
      .required_pull_request_reviews.dismiss_stale_reviews,
    enforce_admins: .enforce_admins.enabled,
    force_pushes: .allow_force_pushes.enabled,
    deletions: .allow_deletions.enabled
  }'

gh api \
  "repos/${OWNER}/${REPOSITORY}/branches/${BRANCH}/protection/required_signatures" \
  --jq '{signed_commits: .enabled}'

gh api \
  "repos/${OWNER}/${REPOSITORY}/environments/${ENVIRONMENT}" \
  --jq '{
    prevent_self_review,
    reviewers: [.protection_rules[] | select(.type == "required_reviewers") |
      .reviewers[] | {type, id}],
    deployment_branch_policy
  }'

gh api \
  "repos/${OWNER}/${REPOSITORY}/rulesets/${RELEASE_CHANGES_RULESET_ID}"

gh api --paginate \
  "repos/${OWNER}/${REPOSITORY}/environments/${ENVIRONMENT}/deployment-branch-policies"

gh api --paginate "repos/${OWNER}/${REPOSITORY}/rulesets"
gh secret list --env "$ENVIRONMENT"
gh variable list --env "$ENVIRONMENT"
gh variable list
```

Require all five exact status contexts, zero main approvals, stale-review and
administrator enforcement, signed commits, and both force pushes and deletions
blocked. Require the environment reviewer to be the exact operator,
`prevent_self_review=false`, and only `main` plus `release/*` deployment
policies.

Require the release-change ruleset to retain pull requests, squash-only merge,
resolved threads, non-fast-forward protection, and the five strict checks, with
only approval count zero and last-push approval disabled. Require the
release-lifecycle and version-tag bypass actors to be the exact operator.
Require the marker ruleset actor to be the exact GitHub App ID with type
`Integration` and mode `always`.

The environment must list only these two secret names:

- `AI_QUALITY_GATE_OPENAI_API_KEY`;
- `AI_QUALITY_GATE_MARKER_APP_PRIVATE_KEY`.

It must list `AI_QUALITY_GATE_MARKER_APP_CLIENT_ID` as an environment variable.
The repository variable `AI_QUALITY_GATE_OPENAI_MODEL` must remain the exact
reviewed production model. Never print any secret value.

## Restore launch-ready separation

Before public exposure, any Matrix or Bisq shadow/allowlist work, autoresponse
testing, or launch, freeze merges and release operations. Choose an independent
environment reviewer and reapply the canonical profiles. Initialize a fresh
operator shell; do not rely on variables or temporary files from the earlier
application:

```bash
set -euo pipefail

OWNER="$(gh repo view --json owner --jq '.owner.login')"
REPOSITORY="$(gh repo view --json name --jq '.name')"
BRANCH="$(gh repo view --json defaultBranchRef --jq '.defaultBranchRef.name')"
ENVIRONMENT="release-ai-quality"
test "$BRANCH" = main

RELEASE_CHANGES_RULESET_ID="$(
  gh api --paginate "repos/${OWNER}/${REPOSITORY}/rulesets" \
    --jq '.[] | select(.name == "Release branch reviewed changes") | .id'
)"
[[ "$RELEASE_CHANGES_RULESET_ID" =~ ^[1-9][0-9]*$ ]]

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

INDEPENDENT_REVIEWER_ID=""
[[ "$INDEPENDENT_REVIEWER_ID" =~ ^[1-9][0-9]*$ ]]

jq --argjson id "$INDEPENDENT_REVIEWER_ID" \
  '.reviewers[0].id = $id' \
  docs/runbooks/release-ai-quality-environment.json \
  > "$WORK_DIR/environment.canonical.json"

gh api --method PUT \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  "repos/${OWNER}/${REPOSITORY}/environments/${ENVIRONMENT}" \
  --input "$WORK_DIR/environment.canonical.json"

gh api --method PUT \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  "repos/${OWNER}/${REPOSITORY}/rulesets/${RELEASE_CHANGES_RULESET_ID}" \
  --input docs/runbooks/release-ai-quality-release-branch-changes.json

gh api --method PUT \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  "repos/${OWNER}/${REPOSITORY}/branches/${BRANCH}/protection" \
  --input docs/runbooks/branch-protection.json
```

Follow both canonical protection runbooks and verify every identity and rule
again. Then run a new fresh-answer workflow for the exact release commit and
model, with the independent reviewer approving it. Evidence approved under the
single-operator profile is not launch evidence.
