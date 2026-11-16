# Host-owned monitoring for bounded Staff pilots

A Staff pilot must not depend on a Codex turn, provider quota, an operator laptop,
or an SSH control socket to stop at its fixed cutoff. The host coordinator in
`scripts/staff_pilot_watchdog.py` runs metadata checks every twelve hours and has
a separate persistent, absolute UTC cutoff timer. Codex's twelve-hour evidence
review is optional to operational safety; it does not capture room history.

This is a preparation capability. Installing these files, enabling timers,
binding a descriptor, starting a pilot, or altering the existing six-job hold
requires the separately reviewed production lifecycle. No current or old frozen
trial helper is replaced by this code. Never point a new binding at an old trial
whose phases were already attempted.

## Existing protection and the added protection

`ContextTrialStore.reserve()` persists reservations atomically and rejects new
admissions at the cap or deadline. Existing reservations can finish before the
deadline. `context_runtime._expire_trial()` disables the generation policy and
closes the context runtime at expiry, and generation/delivery boundaries check the
trial again. These guards do not complete the host's sync-off and scheduler
finalization lifecycle.

The host coordinator adds that terminal lifecycle independently of Codex:

- The twelve-hour check reads the cap directly from the existing SQLite ledger
  before depending on full application health. A missing initial descriptor row
  is accepted only with zero reservations. Retained reservations consume capacity
  even if the related case was removed. Malformed or missing case status is
  uncertain, never evidence that a reserved operation finished.
- At the cap, active or uncertain work gets at most 120 seconds to drain, bounded
  by the fixed cutoff, and one metadata reread. A failed reread cannot cancel the
  stop obligation. Remaining activity stays uncertain; containment does not prove
  completion of that model call or delivery.
- At the cutoff, the host attempts stop and then scheduler-finalize without an
  initial health dependency or drain. The cutoff service waits for the same
  coordinator lock as the health service; its timer event cannot be coalesced
  into an already-running health unit. Each blocking read is followed by a cutoff
  check. The existing canonical lifecycle wrapper retains its separate inherited
  lifecycle lock against deployment/other operators.
- Canonical intents and receipts establish success. Existing, partial, failed or
  ambiguous attempts are observed only. There is no terminal retry, no scheduler
  recreation, no guard retirement, and no automatic restart of a failed phase.
- A successful health observation and its reviewed checkpoint are saved in one
  atomic, fsynced `last-success.json`; `checkpoint.json` is a derived cache. Failed
  observations preserve the last valid success. Corrupt reporting state does not
  prevent a bound due stop, but it prevents a new success claim until reconciled.

The host must be up and its Docker/filesystem dependencies must work. The design
does not guarantee successful shutdown during a host outage, hung kernel or
failed containment. `Persistent=true` catches up a missed cutoff after boot;
`OnBootSec=1min` also checks retained state. An elapsed boot delay fires immediately when a timer is enabled, so install/arm only after runtime and sync readiness, with generation still off. See the [systemd timer contract](https://www.freedesktop.org/software/systemd/man/254/systemd.timer.html). Recorded shutdown/finalization delays
come from the canonical completion timestamps, never from the latest observation.
A busy health service can delay the cutoff attempt by its remaining bounded work;
its own deadline checks minimize that delay. Report actual timestamps rather than
calling the one-second timer accuracy a one-second shutdown guarantee.

## Prepare a new package without activating it

Keep the new descriptor, source freeze, local/transport intents and canonical
phase directory separate from every predecessor. Preserve all predecessor
receipts, held cases, established Matrix identity/session/cursor and trial data.
The maximum remains twenty reservations and at most seven days; timestamps must
use whole UTC seconds so the rendered timer cannot fire before the bound cutoff.

The adapter `scripts/staff_pilot_watchdog_adapter.py` uses the existing helper
contracts. It needs a new reviewed copy/binding of the ordinary health helper and
canonical control shell; do not execute historical helpers unchanged. Its four
modes are:

| Mode | Actual operation | Result |
|---|---|---|
| `limits` | SQLite `mode=ro`, `query_only=ON`, count/status projection | Bound IDs, counts, booleans and timestamp only |
| `health --checkpoint PATH` | Pinned Python health helper with its existing `--trial-dir` / `--checkpoint` CLI | Existing compact health and `next_checkpoint` schema |
| `stop` | Pinned `/bin/bash CONTROL stop DESCRIPTOR_SHA none` | Existing canonical stop intent/receipt, unchanged |
| `scheduler-finalize` | Same canonical shell with that phase | Existing canonical finalization intent/receipt, unchanged |

The control shell, not a direct Python controller invocation, owns and passes the
canonical lifecycle lock. Adapter terminal stdout/exit zero is never accepted as
proof of completion. Canonical receipt fields already match the coordinator;
there is no receipt conversion that could erase a historical failure. Tests use
sanitized fixtures with the real saved health/receipt field structure.

The adapter config contains exactly `schema`, `binding_path`, `descriptor_path`,
`database_path`, `health_command`, `phase_commands`, and `files_sha256`. Its schema
is `staff-pilot-watchdog-adapter-v1`. Pin all imported helpers and control-shell
sources in both adapter and coordinator manifests. The coordinator additionally
pins the adapter config, adapter, coordinator and descriptor. All source/config
files are root-owned private regular files, installed mode 0600; parent directories
are root-controlled. Python reads the files; an executable mode is unnecessary.

The coordinator binding contains exactly `schema`, `trial_id`, `revision`,
`descriptor_sha256`, `start_at`, `end_at`, `max_cases`, `state_dir`, `phase_dir`,
`metrics_path`, `commands`, `files_sha256`, and `receipt_lineage`. Its schema is
`staff-pilot-host-watchdog-v1`. `receipt_lineage` must identify the new activation
or continuation authority actually present in both canonical intent and receipt;
never use a fabricated predecessor lineage. Each command is:

```text
/usr/bin/python3 -B /NEW/PACKAGE/staff_pilot_watchdog_adapter.py --config /NEW/PACKAGE/adapter.json --config-sha256 CONFIG_SHA MODE
```

Build the adapter config and hash it first; then build/hash the coordinator
binding. The adapter obtains `STAFF_PILOT_BINDING_SHA256` from the coordinator's
fixed subprocess environment, avoiding a self-referential hash in the binding's
command list. A direct adapter review invocation can pass `--binding-sha256`.
Call `render_units()` with the final installed paths and binding hash to prepare
both services, both timers and the expectation metric. It does not install them.
Unbound placeholders intentionally fail validation; no default descriptor or
activation window is selected by the code.

## Installation and activation acceptance

Before installation, inspect existing cron jobs, host timers, Docker workers and
lifecycle ownership for duplicates. Do not add polling workers or change the
existing Matrix subscription. Review the entire new source manifest, descriptor,
retained-history baseline and canonical control wrapper. Complete the repository's
applicable signed-identity, release and operator gates for any production change.

A separately authorized installer must then:

1. Install the private package and state directory (0700), and only its four
   prepared systemd units. Resolve the established node-exporter textfile volume
   to its exact current host mount without recreating scheduler or node-exporter.
   Install `staff-pilot-expected.prom` there, separate from the mutable status
   metric and from all existing retention metrics. Load the reviewed Prometheus
   rule normally; do not disable unrelated privacy alerts.
2. Enable/start the two timers, run the initial metadata check with generation
   still off, and inspect the loaded units and their next triggers. No code here
   enables generation, posts messages or adds an autonomous paid batch.
3. Run `staff_pilot_watchdog.py --binding PATH --binding-sha256 SHA
   --verify-installation` and save its exact output/hash in the activation packet.
   It reads installed file content, ownership/modes, systemd load state, no
   drop-ins/no pending reload, active/enabled timers, the effective future cutoff
   and health triggers, and a fresh successful initial health record. Missing or
   mismatched evidence refuses acceptance. The actual activation controller must
   require this approved receipt immediately before generation-on. A rendered
   unit, an installer exit zero, or an inactive elapsed timer is not acceptance.
4. Verify the expectation and result metrics are scraped for this exact binding,
   and validate alert configuration. Keep that evidence with the activation
   receipt. The static expectation makes missing result series an alertable
   failure; a stale predecessor binding cannot cover a new pilot.

The new pilot is not ready to enable generation until this actual installation
acceptance exists. Offline tests and staged templates are not installation proof.

## Failures, closeout and optional operator SSH

`StaffPilotWatchdogMissingOrFailed` fires after a failed attempt, missing status,
more than twelve hours plus fifteen minutes without successful host health, or
no verified finalization fifteen minutes after cutoff (then a two-minute alert
hold). Node-exporter/Prometheus availability requires the existing infrastructure
alerts as well; this one rule cannot detect its own absent expectation or a dead
monitoring stack. The activation acceptance closes the absent-expectation setup
gap. Never fabricate fresh success timestamps to suppress an alert.

Inspect `last-attempt.json`, the last valid success and canonical phase intent /
receipt files. An uncertain terminal attempt requires read-only reconciliation;
never delete its intent or repeat the phase. Repair observation/transport only.
A stop receipt with an outage or incomplete preservation is failure, not success.

After verified stop, cutoff, finalization, final healthy observation and durable
metrics, `finalized.json` prevents further timer work. The ordinary authorized
closeout removes only the two owned timers/services after saving operational and
value reports. Do not retain periodic reads to await voluntary human reviews.
Retain the final expectation/result or retire both in the same reviewed cleanup;
never erase existing retention or predecessor evidence.

For optional operator evidence transport, use `no_multiplexing(existing_ssh_argv)`
when preparing a new reviewed transport. It inserts `ControlMaster=no`,
`ControlPath=none`, and `ControlPersist=no` before inherited options, preserving
the existing host-key policy, SSH identity, BatchMode and exact remote read scope.
It does not edit an old helper or SSH config, recreate an ephemeral socket
folder, or weaken trust. The host's safety path itself uses no SSH.
