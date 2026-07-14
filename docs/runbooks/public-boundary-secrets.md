# Public Boundary Runtime Secrets

Compose generates two independent runtime secrets on the first stack start:

- the scheduler API token, shared only by the API and scheduler; and
- the Alertmanager webhook secret, shared only by Alertmanager and the
  isolated Matrix alert relay.

Each secret lives in its own persistent named volume. The initializer services
have no network, a read-only root filesystem, no Linux capabilities, and write
access only to their assigned volume. They preserve a valid existing value and
fail closed on an empty, malformed, or symbolic-link secret file. Consumers
mount only their required volume read-only.

The values do not belong in `docker/.env`, deployment notes, logs, tickets, or
command output. The API and relay entrypoints load the required file into the
process environment without evaluating its contents. Alertmanager reads its
credential file directly.

## Upgrade and restart behavior

The initializer dependency is part of the Compose graph, so the first upgrade
does not depend on a newly pulled host script. A normal `docker compose up`,
restart, recreate, or `docker compose down` preserves both named volumes and
therefore preserves both credentials.

Do not use `docker compose down -v` as a routine stop command. It deletes these
secret volumes along with the stack's data volumes. The next start creates new
boundary credentials, which is an implicit rotation and may also destroy
unrelated authoritative data.

## Backup and recovery

Include both boundary-secret volumes in the disaster-recovery inventory. Treat
their contents as credentials: encrypt backups, restrict access, and never
print them during verification. Restoring each volume restores one complete
producer/consumer boundary because both consumers mount the same volume.

If a boundary-secret volume is lost while the rest of the stack remains
intact, stop both consumers for that boundary, remove only the affected volume,
and let Compose initialize a replacement before restarting them. Verify the
authenticated scheduler job or alert-delivery path after rotation. These are
human-run production steps; this repository workflow must not execute them on
a production system.

An existing empty or malformed file is not repaired automatically. Preserve it
for diagnosis, then have a human perform the deliberate single-volume rotation
procedure above.
