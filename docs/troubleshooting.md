# Troubleshooting Guide

This document provides solutions for common issues you might encounter with the Bisq 2 Support Agent.

## API Service Issues

### Qdrant Index Initialization Errors

If the API starts but retrieval fails, you may see errors about missing Qdrant collections or index readiness.

Typical symptoms:

```
Qdrant retriever health check failed
```

or

```
Collection <name> not found
```

To fix:

1. Ensure Qdrant is running:
   ```bash
   docker compose -f docker/docker-compose.yml ps qdrant
   ```

2. Rebuild the Qdrant index from current wiki/FAQ sources:
   ```bash
   docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml exec api \
     python -m app.scripts.rebuild_qdrant_index --force
   ```

3. Restart API and re-check health:
   ```bash
   docker compose -f docker/docker-compose.yml restart api
   curl http://localhost:8000/health
   ```

## Bisq API Connection Issues

### Cannot Connect to Bisq API

If the FAQ extractor can't connect to the Bisq API, you might see errors like:

```
Failed to export chat messages: Cannot connect to host host.docker.internal:8090 ssl:default [Name or service not known]
```

This can be fixed by updating the Bisq API URL in the appropriate environment file:

For local API development (`api/.env`):
   ```
   # For local development:
   BISQ_API_URL=http://localhost:8090
   ```

### Bisq API Not Listening on Expected Port

If the Bisq API is running but not listening on the expected port:

1. Check the actual port:
   ```bash
   ss -tuln | grep java
   ```

2. Update the environment file with the correct port:
   ```
   # For local API development in api/.env:
   BISQ_API_URL=http://localhost:<actual-port>
   ```

### Environment File Issues

If you see errors related to missing environment variables:

1. Ensure your environment files exist in the correct locations:
   ```bash
   # For Docker:
   ls -la /path/to/bisq2-support-agent/docker/.env

   # For API:
   ls -la /path/to/bisq2-support-agent/api/.env
   ```

2. If they don't exist, create them from the example files:
   ```bash
   # For Docker:
   cp /path/to/bisq2-support-agent/docker/.env.example /path/to/bisq2-support-agent/docker/.env

   # For API:
   cp /path/to/bisq2-support-agent/api/.env.example /path/to/bisq2-support-agent/api/.env
   ```

3. Edit the files to set the required values:
   ```bash
   # For Docker:
   nano /path/to/bisq2-support-agent/docker/.env

   # For API:
   nano /path/to/bisq2-support-agent/api/.env
   ```

### CORS Issues

If you encounter CORS errors when the web frontend communicates with the API:

1. Check that the `CORS_ORIGINS` setting in your environment files includes all the appropriate origins:
   ```
   # In docker/.env or api/.env:
   CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
   ```

2. Note that `CORS_ORIGINS` now accepts a comma-separated list of origins instead of the previous space-separated format.

3. Restart the API service after making changes:
   ```bash
   docker compose -f docker/docker-compose.yml restart api
   ```

## Web UI Issues

### API Connection Timeout

If the web UI shows a timeout when connecting to the API:

1. Check if the API is running:
   ```bash
   docker compose -f docker/docker-compose.yml ps
   ```

2. Verify the API URL in the web UI environment:
   ```bash
   # Check in the docker-compose.yml file
   grep -A 5 "web:" docker/docker-compose.yml
   ```

3. Test the API directly:
   ```bash
   curl http://localhost:8000/health
   ```

4. Check if the environment setting is correct:
   ```bash
   # For production in docker/.env:
   NEXT_PUBLIC_API_URL=/api

   # For local development in docker-compose.local.yml:
   NEXT_PUBLIC_API_URL=http://localhost:8000
   ```

## FAQ Extractor Issues

### Connection Errors During Startup

If you see connection errors in FAQ extraction logs during container startup, this is **expected behavior** and not a problem:

**Typical Error:**
```text
Failed to export chat messages: Cannot connect to host bisq2-api:8090
```

**Explanation:**
- The bisq2-api service takes 30-60 seconds to fully initialize (Tor network + P2P connections)
- FAQ extraction may start before bisq2-api is ready
- The system has built-in retry logic that automatically succeeds once bisq2-api is ready
- No data is lost during this process

**When to Be Concerned:**
- If connection errors persist for more than 2 minutes after startup
- If the final FAQ extraction result shows failures

**Verification:**
```bash
# Test API connectivity from host machine
curl http://localhost:8090/api/v1/support/export

# Or test from within the API container (using Docker network hostname)
docker compose -f docker/docker-compose.yml exec api curl http://bisq2-api:8090/api/v1/support/export

# Run FAQ extraction manually to see final result
docker compose -f docker/docker-compose.yml exec api python -m app.scripts.extract_faqs
```

### No New FAQs Generated

If the FAQ extractor runs but doesn't generate new FAQs:

1. Check if there are new support conversations in the Bisq API:
   ```bash
   curl -sS http://localhost:8090/api/v1/support/export | jq '.exportMetadata.messageCount'
   ```

2. Check the FAQ extractor logs:
   ```bash
   docker compose -f docker/docker-compose.yml logs scheduler
   ```

3. Verify the OpenAI API key is valid:
   ```bash
   # Check the key in the Docker environment file
   grep OPENAI_API_KEY docker/.env
   ```

4. Ensure BISQ_API_URL is correctly set:
   ```bash
   # Dockerized Bisq API: http://bisq2-api:8090
   # Host-run Bisq API (GUI/headless started manually): http://host.docker.internal:8090
   # Note: host-run Bisq API must bind to 0.0.0.0 to be reachable from Docker.
   grep BISQ_API_URL docker/.env
   ```

5. If Bisq2 API has `authorizationRequired=true`, ensure support-agent auth is configured:
   ```bash
   grep -E '^(BISQ_API_AUTH_ENABLED|BISQ_API_PAIRING_QR_FILE|BISQ_API_PAIRING_CODE_ID|BISQ_API_AUTH_STATE_FILE|BISQ_API_PAIRING_CLIENT_NAME)=' docker/.env
   ```
   - Recommended flow is pairing bootstrap via QR file:
     1. Set `BISQ_API_AUTH_ENABLED=true` and `BISQ_API_PAIRING_QR_FILE=pairing_qr_code.txt`.
     2. Copy current QR payload from Bisq2 API runtime data into API data volume:
        ```bash
        docker compose -f docker/docker-compose.yml exec bisq2-api cat /opt/bisq2/data/pairing_qr_code.txt > api/data/pairing_qr_code.txt
        ```
     3. Restart `api` container and confirm `/data/bisq_api_auth.json` is created.
   - Pairing did not complete when logs show `Missing clientId` (missing/invalid QR file or auth disabled in support-agent).
   - Bisq2-side permission mapping for support endpoints is missing/incomplete for authenticated clients when logs show `Required permissions not granted` for `/api/v1/support/*`.
   - When Docker healthcheck for `bisq2-api` uses an authenticated endpoint and returns `403`, use a non-`-f` curl healthcheck so auth-mode `403` still counts as liveness.

## Monitoring Issues

### Prometheus Can't Scrape Metrics

If Prometheus can't scrape metrics from the API or web service:

1. Check if the metrics endpoints are accessible:
   ```bash
   curl http://localhost:8000/metrics
   curl http://localhost:3000/api/metrics
   ```

2. Verify the Prometheus configuration:
   ```bash
   cat docker/prometheus/prometheus.yml
   ```

3. Restart Prometheus:
   ```bash
   docker compose -f docker/docker-compose.yml restart prometheus
   ```

4. Check if the ADMIN_API_KEY is set in the Docker environment:
   ```bash
   grep ADMIN_API_KEY docker/.env
   ```

## Module Resolution Issues

If you encounter errors related to missing modules or dependencies:

1. For web frontend issues, check the Docker configuration:
   ```bash
   # For local development with hot reloading, use:
   ./run-local.sh
   ```

2. The web frontend uses two different Dockerfiles:
   - `docker/web/Dockerfile` for production (with two-stage build)
   - `docker/web/Dockerfile.dev` for development (with volume mounts for hot reloading)

## MediaWiki XML Namespace Conflicts

If you encounter warnings like these when processing the MediaWiki XML dump:

```
WARNING:mwxml.iteration.page:Namespace id conflict detected. <title>=File:Example.png, <namespace>=0, mapped_namespace=6
WARNING:mwxml.iteration.page:Namespace id conflict detected. <title>=Category:Example, <namespace>=0, mapped_namespace=14
```

These occur because some pages have titles with namespace prefixes (like 'File:' or 'Category:') but are incorrectly tagged with namespace ID 0 in the XML dump.

**Note**: The latest version of the `download_bisq2_media_wiki.py` script already handles namespaces correctly. This fix is only needed for existing XML files created with older versions of the download script.

To fix these conflicts:

1. Run the namespace fix script:
   ```bash
   python3 scripts/fix_xml_namespaces.py
   ```

2. The script will:
   - Update pages with 'File:' prefixes to namespace 6
   - Update pages with 'Category:' prefixes to namespace 14
   - Create a backup of the original file before making changes

3. Restart the API service:
   ```bash
   docker compose -f docker/docker-compose.yml restart api
   ```

## File Permission Issues

**Problem**: FAQ operations fail with permission errors.

**Symptoms**:
```
ERROR:app.services.faq_service:Failed to write to database: [Errno 13] Permission denied: '/data/faqs.db'
```

**Root Cause**: Data files owned by incorrect UID/GID (not matching container user UID 1001).

**Solution**:
```bash
# On production server
sudo find /opt/bisq-support/api/data -type f -exec chown 1001:1001 {} \;

# Verify fix
sudo docker exec docker-api-1 ls -la /data/faqs.db
# Should show: bisq-support bisq-support (UID/GID 1001)
```

**Prevention**: The `deploy.sh` and `update.sh` scripts now automatically fix file permissions during deployment/updates.

**Technical Details**:
- Container runs as UID 1001 (bisq-support)
- Files created by host processes may use different UIDs (e.g., 1000)
- Docker bind mount preserves host file ownership
- Container user needs write permissions to modify files

## Tor Hidden Service Not Accessible

**Problem**: The .onion site is not accessible via Tor Browser.

**Symptoms**:
- Tor Browser shows "Unable to connect" or times out
- Repeated "Giving up on launching a rendezvous circuit" errors in Tor logs
- Local HTTP access works (curl http://127.0.0.1:80 returns 200)

**Diagnosis Steps**:
```bash
# 1. Check if Tor service is running
systemctl status tor@default

# 2. Check Tor logs for circuit errors
journalctl -u tor@default --since "1 hour ago" | grep -iE "(error|warn|fail|circuit|rendezvous)"

# 3. Verify hidden service configuration
cat /etc/tor/torrc | grep -v "^#" | grep -v "^$"
# Should show:
# HiddenServiceDir /var/lib/tor/bisq-support/
# HiddenServicePort 80 127.0.0.1:80

# 4. Verify .onion hostname exists
cat /var/lib/tor/bisq-support/hostname

# 5. Test local HTTP access (should return 200)
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:80/
```

**Root Cause**: Tor hidden services can develop stale circuit state after running for extended periods, causing rendezvous circuit failures.

**Solution**:
```bash
# Restart Tor service to re-establish fresh circuits
systemctl restart tor@default

# Wait for bootstrap to complete (watch for "Bootstrapped 100%")
journalctl -u tor@default -f

# Test .onion access through Tor SOCKS proxy
curl --socks5-hostname 127.0.0.1:9050 -s -o /dev/null -w "%{http_code}" --max-time 30 http://<your-onion-address>.onion/
```

**Verification**:
```bash
# Check Tor bootstrap status (should show 100%)
journalctl -u tor@default --since "5 minutes ago" | grep "Bootstrapped"

# Test .onion accessibility (should return 200)
curl --socks5-hostname 127.0.0.1:9050 -s -o /dev/null -w "%{http_code}" --max-time 30 http://<your-onion-address>.onion/
```

**Technical Details**:
- Tor runs as a systemd service (`tor@default.service`)
- Hidden service keys are stored in `/var/lib/tor/bisq-support/`
- Tor proxies requests to nginx on `127.0.0.1:80`
- Introduction point descriptors may take 1-2 minutes to propagate after restart
- The "Giving up on launching a rendezvous circuit" error indicates Tor cannot establish the final hop to connect clients to the hidden service

**Prevention**: Consider adding a weekly Tor service restart to the scheduler cron if this issue recurs frequently.

## Getting Help

If you're still experiencing issues:

1. Check the logs:
   ```bash
   docker compose -f docker/docker-compose.yml logs api
   docker compose -f docker/docker-compose.yml logs web
   ```

2. Ensure all environment files are properly configured:
   ```bash
   # Check Docker environment
   cat docker/.env

   # Check API environment (for local development)
   cat api/.env
   ```
