# Disaster recovery

This runbook covers encrypted backup, scratch verification, component restore,
and a human-run recovery drill. It does not enable either autoresponse channel
and it does not make any production change by itself.

## Recovery objectives

The operational target is a successful encrypted backup every 24 hours with
30 completed daily sets retained off-host. Alerting around the scheduled host
job must treat a missing or failed backup as an incident.

| State | RPO target | RTO target |
| --- | --- | --- |
| SQLite and application data | 24 hours | 2 hours |
| Matrix/session state | 24 hours | 2 hours |
| Bisq2 service state | 24 hours | 2 hours |
| Qdrant collections | 24 hours | 4 hours |
| Prometheus and Grafana state | 24 hours | 4 hours |
| Alertmanager state | 24 hours | 4 hours |
| Full service | 24 hours | 4 hours |

The backup is component-consistent, not a distributed transaction across all
components. The script gracefully quiesces application writers and monitoring
services, uses the SQLite online backup API, asks Qdrant for native collection
snapshots, and archives the stopped named volumes. Services are restarted
before compression and encryption, keeping the interruption bounded by the
snapshot work rather than by off-host transfer time.

## What is in a backup set

- Every SQLite database below `DATA_DIR`, including nested session stores. Each
  database has an `integrity_check` result and per-table row counts in the
  encrypted manifest.
- Authoritative non-derived application files. Evaluation outputs, logs, and
  rebuildable vector-store files are excluded.
- Matrix sync/session files (including a custom configured session filename and
  its derived encryption store) and the isolated Matrix relay volume.
- The persistent Bisq2 API data volume.
- A native snapshot for every Qdrant collection.
- Prometheus, Grafana, and Alertmanager named volumes. SQLite files found inside
  any stopped service volume are normalized through the SQLite backup API before
  the final volume archive is encrypted; WAL, shared-memory, and journal
  sidecars are not restored.
- Names found in `docker/.env`. Values are never read into the manifest and are
  never included in the backup set.

Encryption identities, Docker environment values, TLS private keys, and other
credentials must be escrowed separately under the organization's key-custody
policy. A backup is not recoverable if its age identity or GPG private key is
lost.

## One-time human decisions

Before scheduling backups, an operator must choose and document:

1. An off-host mount root and an existing target directory below it, with
   capacity monitoring and restricted access. The backup fails if the mount is
   absent; it never creates a target that could hide a vanished mount.
2. Either age or GPG, the public backup recipient, and separate private-key
   escrow with at least two authorized custodians.
3. The host scheduler and alert destination. The application scheduler is not
   used because it must not receive host-level Docker privileges.
4. A low-traffic daily backup window. The snapshot briefly stops writers and
   monitoring services.

Do not put a recipient, target path, identity path, or credential in a unit
file committed to this repository. Supply them through the host's protected
configuration mechanism using the environment-variable names below.

## Create an encrypted backup

From the checked-out release, set the protected host configuration and run:

```bash
export BACKUP_TARGET_DIR='<off-host-mounted-target>'
export BACKUP_MOUNT_ROOT='<off-host-mount-root>'
export BACKUP_AGE_RECIPIENT='<public-age-recipient>'
export BACKUP_RETENTION_DAYS='30'
./scripts/backup.sh --confirm-off-host
```

For GPG, set `BACKUP_ENCRYPTION=gpg` and
`BACKUP_GPG_RECIPIENT='<public-gpg-recipient>'` instead. The script:

1. Refuses a target inside the installation tree, requires the explicit
   off-host confirmation, and verifies that the configured mount root is a
   non-root mount containing the already-existing target directory.
2. Acquires a recovery lock and fails loudly if a required component, command,
   volume, database, or snapshot is unavailable.
3. Inspects the existing API container and requires `DATA_DIR=/data` backed by
   a bind mount whose canonical source is this release's `api/data` directory.
   This prevents a backup from silently reading a different host directory.
4. Restarts every service it quiesced, including when snapshot creation fails.
5. Writes one encrypted file atomically and only then applies retention to
   completed backup sets.

The host scheduler must run the command as an account allowed to inspect and
run the existing Compose project. Capture its exit status without copying
environment values into logs.

## Verify without changing live state

Verification decrypts into a private temporary directory, checks every outer
artifact checksum, restores selected data into scratch, runs SQLite
`integrity_check`, compares all recorded row counts, and extracts volume
archives. When Qdrant is selected (including the default `all` selection), the
script also starts an isolated internal Docker network, disposable Qdrant
volume, and matching Qdrant image; it imports every native snapshot and queries
the scratch service to prove that every recorded collection is present. The
scratch container, network, and volume are removed before verification returns.

```bash
export BACKUP_FILE='<encrypted-backup-file>'
export BACKUP_AGE_IDENTITY_FILE='<protected-age-identity-file>'
./scripts/restore.sh --backup "$BACKUP_FILE" --verify
```

Use `--component sqlite`, `--component matrix`, `--component bisq2`,
`--component qdrant`, `--component prometheus`, `--component grafana`, or
`--component alertmanager` to verify a subset. Artifact checksums for the
complete set are always checked. For GPG backups, the operator's protected GPG
keyring is used and no identity option is needed.

Run scratch verification after every backup. Scratch verification proves that
the set is internally recoverable; it is not a substitute for the periodic
disposable-environment drill below.

Qdrant verification needs the matching release's API and Qdrant images and
created Compose service containers so the script can identify their exact image
IDs. It never connects the scratch service to the production Compose network.
Verification of selections that exclude Qdrant does not require a live API
container or application-data bind mount.

## Restore selected components

Live restore is destructive and requires both `--apply` and `--yes`. It first
runs the same scratch verification. It then stops only the writers for the
selected components. Existing application files and volume contents are
captured into private temporary rollback storage before replacement; a failed
step triggers reverse-order rollback of Qdrant, already changed volumes, and
application data before services restart. Qdrant rollback uses native pre-restore
snapshots and removes collections that were absent before the restore. If any
automatic rollback step fails, the script leaves the private recovery workspace
in place, prints its path, leaves the affected services stopped, and keeps the
command failed so a human can complete recovery from those preimages.

A full Qdrant restore removes collections that are absent from the selected
backup so the recovered inventory matches that point in time. A single-
collection restore leaves unrelated collections in place. Application-data
restore likewise removes selected authoritative files that are absent from the
backup. Those removals are captured in the same private rollback transaction;
derived logs, evaluation output, and rebuildable vector-store files are never
removed by restore.

Before a live or disposable-environment restore, deploy the matching release,
recreate protected configuration with both autoresponse channels disabled, and
create the Compose service containers and named volumes. Qdrant must be running
so its native upload endpoint can recover collection snapshots. Snapshot
compatibility requires the recovery deployment to use the same Qdrant minor
version as the backup deployment.

Live restore also fails before decryption unless the existing API container has
`DATA_DIR=/data` and `/data` is bound from the canonical `api/data` directory of
that release. Recreate the API container from the reviewed Compose configuration
if this topology check fails; do not bypass it.

Restore one component at a time unless the incident requires a full restore:

```bash
./scripts/restore.sh --backup "$BACKUP_FILE" --apply --yes --component sqlite
./scripts/restore.sh --backup "$BACKUP_FILE" --apply --yes --component matrix
./scripts/restore.sh --backup "$BACKUP_FILE" --apply --yes --component qdrant
```

To restore one Qdrant collection, add
`--qdrant-collection '<collection-name>'`. Use `--component all` for full state.
The restore never writes `docker/.env`; recreate protected configuration from
the separate credential escrow, then compare its variable names with the
encrypted inventory.

After a restore:

1. Confirm all stopped services were restarted.
2. Run `./scripts/check-health.sh` and inspect the truthful readiness component
   breakdown.
3. Confirm the expected FAQ and escalation row counts and sample records.
4. Confirm every expected Qdrant collection is present and retrieval succeeds.
5. Confirm Prometheus targets and Grafana dashboards load historical data.
6. Confirm Matrix sessions reconnect without sending an automatic response.
7. Confirm Matrix and Bisq autoresponse flags remain disabled.
8. Record the backup set identifier, selected components, start/end times, and
   validation results in the incident record without copying secrets.

## Human-run restore drill

Run this checklist at least quarterly and after any storage-layout change. A
human operator owns drill execution and sign-off.

- [ ] Select a recent completed set without using the newest set exclusively.
- [ ] Record the target RPO/RTO, drill start time, and backup creation time.
- [ ] Verify the encrypted set in scratch with `--verify`.
- [ ] Provision an isolated disposable recovery environment with no user-facing
      delivery route and with both autoresponse channels disabled.
- [ ] Recreate protected configuration from escrow and compare inventory names.
- [ ] Restore all components with `--apply --yes --component all`.
- [ ] Run health/readiness checks and validate representative SQLite row counts.
- [ ] Validate every Qdrant collection and representative retrieval queries.
- [ ] Validate Prometheus history and Grafana dashboards.
- [ ] Validate Matrix session recovery without sending a response.
- [ ] Measure achieved RPO and RTO against the table above.
- [ ] Destroy the disposable environment and any decrypted scratch data.
- [ ] Record gaps, owners, and due dates; do not place secret material in the
      drill record.

Escalate any failed checksum, integrity check, row-count comparison, missing
collection, missing environment name, or missed RPO/RTO. Do not continue a
live restore with a set that fails scratch verification.
