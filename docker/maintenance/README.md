# Maintenance Mode

This directory contains a static HTML maintenance page and scripts to serve it during system updates when all Docker containers are down.

## Problem

During Docker container rebuilds/redeployments, **all services including nginx are unavailable**. Users visiting the site will see connection errors instead of a user-friendly maintenance message.

## Solution

A **standalone static maintenance page** served by a simple Python HTTP server on the host system, completely independent of Docker. The deployment process should:

1. Start maintenance page server
2. Stop Docker containers
3. Rebuild and restart containers
4. Stop maintenance page server

## Files

- **maintenance.html** - Self-contained static HTML page matching chatbot aesthetic with funny messages
- **serve-maintenance.sh** - Script to start/stop the maintenance page server
- **README.md** - This file

## Usage

### Manual Control

```bash
# Start maintenance page (requires sudo for port 80)
sudo ./serve-maintenance.sh start

# Check status
sudo ./serve-maintenance.sh status

# Stop maintenance page
sudo ./serve-maintenance.sh stop
```

### Integration with Deployment Scripts

The deployment and update scripts should integrate maintenance mode:

```bash
# Example integration in deploy.sh or update.sh

# 1. Start maintenance page
log "Starting maintenance page..."
sudo /opt/bisq-support/docker/maintenance/serve-maintenance.sh start

# 2. Stop Docker services
log "Stopping Docker services..."
docker compose -f docker/docker-compose.yml down

# 3. Rebuild and restart
log "Rebuilding and restarting services..."
docker compose -f docker/docker-compose.yml up -d --build

# 4. Wait for health checks
log "Waiting for services to be healthy..."
sleep 30

# 5. Stop maintenance page
log "Stopping maintenance page..."
sudo /opt/bisq-support/docker/maintenance/serve-maintenance.sh stop

log "Deployment complete!"
```

## Technical Details

### Port Configuration

By default, the maintenance server uses **port 80**. To use a different port:

```bash
MAINTENANCE_PORT=8080 ./serve-maintenance.sh start
```

### Maintenance Page Features

- **Self-contained** - No external dependencies, works offline
- **Dark theme** - Matches chatbot interface aesthetic
- **Funny messages** - Rotates through 20 funny maintenance messages every 8 seconds
- **Auto-refresh** - Page refreshes every 10 seconds to detect when service is back
- **Responsive** - Works on mobile and desktop
- **Animated** - Loading spinner and smooth message transitions

### How It Works

1. **Python HTTP Server** - Uses Python 3's built-in `http.server` module (no dependencies)
2. **Temporary Directory** - Copies maintenance.html to a temp directory as index.html
3. **Background Process** - Runs server as a daemon with PID tracking
4. **Graceful Shutdown** - Cleanly stops server and cleans up PID files

### Limitations

- **Port 80 requires sudo** - If running on port 80, need root privileges
- **No HTTPS** - Serves HTTP only (nginx handles HTTPS in production)
- **Single file** - Can only serve the maintenance page, no other routes

## Production Deployment Considerations

### Option 1: Use Port 80 Directly (Requires sudo)

```bash
sudo ./serve-maintenance.sh start
```

**Pros**: Direct replacement for nginx on port 80
**Cons**: Requires root access, no HTTPS

### Option 2: Use High Port + Port Forwarding

```bash
# Start on port 8080 (no sudo needed)
MAINTENANCE_PORT=8080 ./serve-maintenance.sh start

# Forward port 80 to 8080 using iptables
sudo iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-port 8080
```

**Pros**: No root needed for web server
**Cons**: More complex setup, requires iptables rules

### Option 3: Nginx Maintenance Mode (Requires nginx running)

If nginx is still running and only backend containers are down, configure nginx to serve the static maintenance page:

```nginx
error_page 502 503 504 /maintenance.html;

location = /maintenance.html {
    root /opt/bisq-support/docker/maintenance;
    internal;
}
```

**Pros**: Uses existing nginx, supports HTTPS
**Cons**: Only works if nginx container is still running

## Testing Locally

```bash
# Start maintenance page on port 8080 (no sudo needed)
cd docker/maintenance
MAINTENANCE_PORT=8080 ./serve-maintenance.sh start

# Open browser to http://localhost:8080

# Stop when done
MAINTENANCE_PORT=8080 ./serve-maintenance.sh stop
```

## Security Considerations

- **Minimal Attack Surface** - Only serves a single static HTML file
- **No User Input** - Pure static content, no form processing
- **Auto-refresh** - Page refreshes automatically, reducing stale connections
- **Temporary** - Only runs during deployments (minutes, not hours)

## Future Improvements

1. **systemd Service** - Create a systemd unit for better process management
2. **Health Check Endpoint** - Add `/health` endpoint to detect when to auto-stop
3. **Custom Messages** - Support environment variables for custom maintenance messages
4. **Scheduled Maintenance** - Pre-announce scheduled maintenance windows
5. **Status API Integration** - Pull real-time status from monitoring systems
