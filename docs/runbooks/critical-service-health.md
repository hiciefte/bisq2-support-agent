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

The service probe and Docker health check must both remain healthy for at least
five minutes, and the missing-metric alert must be clear.
