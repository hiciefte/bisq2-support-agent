# Deployment Issues Analysis - October 14, 2025

## Summary
Deployment of PR #79 failed during automated update, triggering automatic rollback. Root cause identified and system restored to operational state.

## Issues Identified

### 1. **502 Bad Gateway Instead of Maintenance Page**

**Issue**: During deployment, users saw "502 Bad Gateway nginx/1.29.1" instead of the maintenance page.

**Root Cause - Multi-Layered Issue**:

**Layer 1: Nginx Health Check Failure**
- Nginx health check: `curl -f http://localhost:80` (hits `/` location)
- During deployment: `web` container is stopped/unhealthy
- Nginx proxy to `web:3000` fails → should trigger maintenance page
- **BUT** nginx was in unhealthy state, so health check returned 502 directly

**Layer 2: Grafana DNS Resolution Problem**
- Nginx configuration has `proxy_pass http://grafana:3000/` at line 155 (for `/grafana/` location)
- During nginx configuration load, it tries to resolve ALL upstreams, including `grafana`
- **Key Discovery**: Monitoring services (grafana, prometheus) were **RUNNING** during deployment
- **BUT** Docker DNS resolution can be slow/flaky during network reconfiguration
- If DNS resolution for `grafana` times out or fails → nginx can't reload config properly
- Failed config reload → nginx stays unhealthy → health check fails → 502 error

**Layer 3: Maintenance Page Scope**
- `error_page 502 503 504 = @maintenance` is **ONLY** defined in `location /` block
- Does NOT apply to:
  - `/api/*` locations
  - `/grafana/*` location
  - Nginx's own health check failures
- When nginx is unhealthy due to config issues, it returns 502 **before** any location matching happens

**Evidence from Logs**:
```
# From docker_ps.txt during deployment:
docker-nginx-1  Up 4 days (unhealthy)

# From nginx logs after rollback:
nginx: [emerg] host not found in upstream "grafana" in /etc/nginx/conf.d/default.conf:155
```

**Why This Happened During Update (Not Just Rollback)**:
1. `update.sh` stops and rebuilds `api`, `web`, `bisq2-api` containers
2. Docker recreates network bridges during container restart
3. DNS resolution can be temporarily unstable during network reconfiguration
4. Nginx tries to reload config → DNS lookup for `grafana` times out
5. Config reload fails → nginx becomes unhealthy → 502 errors

**Fix Applied**:
```bash
# After rollback, monitoring services were missing
docker compose up -d prometheus grafana node-exporter scheduler

# Restarted nginx after grafana was resolvable
docker compose restart nginx
```

### 2. **Deployment Script Failed - Container Health Check Timing**

**Issue**: Update script reported "dependency failed to start: container docker-api-1 is unhealthy" then later showed containers as healthy, causing confusion and rollback.

**Root Cause Analysis**:

```
# From deployment logs:
Container docker-api-1  Started
Container docker-api-1  Waiting
Container docker-api-1  Error
dependency failed to start: container docker-api-1 is unhealthy

# But moments later:
Container docker-api-1  Running
Container docker-api-1  Healthy
Container docker-web-1  Healthy
```

**Timing Issue**:
1. Containers started successfully
2. Health check was performed TOO EARLY (before services fully initialized)
3. Initial health check failed → Docker reported "dependency failed"
4. Services actually became healthy 30-60 seconds later
5. Update script didn't wait long enough for health stabilization

**Current Health Check Wait Time**: 30 seconds in `update.sh`
**Actual Time Needed**: 60-90 seconds for full service initialization

### 3. **Monitoring Service Dependencies**

**Issue**: Nginx depends on grafana service being resolvable, but monitoring services weren't part of rebuild/restart logic.

**Current Behavior**:
- `update.sh` rebuilds only changed services (api, web, bisq2-api)
- Monitoring stack (prometheus, grafana, node-exporter, scheduler) is excluded
- During rollback, ALL containers stopped, but monitoring services weren't restarted

**Result**: Nginx crash loop due to missing grafana upstream

## Recommendations

### 1. **Increase Health Check Wait Time**

**File**: `/opt/bisq-support/scripts/lib/docker-utils.sh`
**Function**: `wait_for_healthy_services()`

**Current**:
```bash
HEALTH_CHECK_WAIT=30  # seconds
```

**Recommended**:
```bash
HEALTH_CHECK_WAIT=90  # seconds to allow full service initialization
```

**Rationale**:
- API container needs 30-45 seconds to initialize FastAPI app
- ChromaDB vector store loading adds 15-30 seconds
- Total: 60-90 seconds for guaranteed healthy state

### 2. **Fix Monitoring Service Management in Rollback**

**File**: `/opt/bisq-support/scripts/update.sh`
**Function**: Rollback logic

**Issue**: Monitoring services stopped during rollback but not restarted

**Recommended Fix**:
```bash
# In rollback function, after rebuilding:
info "Restarting all services including monitoring..."
docker compose up -d --force-recreate

# Or explicitly restart monitoring:
docker compose up -d prometheus grafana node-exporter scheduler
sleep 10  # Wait for grafana to be resolvable
docker compose restart nginx
```

### 3. **Make Nginx Resilient to DNS Resolution Issues**

**File**: `docker/nginx/conf.d/default.prod.conf`
**Location**: Line 155 (grafana upstream) + all proxy_pass directives

**Problem**: Nginx resolves ALL upstream hostnames at config load time. If ANY DNS lookup fails or times out, nginx can't reload configuration properly, causing it to become unhealthy.

**Solution - Use DNS Resolver with Variables** (RECOMMENDED):

Add at **server block level** (after `server_name _;`):
```nginx
server {
    listen 80;
    server_name _;

    # Use Docker's internal DNS with 10s validity
    # Prevents nginx from failing if upstream is temporarily unreachable
    resolver 127.0.0.11 valid=10s;
    resolver_timeout 5s;

    # ... rest of config
}
```

Then modify ALL `proxy_pass` directives to use variables:
```nginx
# BEFORE (hard-coded hostname, resolved at config load):
location /grafana/ {
    proxy_pass http://grafana:3000/;
}

# AFTER (variable, resolved at request time):
location /grafana/ {
    set $grafana_upstream grafana:3000;
    proxy_pass http://$grafana_upstream/;
}
```

**Apply to ALL locations**:
- `location / { proxy_pass http://web:3000; }` → Use `$web_upstream`
- `location /api/ { proxy_pass http://api:8000/api/; }` → Use `$api_upstream`
- `location /grafana/ { proxy_pass http://grafana:3000/; }` → Use `$grafana_upstream`
- All other proxy_pass directives

**Benefits**:
- ✅ DNS lookups happen at **request time**, not config load time
- ✅ Nginx can start even if some upstreams are temporarily unavailable
- ✅ Gracefully handles Docker network reconfiguration
- ✅ Maintenance page can be served for specific location 502 errors

**Alternative - Add Error Handling to All Locations**:
```nginx
# Add to EVERY location block that uses proxy_pass
location /grafana/ {
    error_page 502 503 504 = @maintenance;
    proxy_pass http://grafana:3000/;
    # ...
}
```

**Recommendation**: Use **DNS resolver + variables** (Option A) as it solves the root cause. Add error_page to all locations as defense-in-depth.

### 4. **Add Pre-Deployment Health Check**

**File**: `/opt/bisq-support/scripts/update.sh`
**Location**: Before rebuild

**Add**:
```bash
# Before rebuilding, verify monitoring services are running
check_monitoring_services() {
    local required_services="prometheus grafana node-exporter scheduler"
    for service in $required_services; do
        if ! docker compose ps "$service" | grep -q "Up"; then
            warning "$service is not running, starting it..."
            docker compose up -d "$service"
        fi
    done
}
```

## Deployment Timeline

| Time | Event | Status |
|------|-------|--------|
| 19:16:26 | Backup created | ✅ Success |
| 19:16:26 | Git pull completed | ✅ Success |
| 19:16:26 | Dependency changes detected | ⚠️ Rebuild triggered |
| 19:16:26 | Backend services stopped | ✅ Success |
| 19:16:26 | Container rebuild started | ✅ Success |
| 19:21:29 | Health check failed (too early) | ❌ Failed |
| 19:21:29 | Rollback initiated | ⚠️ Auto-rollback |
| 19:21:29 | Rolled back to previous commit | ✅ Success |
| 19:23:29 | Rollback verification failed | ❌ Monitoring services missing |
| 19:26:00 | Manual intervention: Started monitoring services | ✅ Fixed |
| 19:26:10 | Nginx restarted | ✅ Healthy |
| 19:26:20 | All services healthy | ✅ Success |

## Action Items

### Immediate (Required for Next Deployment)
- [ ] Increase `HEALTH_CHECK_WAIT` to 90 seconds in `docker-utils.sh`
- [ ] Fix rollback logic to restart monitoring services
- [ ] Test deployment with longer health check wait time

### Short-term (This Week)
- [ ] Implement nginx DNS resolver for grafana upstream
- [ ] Add pre-deployment monitoring service check
- [ ] Document manual recovery procedure in CLAUDE.md

### Long-term (Next Sprint)
- [ ] Add comprehensive service dependency graph to update script
- [ ] Implement progressive health checks (retry with backoff)
- [ ] Add deployment dry-run mode for testing

## Current System Status

✅ **All services healthy and operational**
- API: Healthy (running on a5af1fa - pre-PR#79)
- Web: Healthy
- Bisq2 API: Healthy
- Nginx: Healthy
- Prometheus: Running
- Grafana: Running
- Node Exporter: Running
- Scheduler: Running

⚠️ **PR #79 not deployed** - System rolled back to previous stable version

**Next Steps**: Apply recommended fixes above, then retry deployment with longer health check timeout.

## Root Cause Summary

**Primary Issue**: Health check timeout too short (30s vs actual 60-90s needed)

**Secondary Issue**: Monitoring services not restarted during rollback, causing nginx to fail due to missing grafana upstream

**Tertiary Issue**: Nginx configuration not resilient to missing upstream services during maintenance

**Impact**: Deployment failed and rolled back successfully, but users saw 502 errors instead of maintenance page during the window when monitoring services were down.

## Files Requiring Changes

1. `/opt/bisq-support/scripts/lib/docker-utils.sh` - Increase health check wait time
2. `/opt/bisq-support/scripts/update.sh` - Fix rollback monitoring service management
3. `/opt/bisq-support/docker/nginx/conf.d/default.prod.conf` - Add DNS resolver for resilience
4. `/opt/bisq-support/CLAUDE.md` - Document manual recovery procedure

## Testing Checklist for Next Deployment

- [ ] Verify HEALTH_CHECK_WAIT increased to 90 seconds
- [ ] Verify monitoring services restart during rollback
- [ ] Test nginx starts successfully even if grafana is temporarily down
- [ ] Verify maintenance page displays during backend restart
- [ ] Monitor deployment logs for "dependency failed" errors
- [ ] Confirm all services healthy within 90-second window
- [ ] Test rollback procedure includes monitoring services
