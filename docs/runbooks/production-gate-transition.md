# Existing-production release-gate transition

This is the human-run procedure for the first update of an existing production
checkout whose installed updater predates the release AI-quality gate. It keeps
the existing application data and Docker volumes. It does not authorize an
autoresponse channel, create a public listener, or modify production by itself.

Use this procedure once. After the transition succeeds, use the checked-in
`scripts/update.sh` normally. Never bridge the version gap with the old updater,
a copied script, a manual reset, or a new empty deployment.

## Hard stops

Do not begin the production change until all of these are true:

- the candidate pull request is approved, merged, and green at an exact commit;
- main branch protection from `branch-protection.md` is applied and verified;
- the protected environment and ref rules from
  `release-ai-quality-protection.md` are applied and verified;
- a fresh-answer workflow passed for the exact candidate commit and production
  model, and a human reviewed its sanitized report;
- an encrypted off-host backup from the existing stack passed full scratch
  restore verification with the candidate recovery code;
- the production checkout has no tracked or nonignored untracked source change;
- exactly one running API container carries Compose labels for the existing
  production Docker directory, has exactly `DATA_DIR=/data`, and binds `/data`
  to the checkout's existing `api/data` directory;
- the canonical Compose container set has no stale, orphaned,
  duplicate-service, cross-project, or cross-working-directory container;
- all six delivery and ChatOps switches listed below are explicitly `false`;
- external HTTP ingress is blocked by the host or network firewall throughout
  staging;
- the candidate configuration uses base Compose mode, a loopback-only HTTP
  bind, no TLS overlay or redirect, and `COOKIE_SECURE=false`; and
- an operator owns the change window, terminal, rollback decision, and incident
  record.

If any prerequisite cannot be proven, stop. Do not weaken a gate to continue.

## 1. Protect the repository and generate exact evidence

A repository administrator first follows:

1. `docs/runbooks/branch-protection.md`;
2. `docs/runbooks/release-ai-quality-protection.md`.

The environment reviewer must be a trusted human other than the workflow
initiator. The release manager and dedicated marker identity must be the
reviewed identities recorded during setup. Enter provider and marker
credentials only through the protected environment's interactive secret flow;
never put their values in a command, issue, artifact, or operator log. Set
`AI_QUALITY_GATE_OPENAI_MODEL` to the exact `OPENAI_MODEL` selected in the
protected production configuration.

After the transition pull request merges, pause further main merges. From a
clean administrative checkout:

```bash
git fetch --no-tags origin main
CANDIDATE_REF=main
CANDIDATE_COMMIT="$(git rev-parse origin/main)"
test "$(git rev-parse "$CANDIDATE_COMMIT^{commit}")" = "$CANDIDATE_COMMIT"
gh workflow run ai-quality-gate.yml --ref "$CANDIDATE_REF"
```

The separate environment reviewer approves the protected jobs. Locate the
newest manual run whose `headSha` equals `CANDIDATE_COMMIT`, wait for all three
quality jobs to succeed, and download only its dynamically named sanitized
report. Review every case result and metric. Confirm that the marker namespace
contains an exact commit/model marker without printing the raw model value.

Before touching production, fetch main again and require it still points to the
same candidate:

```bash
git fetch --no-tags origin main
test "$(git rev-parse origin/main)" = "$CANDIDATE_COMMIT"
```

If main advanced, discard this transition attempt, select the new exact commit,
and run fresh answers again. An older pass never authorizes a newer commit.

## 2. Stage candidate tools without changing the live checkout

On the production host, set these values only in the protected operator shell:

```bash
PRODUCTION_REPOSITORY='<existing-production-checkout>'
CANDIDATE_REF=main
CANDIDATE_COMMIT='<full-reviewed-commit>'
CANDIDATE_WORKTREE='<private-temporary-worktree>'
```

Fetch and stage a detached worktree. The live checkout remains at its current
commit:

```bash
git -C "$PRODUCTION_REPOSITORY" fetch --no-tags origin \
  "refs/heads/$CANDIDATE_REF"
test "$(git -C "$PRODUCTION_REPOSITORY" rev-parse FETCH_HEAD)" = \
  "$CANDIDATE_COMMIT"
git -C "$PRODUCTION_REPOSITORY" worktree add --detach \
  "$CANDIDATE_WORKTREE" "$CANDIDATE_COMMIT"
test "$(git -C "$CANDIDATE_WORKTREE" rev-parse HEAD)" = "$CANDIDATE_COMMIT"
test -z "$(git -C "$CANDIDATE_WORKTREE" status --short)"
```

Do not copy candidate files into the live checkout. The bootstrap requires the
candidate worktree to be detached, clean, separate, and at the exact commit.

## 3. Prove the existing data is recoverable

Follow `docs/disaster-recovery.md` using `backup.sh` and `restore.sh` from the
candidate worktree while pointing `BISQ_SUPPORT_INSTALL_DIR` at the existing
production checkout:

```bash
export BISQ_SUPPORT_INSTALL_DIR="$PRODUCTION_REPOSITORY"
export BACKUP_TARGET_DIR='<existing-off-host-target>'
export BACKUP_MOUNT_ROOT='<existing-off-host-mount-root>'
export BACKUP_AGE_RECIPIENT='<escrowed-public-recipient>'

"$CANDIDATE_WORKTREE/scripts/backup.sh" --confirm-off-host

BACKUP_FILE='<newly-completed-encrypted-backup>'
export BACKUP_AGE_IDENTITY_FILE='<protected-identity-file>'
"$CANDIDATE_WORKTREE/scripts/restore.sh" \
  --backup "$BACKUP_FILE" --verify
```

Use the GPG options documented in the disaster-recovery runbook if that is the
reviewed encryption choice. The operator must identify the exact newly
completed backup; do not select a set merely because it sorts last.

The older stack may legitimately have no separate Matrix alert-relay service or
volume. In that one topology, the candidate backup records one absent volume
and still snapshots Matrix session/store files from application data. Any
configured relay whose container or named volume is missing is an error, not a
legacy exception. Record the verification summary without decrypted data or
configuration values.

Passing `--confirm-fresh-backup` later is an operator attestation that this exact
backup completed and passed full scratch verification during the same change
window. It is not a bypass.

## 4. Keep the production-test boundary dark and private

The protected `docker/.env` must contain exactly one of each line below:

```dotenv
AUTONOMOUS_DELIVERY_ENABLED=false
MATRIX_SYNC_ENABLED=false
MATRIX_CHATOPS_ENABLED=false
BISQ2_CHANNEL_ENABLED=false
BISQ2_CHATOPS_ENABLED=false
ESCALATION_BISQ2_WS_ENABLED=false
COOKIE_SECURE=false
```

The bootstrap checks these names without printing any other value. The global
switch also forces any persisted autonomous-delivery setting off at startup.
Do not add Matrix or Bisq allowlisted response targets during this transition.
Before invoking the bootstrap, use a clean operator shell and `unset` these six
names plus `COOKIE_SECURE`, `OPENAI_MODEL`,
`BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE`, `NGINX_HTTP_BIND_ADDRESS`,
`NGINX_HTTPS_BIND_ADDRESS`, `NGINX_TLS_CERTIFICATE_DIR`,
`NGINX_TLS_CERTIFICATE_FILENAME`, `NGINX_TLS_PRIVATE_KEY_FILENAME`, and
`NGINX_TLS_REDIRECT_HTTP`. Also unset `COMPOSE_ENV_FILES`,
`COMPOSE_DISABLE_ENV_FILE`, `COMPOSE_FILE`, `COMPOSE_PATH_SEPARATOR`,
`COMPOSE_PROJECT_NAME`, `COMPOSE_PROFILES`, `DOCKER_HOST`, `DOCKER_CONTEXT`, and
`BISQ_SUPPORT_LIFECYCLE_LOCK_FD`.
The bootstrap rejects all of these exported overrides because they could replace
the verified environment, Compose project, service selection, or Docker daemon.

Do not set a project name to make the transition select a stack. The bootstrap
finds the running API container by its exact Compose working-directory label,
requires the match to be unique, derives its project name from Docker labels,
and checks it against Compose's canonical container set. It rejects stale or
orphaned containers instead of letting one satisfy a data-continuity check. It
persists the label-derived name as the sole canonical `COMPOSE_PROJECT_NAME`
assignment in protected `docker/.env`. While containers exist, production
entry points rederive and validate the label identity and explicitly pin it. If
`docker compose down` has removed the entire container set, only
`scripts/start.sh` may fall back to that protected name to recreate the same
project; other operations fail closed until the stack exists. No command may
derive or start a new default project beside it. Zero or multiple matches,
malformed labels, a conflicting persisted name, a different data bind, or a
noncanonical container set are hard stops. Repair or disambiguate the existing
stack under a separately reviewed plan.

The legacy pre-transition stack may still publish HTTP on all host interfaces,
so keep external firewall ingress closed before staging and throughout the
window. Configure the candidate for base Compose mode with
`NGINX_HTTP_BIND_ADDRESS=127.0.0.1`, an empty Compose override selection, empty
TLS file settings, `NGINX_TLS_REDIRECT_HTTP=false`, and `COOKIE_SECURE=false`.
Before checkout mutation, the bootstrap rejects a TLS overlay or non-loopback
candidate configuration; after restart it inspects the live nginx container
and requires exactly one HTTP binding on `127.0.0.1`. It also requires the live
API container to use `COOKIE_SECURE=false`. Reach the website and `/admin` only
through an operator-established SSH local-forward whose target is the
production loopback listener. Store the SSH target and ports in the operator
shell, not in this repository.

Before staging, verify the closed firewall from an independent external
network. Keep the reviewed URL only in that operator shell. A successful HTTP
connection is a hard stop, and only an immediate connection failure (curl exit
7) proves closure. A timeout is inconclusive and also stops staging:

```bash
: "${EXTERNAL_HTTP_URL:?Set the reviewed external HTTP probe URL}"
external_probe_result=0
curl --silent --show-error --max-time 10 --output /dev/null \
  "$EXTERNAL_HTTP_URL" || external_probe_result=$?
case "$external_probe_result" in
  0)
    echo 'External HTTP ingress is still reachable' >&2
    exit 1
    ;;
  7)
    echo 'External HTTP ingress is closed'
    ;;
  28)
    echo 'External HTTP probe timed out; ingress closure is unproven' >&2
    exit 1
    ;;
  *)
    echo "External HTTP probe failed unexpectedly (curl exit ${external_probe_result})" >&2
    exit 1
    ;;
esac
```

After the transition, establish the temporary forward in one operator
workstation terminal. Keep the SSH destination and selected ports in the shell
rather than this runbook:

```bash
ssh -N -L \
  "${LOCAL_HTTP_PORT}:127.0.0.1:${PRODUCTION_HTTP_PORT}" \
  "$SSH_TARGET"
```

In a second workstation terminal, probe both browser surfaces locally:

```bash
curl --fail --silent --show-error \
  "http://127.0.0.1:${LOCAL_HTTP_PORT}/" >/dev/null
curl --fail --silent --show-error \
  "http://127.0.0.1:${LOCAL_HTTP_PORT}/admin" >/dev/null
```

This temporary mode deliberately has no domain or certificate lifecycle. It is
not the clearnet launch configuration. Revisit `public-access.md` before any
public exposure.

## 5. Run the pinned one-time transition

From the candidate worktree, run:

```bash
"$CANDIDATE_WORKTREE/scripts/bootstrap-release-gate-update.sh" \
  --repository "$PRODUCTION_REPOSITORY" \
  --remote origin \
  --ref "$CANDIDATE_REF" \
  --commit "$CANDIDATE_COMMIT" \
  --confirm-fresh-backup
```

The bootstrap fails before handoff unless the branch still points to the exact
commit, both worktrees are clean, the update is forward-only, production-test
delivery is dark, and the exact commit/model quality evidence is valid. Before
checkout mutation it passes the label-derived, nonsecret Compose project name
into the candidate updater without printing it, validates the base/loopback
exposure, and persists that project name in protected `docker/.env`. It pins the
already verified object behind a temporary local remote, pins the
already-running Compose project, and invokes the candidate updater from memory.
One exclusive lifecycle lock is held from the initial identity capture through
the update, post-update checks, and any guarded rollback. Backup, restore,
health-repair, start, stop, update, and rollback operations fail closed while
that lock is held.
The normal updater performs its own second
gate check, preserves the prior commit, rebuilds/restarts, checks health, and
rolls back on handled failure. Before declaring success, the bootstrap proves
that the replacement API container still belongs to the same project and still
binds the exact pre-transition application-data directory. It also requires
every pre-existing service/destination persistent-mount mapping to retain the
same bind source or named-volume identity; newly introduced mounts may be
added. Persistent binds are limited to application data and `/var/log` state;
source, configuration, secret, and host-telemetry binds are deliberately not
state continuity records. This permits removal of the legacy API source bind
while still protecting its `/data` bind. For project selection, created and
exited API containers remain existing-stack anchors for backup, restore, and
rollback; a restarting container is rejected as unstable. Release updates,
including this live transition, require the API to be running. A cleanly
stopped stack must be started and health-checked before an update; a crash loop
requires rollback or disaster recovery. An existing FAQ database remains
authoritative even when it contains zero rows; only an absent database triggers
the one-time JSONL migration. Git reset and rollback are required to leave all
ignored runtime data in place; the updater rejects a release that would track
or overwrite it and never copies a live database or JSONL file back over an
active writer. The bootstrap also catches a nonzero exit or
handled signal after the checkout changes and invokes the candidate rollback
function before removing its temporary remote.

Do not run the installed pre-gate `scripts/update.sh` first. Do not interrupt a
healthy build merely because it is quiet; watch the operator terminal and
Docker resource state during the bounded change window.

## 6. Verify the exact live result

Before ending the window, require all of the following:

```bash
test "$(git -C "$PRODUCTION_REPOSITORY" rev-parse HEAD)" = \
  "$CANDIDATE_COMMIT"
test -z "$(git -C "$PRODUCTION_REPOSITORY" status --short)"
"$PRODUCTION_REPOSITORY/scripts/check-health.sh"
EXPECTED_BUILD_ID="build-$(git -C "$PRODUCTION_REPOSITORY" \
  rev-parse --short "$CANDIDATE_COMMIT")"
HEALTH_JSON="$(curl --fail --silent --show-error \
  "http://127.0.0.1:${LOCAL_HTTP_PORT}/api/health")"
test "$(jq -r '.status' <<< "$HEALTH_JSON")" = healthy
test "$(jq -r '.build_id' <<< "$HEALTH_JSON")" = "$EXPECTED_BUILD_ID"
```

- The API container healthcheck reports ready, and `/api/health` reports the
  expected `build-<short-candidate-SHA>` value proven above.
- Compose reports every expected critical service healthy, including the new
  Matrix alert relay; readiness does not imply a response channel is enabled.
- The website, `/admin`, and a manual web-chat request work through the SSH
  tunnel.
- The bootstrap has revalidated that all six delivery variables and
  `COOKIE_SECURE` occur exactly once as `false` inside the replacement API
  container.
- Prometheus targets and dashboards are healthy. Run an alert-delivery drill
  only after a human confirms its destination is a private staff-only Matrix
  room; this never authorizes support-room delivery.
- Existing FAQ, feedback, training, session, Bisq, monitoring, and Qdrant state
  remain present at reviewed representative counts.
- No Matrix sync, Matrix ChatOps, Bisq channel, Bisq ChatOps, or Bisq websocket
  delivery activity appears in logs or metrics.

Immediately create and scratch-verify a second encrypted backup with the now
installed scripts. Its verification summary must report zero absent volumes.
Keep the pre-transition set until the new-stack set and representative data
checks both pass.

Remove the detached worktree only after evidence is recorded:

```bash
git -C "$PRODUCTION_REPOSITORY" worktree remove "$CANDIDATE_WORKTREE"
```

Resume main merges only after the operator closes the change window.

## Failure and rollback

- A failure before candidate-updater handoff leaves the production checkout and
  services unchanged. If exact evidence already passed, the protected Compose
  `.env` may retain the verified project-name entry; it identifies the same
  pre-existing stack and does not start or recreate a service.
- A handled failure or signal after reset/build enters either the candidate
  updater's normal rollback or the bootstrap's final guarded rollback to the
  recorded prior commit while preserving production data.
- An abrupt host loss or uncatchable process termination cannot run an exit
  guard. On restart, compare the checked-out commit and service state with the
  incident record before running any script.
- If automatic rollback or disaster recovery is incomplete, stop. Preserve the
  private failure workspace and logs, keep affected services stopped, and use
  `docs/disaster-recovery.md`. Never clear a recovery-failure marker just to
  retry.
- Do not manually reset the live checkout, delete volumes, initialize an empty
  stack, or enable a response channel as a diagnostic step.
- Sanitize the incident record: commit IDs, check names, boolean switch names,
  aggregate counts, and timestamps are acceptable; endpoints, identifiers,
  credentials, prompts, answers, and decrypted data are not.

The human operator decides whether a verified rollback is sufficient or the
off-host set must be restored. Repository automation does not make that
production decision.
