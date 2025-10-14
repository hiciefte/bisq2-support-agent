# Maintenance Mode

This directory contains the static HTML maintenance page used during backend service updates.

## Current Implementation

The system uses **nginx automatic failover** for zero-downtime maintenance mode:

- **Nginx stays running** during backend deployments
- **Automatic failover** when backend containers (api, web, bisq2-api) return 502/503/504 errors
- **Zero configuration** needed - works out of the box
- **Professional UX** - users see maintenance page instead of connection errors

## How It Works

1. **Backend Update Detected**: `update.sh` pulls new code and detects changes
2. **Selective Rebuild**: Only backend containers are stopped and rebuilt
3. **Nginx Automatic Failover**: When backends are unavailable, nginx serves `maintenance.html`
4. **Service Restoration**: Backends come back online, nginx automatically resumes normal operation
5. **User Experience**: Seamless transition - maintenance page auto-refreshes every 10 seconds

## Files

- **maintenance.html** - Self-contained static HTML page with funny rotating messages
- **README.md** - This file

## Nginx Configuration

The maintenance system is configured in nginx automatically:

```nginx
# In location / block - triggers maintenance on backend errors
error_page 502 503 504 = @maintenance;

# Named location for maintenance page
location @maintenance {
    root /usr/share/nginx/html;
    rewrite ^ /maintenance.html break;
    internal;
}

# Serve maintenance page file with cache-busting headers
location = /maintenance.html {
    root /usr/share/nginx/html;
    internal;
    add_header Cache-Control "no-cache, no-store, must-revalidate";
    add_header Pragma "no-cache";
    add_header Expires "0";
}
```

## Deployment Integration

The `update.sh` script automatically leverages maintenance mode:

```bash
# 1. Detect changes needing rebuild
if [ "$REBUILD_NEEDED" = "true" ]; then
    # 2. Stop only backend containers (nginx stays running)
    docker compose stop api web bisq2-api

    # 3. Nginx automatically shows maintenance page to visitors

    # 4. Rebuild and restart backend
    docker compose up -d --build api web bisq2-api

    # 5. Wait for health checks
    sleep 30

    # 6. Nginx automatically resumes normal operation
fi
```

**Key Benefits:**
- No manual intervention required
- Zero downtime for user-facing interface
- Works for both clearnet and Tor (.onion) access
- Professional maintenance page with auto-refresh

## Maintenance Page Features

- **Self-contained** - No external dependencies, works offline
- **Dark theme** - Matches chatbot interface (green accent color)
- **Funny messages** - Rotates through 20 funny maintenance messages every 8 seconds
- **Auto-refresh** - Page refreshes every 10 seconds to automatically detect when service is back
- **Responsive** - Works on mobile and desktop
- **Animated** - Loading spinner and smooth message transitions
- **Professional** - User-friendly experience instead of connection errors

## Technical Architecture

### Volume Mount
```yaml
# docker-compose.yml
volumes:
  - ./docker/maintenance/maintenance.html:/usr/share/nginx/html/maintenance.html:ro
```

### Error Handling Flow
1. **Normal Operation**: Backend healthy → nginx proxies requests to backend
2. **Backend Unavailable**: Backend returns 502/503/504 → nginx intercepts error
3. **Maintenance Mode**: nginx serves `/maintenance.html` from volume mount
4. **Service Restored**: Backend healthy again → nginx resumes normal proxying

### Selective Rebuild Strategy
- **Stays Running**: nginx, prometheus, grafana, node-exporter, scheduler
- **Gets Rebuilt**: api, web, bisq2-api (only when changes detected)
- **Zero Downtime**: Users always see either working app or maintenance page

## System Requirements

**Nginx Configuration Files:**
- `docker/nginx/conf.d/default.conf` - Local development config
- `docker/nginx/conf.d/default.prod.conf` - Production config with security headers

Both configs include the same maintenance mode error handling.

**Docker Compose:**
- Maintenance HTML file must be mounted into nginx container at `/usr/share/nginx/html/maintenance.html`
- Mount is read-only (`:ro`) for security

**Update Script:**
- `scripts/update.sh` implements selective rebuild logic
- `scripts/lib/docker-utils.sh` contains `rebuild_services()` function
- Nginx config changes trigger nginx restart via `needs_nginx_restart()` in `git-utils.sh`

## Production Benefits

✅ **Zero Configuration**: Works automatically after deployment
✅ **Zero Downtime**: User-facing interface always available
✅ **HTTPS Support**: Maintenance page served through existing SSL termination
✅ **Tor Support**: Works seamlessly with .onion hidden service
✅ **Professional UX**: Users see friendly maintenance page, not errors
✅ **Auto-Recovery**: Service automatically resumes when backends are healthy
✅ **Selective Updates**: Only changed containers are rebuilt
✅ **Build Cache Preserved**: Standard cleanup preserves Docker build cache

## Testing Locally

### Test Automatic Maintenance Mode

```bash
# Start local environment
./run-local.sh

# Stop only backend containers to trigger maintenance mode
docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml stop api web

# Visit http://localhost - should show maintenance page

# Restart backends
docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml start api web

# Refresh browser - should automatically return to normal operation
```

### Test Maintenance Page Standalone

```bash
# Open the HTML file directly in browser
open docker/maintenance/maintenance.html

# Or serve with Python for testing
cd docker/maintenance
python3 -m http.server 8080
# Visit http://localhost:8080/maintenance.html
```

## Security Considerations

- **Read-Only Mount** - Maintenance HTML is mounted read-only for security
- **Internal Directive** - Nginx `internal;` directive prevents direct access
- **Minimal Attack Surface** - Only served during backend unavailability
- **No User Input** - Pure static content, no form processing
- **Cache-Busting Headers** - Prevents stale page caching
- **Auto-Refresh** - Page refreshes automatically, reducing stale connections
- **Temporary** - Only active during deployments (minutes, not hours)

## Monitoring

**Check maintenance mode status:**

```bash
# Check if backends are available
docker compose ps api web bisq2-api

# Check nginx logs for maintenance page serving
docker compose logs nginx | grep maintenance

# Monitor in real-time
docker compose logs -f nginx
```

**Health check endpoints remain available** during maintenance (internal only):
- `/health` - Nginx health (always available)
- `/api/health` - API health (via proxy when backend is up)
