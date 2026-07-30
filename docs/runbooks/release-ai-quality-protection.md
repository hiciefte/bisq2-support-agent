# Release AI-quality protection

This is a human-run repository-administration procedure. It creates no
deployment and must be completed before the release workflow is allowed to use
provider or marker credentials.

## Identities and marker App

Choose two human identities and record only their numeric account IDs while
running this procedure:

- one trusted environment reviewer; and
- one release manager allowed to create or delete `release/*` branches and
  `v*` tags.

Create a dedicated GitHub App for quality-marker lifecycle operations. Configure
it with all of these restrictions:

- install it on this repository only, using selected-repository access;
- grant only repository `Contents: Read and write` (implicit metadata read is
  expected);
- grant no organization or account permissions;
- disable webhooks and subscribe to no events; and
- generate a private key only for the protected environment secret described
  below.

Record the App's numeric App ID separately from its public client ID. The
ruleset uses the numeric App ID as an `Integration` actor. The workflow uses the
client ID and private key to mint a short-lived installation token for the
current repository. Do not use a personal access token or the default workflow
token as the marker credential.

## Render the reviewed payloads

Run from the repository root with an authenticated repository administrator.
Set each value to a positive numeric account ID; no credential value is passed
on a command line.

```bash
OWNER="$(gh repo view --json owner --jq '.owner.login')"
REPOSITORY="$(gh repo view --json name --jq '.name')"
ENVIRONMENT="release-ai-quality"
ENVIRONMENT_REVIEWER_ID=""
RELEASE_MANAGER_ID=""
MARKER_APP_ID=""

if ! [[ "$ENVIRONMENT_REVIEWER_ID" =~ ^[1-9][0-9]*$ ]]; then
  echo "Invalid ENVIRONMENT_REVIEWER_ID" >&2
  exit 1
fi
if ! [[ "$RELEASE_MANAGER_ID" =~ ^[1-9][0-9]*$ ]]; then
  echo "Invalid RELEASE_MANAGER_ID" >&2
  exit 1
fi
if ! [[ "$MARKER_APP_ID" =~ ^[1-9][0-9]*$ ]]; then
  echo "Invalid MARKER_APP_ID" >&2
  exit 1
fi

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

jq --argjson id "$ENVIRONMENT_REVIEWER_ID" \
  '.reviewers[0].id = $id' \
  docs/runbooks/release-ai-quality-environment.json \
  > "$WORK_DIR/environment.json"
jq --argjson id "$RELEASE_MANAGER_ID" \
  '.bypass_actors[0].actor_id = $id' \
  docs/runbooks/release-ai-quality-release-branch-lifecycle.json \
  > "$WORK_DIR/release-branch-lifecycle.json"
cp docs/runbooks/release-ai-quality-release-branch-changes.json \
  "$WORK_DIR/release-branch-changes.json"
jq --argjson id "$RELEASE_MANAGER_ID" \
  '.bypass_actors[0].actor_id = $id' \
  docs/runbooks/release-ai-quality-version-tags.json \
  > "$WORK_DIR/version-tags.json"
jq --argjson id "$MARKER_APP_ID" \
  '.bypass_actors[0].actor_id = $id' \
  docs/runbooks/release-ai-quality-marker-tags.json \
  > "$WORK_DIR/marker-tags.json"
```

## Create the protected environment

Apply the environment with one required reviewer and custom branch policies:

```bash
gh api --method PUT \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  "repos/${OWNER}/${REPOSITORY}/environments/${ENVIRONMENT}" \
  --input "$WORK_DIR/environment.json"
```

Remove any existing deployment policies for this environment, then allow only
the default branch and one-segment release branches:

```bash
gh api --paginate \
  "repos/${OWNER}/${REPOSITORY}/environments/${ENVIRONMENT}/deployment-branch-policies" \
  --jq '.branch_policies[].id' |
while IFS= read -r policy_id; do
  gh api --method DELETE \
    "repos/${OWNER}/${REPOSITORY}/environments/${ENVIRONMENT}/deployment-branch-policies/${policy_id}"
done

gh api --method POST \
  "repos/${OWNER}/${REPOSITORY}/environments/${ENVIRONMENT}/deployment-branch-policies" \
  -f name=main -f type=branch
gh api --method POST \
  "repos/${OWNER}/${REPOSITORY}/environments/${ENVIRONMENT}/deployment-branch-policies" \
  -f 'name=release/*' -f type=branch
```

Store both credentials interactively in the environment. Never define either
secret name as a repository or organization secret, and never pass a secret
value on a command line.

```bash
gh secret set AI_QUALITY_GATE_OPENAI_API_KEY --env "$ENVIRONMENT"
gh secret set AI_QUALITY_GATE_MARKER_APP_PRIVATE_KEY --env "$ENVIRONMENT"
```

Set the App client ID as a non-secret environment variable. Set the model
identity to the exact intended production model as a repository variable:

```bash
gh variable set AI_QUALITY_GATE_MARKER_APP_CLIENT_ID --env "$ENVIRONMENT"
gh variable set AI_QUALITY_GATE_OPENAI_MODEL
```

The App action deliberately omits `owner` and `repositories`, which scopes each
installation token to the current repository. It requests only `contents:
write`, leaves the job's default workflow token read-only, and revokes the
installation token at the end of each marker job.

## Apply the ref rulesets

The templates are active rulesets. Create each once. If a same-named ruleset
already exists, compare it field-for-field and update that ruleset instead of
creating a duplicate.

```bash
gh api --method POST \
  "repos/${OWNER}/${REPOSITORY}/rulesets" \
  --input "$WORK_DIR/release-branch-lifecycle.json"
gh api --method POST \
  "repos/${OWNER}/${REPOSITORY}/rulesets" \
  --input "$WORK_DIR/release-branch-changes.json"
gh api --method POST \
  "repos/${OWNER}/${REPOSITORY}/rulesets" \
  --input "$WORK_DIR/version-tags.json"
gh api --method POST \
  "repos/${OWNER}/${REPOSITORY}/rulesets" \
  --input "$WORK_DIR/marker-tags.json"
```

These rules make release-branch changes review-only, limit release branch and
version-tag lifecycle operations to the release manager, and limit quality
marker creation, movement, and deletion to the dedicated GitHub App.

## Verify before first use

Read the environment, policies, rulesets, and secret names back. Secret values
must never be printed.

```bash
gh api \
  "repos/${OWNER}/${REPOSITORY}/environments/${ENVIRONMENT}"
gh api --paginate \
  "repos/${OWNER}/${REPOSITORY}/environments/${ENVIRONMENT}/deployment-branch-policies"
gh api --paginate "repos/${OWNER}/${REPOSITORY}/rulesets"
gh secret list --env "$ENVIRONMENT"
gh variable list
gh variable list --env "$ENVIRONMENT"
```

Inspect the marker ruleset and require the bypass actor to be `Integration`,
with the exact numeric App ID and `always` bypass mode. In the GitHub App
settings, confirm the installation still selects only this repository, the only
nonimplicit permission is repository Contents read/write, and no webhook or
event subscription has been added.

Finally, run the workflow from a reviewed `release/*` branch. Confirm the
environment requires approval, the sanitized artifact passes review, and the
exact commit/model marker appears. Confirm the deployment verifier accepts only
the newest successful fresh-answer run and rejects the same marker after a newer
failed test run. It must also reject tracked or nonignored untracked source
changes. A version tag for another commit or model must fail its
marker-verification job. Do not enable any response channel while performing
this validation.

The temporary single-human exception is a separate, explicitly non-launch-ready
profile. Use `single-operator-production-testing.md` only for private
production testing, and restore this canonical protection before public launch
or autoresponse testing.
