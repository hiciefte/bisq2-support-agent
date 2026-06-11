# Bisq2 API Startup and Pairing Runbook

Use this runbook when the support-agent must connect to a Bisq2 API client for real Bisq2 network data, or when production Bisq2 API pairing has to survive container updates and restarts.

## Local Production-Network Client

Use this flow for local end-to-end testing against the regular Bisq2 production network. Do not use the local 3-node harness for this case. The local 3-node scripts intentionally use a local CLEAR network and will not receive real-world chats or offer-book data.

### Start One Headless Bisq2 API Client

From the support-agent repo, start the Bisq2 API app from the Bisq2 Java workspace:

```bash
BISQ2_DIR=/Users/takahiro/Documents/Workspaces/Java/bisq2
BISQ2_RUNTIME=/tmp/bisq2-prod-api

mkdir -p "$BISQ2_RUNTIME/data" "$BISQ2_RUNTIME/logs"
: > "$BISQ2_RUNTIME/logs/api.log"

screen -S bisq2-prod-api -X quit >/dev/null 2>&1 || true
screen -dmS bisq2-prod-api -t api sh -lc "
  cd '$BISQ2_DIR' &&
  env JAVA_OPTS='-Dapplication.api.server.restEnabled=true -Dapplication.api.server.websocketEnabled=true -Dapplication.api.server.bind.host=127.0.0.1 -Dapplication.api.server.bind.port=8090' \
    apps/api-app/build/install/api-app/bin/api-app \
      --app-name=bisq2_api_prod \
      --data-dir=$BISQ2_RUNTIME/data \
      >> $BISQ2_RUNTIME/logs/api.log 2>&1
"
```

Why this command:

- It starts exactly one Bisq2 client.
- It uses the normal Bisq2 production TOR network defaults.
- It exposes only the local API on `127.0.0.1:8090`.
- It keeps runtime data outside the repo under `/tmp/bisq2-prod-api`.

On macOS Docker Desktop, the support-agent container can reach a host service bound to `127.0.0.1` through `host.docker.internal`. On native Linux Docker, a host-run Bisq2 API may need to bind to `0.0.0.0` to be reachable from containers; if you do that, keep it firewalled to the host/Docker bridge.

### Verify Bisq2 Startup

```bash
screen -ls
tail -n 120 /tmp/bisq2-prod-api/logs/api.log
pgrep -fl 'bisq\.api_app\.ApiApp.*--app-name=bisq2_api_prod|bisq2_api_prod'
```

Healthy signs:

- Tor bootstraps to 100%.
- REST/WebSocket starts on port `8090`.
- Logs show production network inventory, offers, and public chat messages.

Stop the local headless client with:

```bash
screen -S bisq2-prod-api -X quit
```

### Pair Support-Agent Locally

The Bisq2 API writes a QR pairing payload after startup. Copy it into the support-agent API data directory, which is mounted into the API container as `/data`:

```bash
cp /tmp/bisq2-prod-api/data/pairing_qr_code.txt api/data/pairing_qr_code.txt
chmod 600 api/data/pairing_qr_code.txt
```

If `docker/.env` contains stale explicit auth values from an older Bisq2 client, blank them before restarting the API container. Explicit env credentials take precedence over the pairing/auth-state file.

```bash
cp docker/.env "/tmp/bisq-support-docker.env.$(date +%Y%m%d%H%M%S)"

python3 - <<'PY'
from pathlib import Path

path = Path("docker/.env")
blank = {
    "BISQ_API_CLIENT_ID",
    "BISQ_API_CLIENT_SECRET",
    "BISQ_API_SESSION_ID",
    "BISQ_API_PAIRING_CODE_ID",
}

lines = []
for line in path.read_text().splitlines():
    key = line.split("=", 1)[0].strip()
    if key in blank:
        lines.append(f"{key}=")
    else:
        lines.append(line)
path.write_text("\n".join(lines) + "\n")
PY
```

Start or recreate the local support-agent API:

```bash
./run-local.sh

docker compose --env-file docker/.env \
  -f docker/docker-compose.yml \
  -f docker/docker-compose.local.yml \
  up -d --force-recreate api
```

Expected log markers:

```text
Loaded Bisq pairing code ID from QR file
Paired Bisq API client successfully
Loaded Bisq API auth state from /data/bisq_api_auth.json
Bisq startup self-test completed with status=healthy
Connected to Bisq2 WebSocket at ws://host.docker.internal:8090/websocket
```

Verify from the support-agent side:

```bash
curl -sS http://localhost:8000/health | jq '.services.bisq2_api'
ls -l api/data/bisq_api_auth.json api/data/pairing_qr_code.txt
```

The file `api/data/bisq_api_auth.json` is a local secret/runtime artifact. Do not commit it.

## Production Pairing and Restart Semantics

Production uses two persistent stores:

- API data: `/opt/bisq-support/api/data` bind-mounted into `api` as `/data`.
- Bisq2 data: Docker named volume `bisq2-data` mounted into `bisq2-api` as `/opt/bisq2/data`.

The deploy/update scripts preserve both stores:

- `scripts/update.sh` rebuilds/recreates containers with `docker compose stop`, `docker compose up -d`, or `docker compose down` without `-v`.
- `scripts/deploy.sh` runs `docker compose build` and `docker compose up -d`.
- Data is lost only if an operator deletes `/opt/bisq-support/api/data`, runs `docker compose down -v`, removes `bisq2-data`, or prunes volumes while they are unattached.

### Config Files

Production config separation is:

- `/etc/bisq-support/deploy.env`: deploy-path variables only.
- `/opt/bisq-support/docker/.env`: all app config, secrets, room IDs, and feature flags.

Do not put Bisq API auth variables in `deploy.env`; scripts intentionally ignore app config there.

### Required Production Auth Settings

If the Bisq2 API server has `application.api.server.security.authorizationRequired=true`, set these in `/opt/bisq-support/docker/.env`:

```bash
BISQ_API_URL=http://bisq2-api:8090
BISQ_API_AUTH_ENABLED=true
BISQ_API_AUTH_STATE_FILE=bisq_api_auth.json
BISQ_API_AUTH_STATE_SECRET=<stable random secret>
```

Recommended steady state after first successful pairing:

```bash
BISQ_API_CLIENT_ID=<durable client id>
BISQ_API_CLIENT_SECRET=<durable client secret>
BISQ_API_SESSION_ID=
BISQ_API_PAIRING_CODE_ID=
BISQ_API_PAIRING_QR_FILE=
```

Alternative steady state:

- Leave `BISQ_API_CLIENT_ID` and `BISQ_API_CLIENT_SECRET` blank.
- Keep `/data/bisq_api_auth.json` as the credential source.
- Keep `BISQ_API_AUTH_STATE_SECRET` unchanged across restarts and deployments.

This is restart-safe as long as `/opt/bisq-support/api/data/bisq_api_auth.json` persists and the encryption secret does not change.

Do not set `BISQ_API_SESSION_ID` in production. Sessions are runtime state; the support-agent can create a fresh session from the client secret.

### Auth Loading Order

The support-agent Bisq client uses this order:

1. Explicit `BISQ_API_CLIENT_ID`, `BISQ_API_CLIENT_SECRET`, and optional `BISQ_API_SESSION_ID` from `docker/.env`.
2. Encrypted auth state from `/data/$BISQ_API_AUTH_STATE_FILE` if no client ID is set.
3. Pairing QR/code only when credentials are missing or session recovery fails.

This means stale explicit env credentials can block a fresh QR pairing attempt. Blank stale env values before re-pairing.

### First Bootstrap or Re-Pairing

Only use the QR/code as a bootstrap mechanism. Do not rely on an old QR file as a long-term recovery path.

```bash
cd /opt/bisq-support/docker

docker compose -f docker-compose.yml exec bisq2-api \
  cat /opt/bisq2/data/pairing_qr_code.txt \
  > /opt/bisq-support/api/data/pairing_qr_code.txt

chmod 600 /opt/bisq-support/api/data/pairing_qr_code.txt
chown 1001:1001 /opt/bisq-support/api/data/pairing_qr_code.txt
```

Then make sure stale explicit values are blank in `/opt/bisq-support/docker/.env`:

```bash
BISQ_API_CLIENT_ID=
BISQ_API_CLIENT_SECRET=
BISQ_API_SESSION_ID=
BISQ_API_PAIRING_CODE_ID=
BISQ_API_PAIRING_QR_FILE=pairing_qr_code.txt
```

Restart only the support-agent API container:

```bash
cd /opt/bisq-support/docker
docker compose -f docker-compose.yml up -d --force-recreate api
docker compose -f docker-compose.yml logs --tail=200 api | grep -Ei 'Bisq|pair|auth|session'
```

After successful pairing, either move the durable client credentials into `/opt/bisq-support/docker/.env` or keep the encrypted auth-state file as the source of truth. In either case, blank `BISQ_API_PAIRING_QR_FILE` for steady-state production unless you intentionally want pairing fallback during the next restart.

### Read-Only Production Check

Use this check before production updates when Bisq2 pairing is in scope. It prints only key presence/lengths and file metadata, not secret values.

```bash
ssh root@143.110.227.171 'bash -s' <<'REMOTE'
set -eu
cd /opt/bisq-support/docker

python3 - <<'PY'
from pathlib import Path

keys = [
    "BISQ_API_URL",
    "BISQ_API_AUTH_ENABLED",
    "BISQ_API_CLIENT_ID",
    "BISQ_API_CLIENT_SECRET",
    "BISQ_API_SESSION_ID",
    "BISQ_API_PAIRING_CODE_ID",
    "BISQ_API_PAIRING_QR_FILE",
    "BISQ_API_AUTH_STATE_FILE",
    "BISQ_API_AUTH_STATE_SECRET",
]

for path in [Path("/etc/bisq-support/deploy.env"), Path("/opt/bisq-support/docker/.env")]:
    values = {}
    if path.exists():
        for raw in path.read_text(errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            if "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("'\"")
    print(f"file={path} exists={path.exists()}")
    for key in keys:
        value = values.get(key, "")
        if key in {"BISQ_API_URL", "BISQ_API_AUTH_ENABLED", "BISQ_API_PAIRING_QR_FILE", "BISQ_API_AUTH_STATE_FILE"}:
            print(f"{path.name}:{key}={value or 'unset'}")
        else:
            print(f"{path.name}:{key}={'SET(len=' + str(len(value)) + ')' if value else 'unset'}")
PY

docker compose -f docker-compose.yml ps api bisq2-api
docker inspect docker-api-1 --format '{{range .Mounts}}{{println .Type .Source .Destination}}{{end}}'
docker inspect docker-bisq2-api-1 --format '{{range .Mounts}}{{println .Type .Name .Source .Destination}}{{end}}'
docker exec docker-api-1 sh -lc 'for f in /data/bisq_api_auth.json /data/pairing_qr_code.txt; do if [ -e "$f" ]; then ls -l "$f"; else echo missing "$f"; fi; done'
docker exec docker-bisq2-api-1 sh -lc 'grep -n "authorizationRequired\|supportSessionHandling\|host =\|port =" /opt/bisq2/data/bisq.conf 2>/dev/null || true'
docker exec docker-api-1 sh -lc 'curl -fsS --max-time 5 http://localhost:8000/health'
REMOTE
```

### Production Failure Modes

Use these signatures to avoid unnecessary re-pairing:

- `bisq2-api` healthcheck times out on `/api/v1/openapi.json`: target API is not responsive. Pairing is not the primary issue.
- `authorizationRequired=false` in `/opt/bisq2/data/bisq.conf`: Bisq2 API is not enforcing auth. Support-agent auth headers may be configured but pairing is not being exercised.
- `Missing clientId`, `401`, or `403` in support-agent logs: check `BISQ_API_AUTH_ENABLED`, client credentials, session creation, and permission mapping.
- `Failed to decrypt Bisq API auth state`: `BISQ_API_AUTH_STATE_SECRET` changed or the auth-state file is from another environment.
- `Ignoring incomplete Bisq API auth state`: auth-state file lacks `client_secret`; re-pair or restore a valid state file.
