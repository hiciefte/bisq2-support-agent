# Deployment workflow

`scripts/update.sh` is the release entrypoint. Its selective controller uses the
checked-in plan, host, recovery and journal implementations. The legacy updater
path remains available; it is not an implementation of the controller's durable
continuation contract.

The controller has a local execution and validation path. A prepared plan, an offline test, or
a completed journal does not establish production readiness or authorize a
release. Before production use, complete the disposable Linux rehearsal and
operational review described below. Matrix activation retains a separate scope.

## Prepare and inspect

Use a local repository containing the exact previous and candidate commits.
Supply full 40-character commit IDs, a future UTC deadline, the exact affected
service set (`api`, `web`, or `api,web`), and the configured host-profile name.

```bash
scripts/update.sh plan \
  --repository /path/to/repository \
  --previous "$PREVIOUS_COMMIT" \
  --commit "$CANDIDATE_COMMIT" \
  --services api,web \
  --profile production \
  --deadline "$DEPLOYMENT_DEADLINE_UTC" \
  --operation /path/to/private/operations/release-001

scripts/update.sh status \
  --operation /path/to/private/operations/release-001
```

Planning reads committed local Git objects. It does not fetch, build, connect to
a host, load secrets or modify the source/index/runtime. The requested operation
parent must already exist. Plan creation rejects traversal and symlink paths,
exclusively creates a private operation directory and `plan.json`, and syncs the
record and both directory entries before success. Partial creation is retained
on failure and cannot be overwritten. Inside the source checkout, outputs are
restricted to ignored `.agent-artifacts/` or `failed_updates/` directories.

The planner accepts a conservative subset of selective API/web source changes.
It refuses migrations, runtime data, catalogues, Compose, operational scripts,
unknown paths and mismatched services. Dependency changes can be planned; live
compatibility still requires the reviewed release checks. Unknown changes are
not guessed into a deployment capability.

New plans use `deployment-plan-v2`. The source commit/tree pins and exact phase
sequence include source publication after postchange restore verification.
Existing v1 plans remain readable for status but cannot authorize effects;
prepare and approve a new v2 plan rather than modifying an old journal.

## Protected profile and explicit approval

`scripts/lib/deployment_protocol.py` is the shared producer/consumer contract.
Its private `deployment-profile-v1` record binds:

- A fixed SSH alias or explicit local rehearsal mode, with an absolute host
  Python reference. There are no user-supplied command strings or hooks.
- Exact installation, staged candidate, operation parent and Compose project;
  the canonical Compose filename, quality remote and loopback HTTP readiness
  endpoint. The candidate tools checkout is separate from the installation.
- A server ciphertext export directory and public encryption-recipient file
  reference; an operator-local private destination, verifier tools checkout and
  identity-file reference. The server does not read the operator's key file.
  The local operation's recovery directories must be beneath that destination.
- The verifier's Docker executable and hash, socket, immutable tooling/API/Qdrant
  image IDs, container UID/GID, and the fixed host/recovery helper hashes. Container
  identity is explicit because the Docker VM's socket ownership can differ from
  the host user; local files and key references must remain operator-owned.
- Bounded phase and readiness timeouts. Profiles do not contain configuration,
  credential or key contents, arbitrary environment overrides, or image tags.

The external `deployment-approval-v1` record binds canonical plan/profile
SHA-256 hashes, the exact ordered phase scope, operator, approval time and UTC
deadline. It explicitly allows the standard and live-MCP smoke calls for an API
release, data-compatible availability rollback, and private disabled channels.
Web-only releases have no model-smoke scope. Empty, broad, mismatched or expired
approvals cannot authorize effects. Creating or validating a record does not
supply the human authorization required by the release policy.

Both the client and host check the current approval window before effects.
Read-only status and reconciliation remain available after expiry. Completion
of an already-started effect can be recorded after the deadline; expiry never
permits a new effect or a replay.

## Apply, continue and reconcile

After the separate exact-release approval and required acceptance evidence:

```bash
scripts/update.sh apply \
  --operation /path/to/private/operations/release-001 \
  --profile /path/to/private/host-profile.json \
  --approval /path/to/private/release-approval.json

scripts/update.sh continue --operation /path/to/private/operations/release-001
scripts/update.sh reconcile --operation /path/to/private/operations/release-001
```

Apply snapshots the exact protected profile and approval. Continue consumes that
binding and runs only a proven unattempted phase following a successful prefix.
Reconcile is read-only: it reads host status and receipts without mutating the
journal or replaying an effect. Status is entirely offline. A missing outcome,
failed effect or conflicting receipt requires investigation; another invocation
is not a retry authorization.

A fixed dependency-free bootstrap verifies the host helper hashes before loading
repository code. It transports the same checked-in source for every release;
only protected path and hash metadata varies. The fixed transport opens one
persistent host owner, which holds the existing
production lifecycle lock while the local client receives and restore-verifies
ciphertext. Host operation identity derives from the plan hash, so copying the
same approved plan into another client directory does not create a fresh host
attempt namespace. A global active-operation marker under the canonical recovery
directory also blocks a different plan or legacy lifecycle command after an
interrupted operation. It is retired only after fresh completion verification.
The client journal and host exclusive effect receipts retain
uncertainty across connection loss. The transport accepts fixed operations, not
arbitrary shell commands from profiles.

The supported sequence is:

1. Verify the exact source, quality gate, fresh identities and preserved state;
   build immutable images while current services remain available.
2. Pause the same scheduler only if this operation owns that change. Capture an
   encrypted prechange backup, promptly resume its writers, transfer ciphertext
   and verify a full isolated restore before switching services.
3. Switch only selected API/web services to the recorded image IDs; verify actual
   readiness and proxy routing. Run each authorized API smoke once.
4. Capture, transfer and fully restore-verify the postchange backup. Publish the
   pinned source and restore the scheduler's original pause state, preserving
   its process and held-job configuration.

Success receipts bind plan/profile/intent and the fresh baseline hashes. Their
phase-specific payloads carry immutable identities and required preservation,
readiness and recovery proofs. Both producer and consumer use the same strict
validator. Unknown keys, incomplete recovery, another baseline or source,
wrong verifier image, partial service sets and false preservation flags refuse
success. Completion additionally joins the saved fresh host verification and its hash;
phase counts alone cannot claim completion. Raw diagnostics remain private; public-facing errors use closed codes.

## Shared operational invariants

Backup verifies each quiesced writer's immutable Docker identity before and
after its one resume attempt. A zero Compose exit is insufficient: the same
container must be running, unpaused, not restarting, with a positive PID.
Application readiness is a separate check. Identity hashes preserve all Config
and mount content while ignoring object-key and outer mount-list ordering.

Service replacement compares unique environment names and values without relying
on Docker's list order; duplicate or malformed entries refuse the switch. The
existing build-ID allowance is separate. Compose builder metadata may differ only
when the saved build evidence proves it belongs to the exact candidate image.
These replacement rules do not relax existing-container identity hashes.

Failed captures, partial ciphertext and diagnostics remain available for
reconciliation. They are not successful backups. Cleanup errors propagate; an
uncertain writer resume is not retried by an exit trap. Full Docker configuration
can contain secrets and stays private, outside the archive payload.

On Linux, backup and update share the canonical lifecycle lock. A backup may
borrow an inherited descriptor only after checking its inode and actual
exclusive lock. It never unlocks its parent. The controller and its bound
borrowed backups can inventory an already-paused scheduler; its original pause
is preserved, not claimed or resumed. Ordinary callers and other paused services
retain the refusal. Scheduler pause ownership differs from lock
ownership; neither permits recreation or execution of held jobs.

## Acceptance before production

The complete path requires a disposable Linux rehearsal through the real
entrypoints and receipt consumers. Prove interruption handling before/after
effects, no replay of uncertain smokes/captures/switches, retained backups after
downstream failure, actual restore and cleanup, unchanged unrelated identity
and data, bounded availability recovery and the same scheduler with held jobs.
Measure downtime. Helper tests and synthetic receipts do not prove these live
properties or replace an exact-head independent review.

The exact-commit quality gate, report review, production authorization and
recovery requirements in [the production transition runbook](production-gate-transition.md)
remain required. Deployment does not enable Matrix or establish natural answer
quality. No task-generated adapters or approval materializers are needed to
operate the fixed protocol; historical operation evidence remains preserved.

For a known failed service switch, the controller may restore availability once
using the recorded old immutable image, only while its authority, exact topology
and data-compatibility conditions still hold. The failed rollout, scheduler hold
and active-operation marker remain visible. An uncertain switch or any started
smoke refuses automatic availability restoration. It never restores application
data or rewinds a database as part of this source-only recovery.

The installed Python interpreter, SSH trust configuration and operator-local
controller are trusted deployment tooling. A profile is a protected configuration
record, not executable policy supplied by an application or model response.
