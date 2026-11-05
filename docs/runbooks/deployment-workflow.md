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
By default it refuses operational scripts, migrations, runtime data, catalogues,
Compose, unknown paths and mismatched services. The explicit capabilities below
admit only their individually bound exceptions. Dependency
changes can be planned; live compatibility still requires the reviewed release
checks. Unknown changes are not guessed into a deployment capability.

Ordinary plans use `deployment-plan-v2`. The source commit/tree pins and exact phase
sequence include source publication after postchange restore verification.
Existing v1 plans remain readable for status but cannot authorize effects;
prepare and approve a new v2 plan rather than modifying an old journal.

### Releases that update the deployment tooling

For a reviewed release that also changes the controller, add
`--include-deployment-tooling` to the `plan` command. This creates a
`deployment-plan-v3` with the distinct
`selective-api-web-with-tooling-v1` capability. Its `tooling_sha256` map names
every changed file in the fixed `DEPLOYMENT_TOOLING` allowlist in
`scripts/lib/deployment_protocol.py`, with hashes derived from the candidate's
committed Git blobs. Only these deployment entrypoints and libraries are
supported; the option does not admit arbitrary scripts or remove paths from the
source diff. Deleted tooling files and symlinks are refused.

The host independently derives the complete changed tooling set and hashes
before effects and again when verifying source publication. Missing, extra or
wrong pins refuse the release. A v3 plan requires a `deployment-approval-v3`
record with an identical `tooling_sha256` map; an ordinary v2 approval cannot
authorize it. Review the complete tooling diff before granting that capability.
Existing plans and attempted operations must never be upgraded in place.

### Preserve an already-applied Bisq2 heap repair

The separate `--preserve-bisq2-heap-repair` option creates a
`deployment-plan-v4` with `selective-api-web-preserved-heap-v1`. It carries only
the fixed change from the former 1 GiB JVM heap to the reviewed 2 GiB heap and
exit-on-OOM configuration. The complete Compose, Bisq2 Dockerfile and example
environment blobs are pinned in the plan and matching `deployment-approval-v4`.
Any other edit in those files is refused. The option can be combined with
`--include-deployment-tooling`; its tooling pins remain separately explicit.

Before any effect, the installation must contain exactly the unstaged Compose
repair already equal to the candidate blob, with an otherwise unchanged index
and clean source tree. The existing Bisq2 node must already run the repaired
options, 4 GiB container limit and `always` restart policy. Normal plans continue
to refuse dirty source and all Compose changes. This capability does not apply
the runtime repair, rebuild or recreate Bisq2, modify its volume, or authorize
other operational/configuration changes.

Only after both backup/restore chains and the API/web checks succeed, the
journaled `publish_source` phase adopts that exact Compose blob into the index
and fast-forwards the source. It does not reset, stash or rewrite the existing
Compose file. The effective Compose configuration and all unrelated container
identities remain equal to the captured baseline. Its receipt explicitly proves
heap-source reconciliation. A failure after index adoption remains an attempted
publication requiring read-only reconciliation; it is never a fresh attempt or
permission to stage other files. Preserve the original dirty-patch evidence.

This mode still requires a real API or web source change. Tooling-only releases
are not supported. For a tooling and web dependency release with no API source
change, select only `web`: API tests do not select an API restart, and the plan
contains no API smoke calls. All backup, restore, scheduler preservation,
deadline, recovery and once-only execution rules remain unchanged.

For first use, stage the entire exact candidate as a clean, separate checkout
and bind it in the protected profile. The fixed bootstrap can execute its
hash-checked helpers before that revision is installed. The controller publishes
the source only after postchange restore verification. Do not copy helpers into
the live installation, advance its source manually, filter its diff or repeat
the historical pre-quality-gate transition to bypass commissioning.

### Publish reviewed retention monitoring without recreation

`--include-retention-monitoring` selects `deployment-plan-v5` and
`selective-api-web-with-monitoring-v1`. Its matching approval explicitly pins
all four fixed monitoring files: scheduler heartbeat, Prometheus alert rules,
their rule test fixture, and the offline monitoring validator. It does not admit
other monitoring/configuration paths. Tooling and already-applied heap repair
remain separate pin maps and optional flags.

For the reviewed Python runner compatibility repair only,
`--include-python-runner-pins` additionally binds the complete two workflow
blobs. The planner and host require exactly three `ubuntu-latest` to
`ubuntu-24.04` runner replacements in the named Python jobs, including the fixed
explanatory comment. Every other byte must match the previous commit. Model,
permission, step and other workflow changes remain refused.

Preflight requires the original scheduler to be unpaused, fresh heartbeat
telemetry, exact host-to-container bind sources and bytes, and valid candidate
rules checked by the existing Prometheus `promtool`. It records the heartbeat
inode/ownership/mode and successful Prometheus reload timestamp. Candidate and
loaded rule expressions are compared using that same installed PromQL formatter;
the experimental CLI flag enables formatting only, not server features.

The canonical backups stop and start Prometheus without replacing its container.
After each successful capture, the controller records a separate process/reload
checkpoint joined to that capture intent and canonical receipt. It requires the
same container/configuration/mount identity and the zero restart count produced by
Docker's explicit start, including when the prior automatic restart count was
nonzero. The checkpoint binds the exact raw receipt hash accepted by capture,
not merely an equivalent parsed record. Process startup and successful
configuration load must fall inside the owner's directly sampled capture call
window. The initial baseline remains immutable. Later process checks and publication use the latest verified checkpoint; a later unexpected
process restart or publication-time reload drift is refused. A slow initial
configuration load after the accepted capture return remains unproved and fails
closed, requiring reconciliation; it does not authorize a backup retry or a broader
restart exception. An exclusive intent precedes the capture; a separate exclusive
completion record joins that intent, the accepted receipt hash and wall/monotonic
clock samples immediately around the capture call. Monotonic elapsed time must fit
the measured wall-clock sampling envelope; this adds no timing grace to the allowed
process/reload window. Filesystem mtimes are checked for later tampering, not used
as clock authority, so coarse filesystem timestamps cannot move the window.

Inside the existing journaled `publish_source` phase, with the scheduler paused,
the controller writes the pinned heartbeat bytes in place, fsyncs, verifies the
actual mounted bytes, and adopts only that blob into the index. The subsequent
fast-forward preserves the single-file bind inode. During publication, Prometheus
keeps its latest verified container and process: configuration validation precedes
one HUP, followed by bounded observations requiring a newer successful reload
and the exact loaded rule expressions. A partial write, index adoption or uncertain HUP is an attempted
phase requiring reconciliation, never permission to retry.

After its one ordinary scheduler resume, the controller waits for the existing
cron to publish a fresh heartbeat with valid six-job hold proof. It never invokes
the heartbeat or held jobs directly. A resumed old invocation can produce one
legacy-format sample; that is not acceptance, and observation continues within
the original timeout. Partial or contradictory new hold fields fail. Acceptance
also requires Prometheus to consume that new sample, evaluate the hold recording
rule afterward, and clear the four held-job missing/stale alerts. Stored sample
times come from `timestamp(...)`, not instant-query evaluation times.

Publish/resume receipts carry explicit monitoring proofs. Failure to observe the
normal resumed heartbeat is a failed resume phase even if the scheduler has
already returned to its original running state; preserve the recorded attempt
and reconcile without replay. The six held jobs, scheduler command/crontab,
Prometheus runtime configuration, and unrelated services remain preserved.

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

The external `deployment-approval-v2` record (v3 for the explicit tooling
capability above) binds canonical plan/profile
SHA-256 hashes, the exact ordered phase scope, operator, approval time and UTC
deadline. It explicitly allows the standard and live-MCP smoke calls for an API
release, data-compatible availability rollback, and private disabled channels.
Web-only releases have no model-smoke scope. Empty, broad, mismatched or expired
approvals cannot authorize effects. Creating or validating a record does not
supply the human authorization required by the release policy.

The approval also names the physical `image_consumers` for each selected service.
An API release must include `matrix-alert-relay` when it is present because both
consume the API image. The controller checks this scope against the existing
topology before effects; it never adds a consumer to an existing approval. The
API and relay switch together and each must pass readiness. A known failed
switch restores both to their original image together; unrelated services remain
unchanged. A deployment without the relay can explicitly bind only `api`.
Version-1 approvals do not authorize this expanded contract. Prepare a new
version-2 approval, or version 3 for the tooling capability, for a new operation;
never rewrite an attempted journal.

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

If all phases succeeded but the final transport reply was lost, `continue` can
recover completion only when both local completion records are absent. It reads
the already-saved host reply through the reconciliation transport, validates its
receipt bindings, and publishes local records exclusively. It does not rerun
finalization, runtime probes or effects, and reports the original verification
time. A partial or malformed local record, or a missing saved host reply, still
requires read-only investigation.

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
   encrypted prechange backup, promptly resume its writers and verify API routing,
   then transfer ciphertext and verify a full isolated restore before switching
   services.
3. Switch only selected API/web services to the recorded image IDs; verify actual
   readiness and proxy routing. Run each authorized API smoke once.
4. Capture, transfer and fully restore-verify the postchange backup. Publish the
   pinned source and restore the scheduler's original pause state, preserving
   its process and held-job configuration.

After each canonical capture resumes its writers, the controller validates the
existing Nginx configuration and reloads it once to refresh upstream addresses.
A writer can receive a different Docker address while keeping its container ID.
The controller requires direct API readiness and the expected API build through
`/api/health` before publishing the backup phase receipt. Route observations may
repeat within the phase's remaining readiness budget while Nginx workers drain;
the capture and reload are never retried. The Nginx container, configuration and
master process remain preserved; workers may change during reload.

The selected-service switch and its one permitted availability restoration also
reload Nginx once after direct service readiness. API `/api/health` and web `/`
observations then wait within the existing readiness and phase deadlines for the
expected build. A stale build, unavailable upstream or malformed API response
can be observed again while workers change; the switch and reload are not
retried. A route that never exposes the expected build fails the phase and keeps
the scheduler held. Preflight and final verification remain strict single route
observations without reload or convergence waits.

API routing is checked again before releasing the scheduler and during final
completion, including web-only releases that retain the original API image and
build. These last checks do not reload Nginx or call a model. A failed route check
cannot produce a successful completion; a failed post-capture check retains the
capture evidence and scheduler hold for reconciliation.

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

Replacement comparisons also tolerate two Docker inspection representations:
present `Dns`, `DnsOptions` and `DnsSearch` values may change between `null` and
`[]`, and `MaskedPaths` may reorder the exact same absolute path strings.
Missing fields, nonempty DNS order/values, changes to mask entries or multiplicity,
and every other HostConfig field remain material. No stored snapshot is rewritten.
Docker selects DNS overrides only for nonempty lists, so both empty forms inherit
the same daemon settings ([Moby sandbox configuration](https://github.com/moby/moby/blob/v28.5.1/daemon/container_operations.go#L64-L77)).
The mask comparison follows the OCI requirement that each listed absolute path
is hidden, retaining the same entries and multiplicity ([OCI masked paths](https://github.com/opencontainers/runtime-spec/blob/v1.2.1/config-linux.md#masked-paths)).
`MaskedPaths: null` and `MaskedPaths: []` are deliberately different: Docker
supplies default masks only for `null` ([Moby container creation](https://github.com/moby/moby/blob/v28.5.1/daemon/create_unix.go#L32-L39)).

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
