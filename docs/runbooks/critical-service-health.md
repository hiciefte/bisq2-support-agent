# Critical service health

## Impact

One or more required services is unavailable, functionally degraded, or no
longer producing probe metrics. Public requests or operator alerting may be
impaired.

## Confirm

1. Run `./scripts/check-health.sh --json` and identify the affected service.
2. Check whether `CriticalServiceProbeFailed`, `CriticalServiceProbeMissing`,
   `BlackboxExporterUnavailable`, or a container alert is firing.
3. Compare the functional probe with the service's Docker health status and
   recent logs.

## Triage

1. If probe metrics are missing for every service, restore Prometheus or the
   blackbox exporter before diagnosing individual targets.
2. If one probe fails, check that service's own health endpoint and its direct
   dependencies.
3. Use the repository lifecycle scripts for restart or rollback. Do not edit
   running containers or production configuration directly.
4. Keep autonomous channel delivery disabled while any required dependency is
   degraded.

## Recovery

### Bisq2 heap exhaustion

If the Bisq2 API probe times out while its Java process uses high CPU, compare
the JVM heap occupancy and full-collection count over time. Check recent logs
for `OutOfMemoryError: Java heap space` and inspect container memory events.
Java heap exhaustion can occur below the container memory limit, leaving the
container running but its API unresponsive.

The default `BISQ2_JAVA_OPTS` allows a 2 GiB heap and exits on unrecoverable
out-of-memory errors so Docker can restart the node. Size overrides against
both the 4 GiB container limit and the host's available memory; leave room for
native memory, threads, Tor and other services. Use `docker/.env` for the
override and the authorized lifecycle workflow to recreate the container.
Record the previous option string, image ID, volume mounts and restart count
before an authorized change, and preserve the Bisq2 data volume and API auth
state. Rollback restores the prior options/image and recreates the service
using the same stores.

After recovery, confirm the running JVM arguments and effective heap limit,
both API probes, stable container restart count, and CPU/heap behavior after
Tor/P2P initialization. Recheck after the next scheduled workload and over a
longer observation window. Repeated OOM exits or rising retained heap require
a Bisq2 memory investigation; increasing the heap alone does not fix a leak.
Do not collect or publish heap dumps casually: they can contain private chat
and authentication data.

The service probe and Docker health check must both remain healthy for at least
five minutes, and the missing-metric alert must be clear.
