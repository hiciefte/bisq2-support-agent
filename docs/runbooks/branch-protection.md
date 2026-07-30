# Main branch protection

This is a human-run repository administration procedure. It does not modify a
deployment and must not be automated with a credential stored in this
repository.

The committed payload requires pull requests, one approving review, fresh
status checks against the current branch head, and protection for repository
administrators. It also blocks force pushes and branch deletion.

## Preconditions

1. Sign in with `gh` using an account with repository administration access.
2. Confirm the five required checks below have completed on a recent pull
   request. Check names are exact and a renamed or missing check will block
   merging:
   - `Lint, Type Check & Test`
   - `Frontend Lint, Type Check & Test`
   - `Shell Lint & Deployment Tests`
   - `Security Scan`
   - `Offline Staff-Alignment Gate`
3. Review `docs/runbooks/branch-protection.json`. In particular, keep
   `strict`, `enforce_admins`, and `dismiss_stale_reviews` enabled.

## Apply

Run these commands from the repository root. They discover the repository
identity from the authenticated checkout instead of embedding it in the
runbook.

```bash
OWNER="$(gh repo view --json owner --jq '.owner.login')"
REPOSITORY="$(gh repo view --json name --jq '.name')"
BRANCH="$(gh repo view --json defaultBranchRef --jq '.defaultBranchRef.name')"

test "$BRANCH" = "main"

gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  "repos/${OWNER}/${REPOSITORY}/branches/${BRANCH}/protection" \
  --input docs/runbooks/branch-protection.json
```

The API call is intentionally a human decision point. Do not run it from CI
and do not grant CI repository-administration permission.

## Verify

Read the applied settings back and inspect the reduced result:

```bash
gh api \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  "repos/${OWNER}/${REPOSITORY}/branches/${BRANCH}/protection" \
  --jq '{
    strict: .required_status_checks.strict,
    contexts: .required_status_checks.contexts,
    required_approving_review_count:
      .required_pull_request_reviews.required_approving_review_count,
    dismiss_stale_reviews:
      .required_pull_request_reviews.dismiss_stale_reviews,
    enforce_admins: .enforce_admins.enabled,
    allow_force_pushes: .allow_force_pushes.enabled,
    allow_deletions: .allow_deletions.enabled
  }'
```

The result must show `strict`, `dismiss_stale_reviews`, and `enforce_admins`
as `true`; one required approving review; and both `allow_force_pushes` and
`allow_deletions` as `false`.

Finally, open a test pull request and confirm that merging is unavailable until
all five checks pass on the latest commit and one non-stale approval exists.

## Updating required checks

When a workflow job is renamed, update the context in
`docs/runbooks/branch-protection.json` in the same pull request. After that
pull request's old checks pass, a repository administrator applies the updated
payload and verifies the new check name before merging subsequent work.

## Temporary single-operator testing

`single-operator-production-testing.md` defines the narrowly scoped,
non-launch-ready exception for private production testing. Its separate payload
sets the approval count to zero but preserves pull requests, all five strict
checks, administrator enforcement, signed commits, and force-push/deletion
blocks. Never edit this canonical payload to enter that mode, and restore this
payload before public exposure or autoresponse testing.
