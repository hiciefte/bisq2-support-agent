# Scheduler Job Capabilities

The production scheduler is an unprivileged cron container. It has no Docker
socket, Docker client, or admin credential. Jobs that mutate application state
call single-purpose FastAPI endpoints over the private Compose network with a
dedicated `SCHEDULER_API_TOKEN`. Production nginx returns 404 for every
`/api/internal/*` request, and an admin credential cannot authenticate these
endpoints.

Compose provisions the scheduler token as a non-rotating runtime secret before
the API or scheduler starts. The API fails closed when it is absent or shorter
than the minimum credential length. Do not add it to `docker/.env`, reuse
`ADMIN_API_KEY`, or expose the token to the browser-facing web service. See
[Public Boundary Runtime Secrets](public-boundary-secrets.md) for persistence,
recovery, and deliberate rotation procedures.

## Job inventory

| Schedule | Job | Required capability | Mechanism |
| --- | --- | --- | --- |
| Container start and weekly | Feedback processing | Read stored feedback and update learning weights | `POST /internal/scheduler/process-feedback` |
| Weekly | Wiki refresh | Download/process wiki data and rebuild the live index | `POST /internal/scheduler/update-wiki`; writes under configured `DATA_DIR` and runs the forced build in a bounded worker thread behind the live-index locks |
| Daily | LLM-Wiki reconciliation | Read and update the unified training repository | `POST /internal/scheduler/reconcile-llm-wiki-coverage` |
| Container start and daily | Privacy retention | Delete or anonymize out-of-window records and compact changed SQLite databases | `POST /internal/scheduler/privacy-retention`; supports `dry_run=true` |
| Daily | Bind-mounted log retention | Rotate and age scheduler/nginx logs | Allowlisted bind mounts only; no Docker access |
| Every 12 hours | Bisq and Matrix training sync | Invoke one ingestion source at a time | Separate `training-sync/bisq` and `training-sync/matrix` endpoints |
| Every 10 minutes and container start | Bisq readiness | Read-only MCP probe | Direct private-network MCP request; no privileged token |
| Every 15 minutes | RAG health | Read Prometheus metrics; optionally send an operator-configured heartbeat | Direct private-network Prometheus request; blank `HEALTHCHECK_URL` disables the external heartbeat |
| Every minute | Cron heartbeat | Touch scheduler-local health file | No network or application capability |

Each scoped endpoint returns a non-2xx response on task failure so cron cannot
mistake an error payload for success. External responses are generic; detailed
exceptions remain in API logs.

## Docker and host maintenance

None of the scheduler jobs requires Docker access. Application jobs run inside
the API container, and the wiki job rebuilds the live index without restarting
a container. Blocking document, embedding, and Qdrant work runs off the public
event loop; the stable Qdrant alias keeps the previous reader live until the
replacement reader is ready. Docker cleanup remains a separately documented,
human-installed host maintenance task under `docker/scripts/maintenance/`; it
is not mounted into or invoked by the scheduler.

Docker runtime-log age retention is likewise host-managed. Use
`scripts/configure-runtime-log-retention.sh --check` and follow
[Privacy Retention](privacy-retention.md); do not give the scheduler access to
the Docker API.

## Verification

Before deployment, inspect the resolved scheduler service without printing its
environment values:

```bash
docker compose config --format json \
  | jq '.services.scheduler | {volumes, command, environment_keys: (.environment | keys)}'
```

Confirm that the output has no Docker socket, Docker client installation, admin
credential, or scheduler token environment key. It should instead contain the
read-only `scheduler-api-secret` volume and source the runtime-secret loader
before cron starts. Do not paste resolved environment values into tickets,
commits, or pull requests.
