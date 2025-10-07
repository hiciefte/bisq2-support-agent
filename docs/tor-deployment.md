# Tor Hidden Service Deployment Guide

This guide provides step-by-step instructions for deploying the Bisq Support Agent as a Tor hidden service (.onion address). This enables private, censorship-resistant access to the support assistant.

## Overview

The Tor integration is **completely optional**. The application will run normally without Tor configuration. When Tor is not configured:
- The application builds and runs successfully
- Tor verification endpoints return HTTP 503 "Service Unavailable"
- Metrics show `tor_hidden_service_configured=0`

## Architecture

This deployment uses **Host-Based Tor** for optimal security:

```
Internet (Tor Network)
         ↓
    Tor Daemon (Host)
    - Listens on Tor network
    - SOCKS proxy: 127.0.0.1:9050
    - Forwards HTTP to: 127.0.0.1:80
         ↓
    Nginx Container
    - Binds to: 127.0.0.1:80:80
    - Bridge network only (no host networking)
         ↓
    API/Web Containers
    - Internal Docker networking
    - No direct external access
```

**Security Boundaries**:
- Tor daemon runs on host (not in container)
- Nginx binds to localhost only - **already configured in production**
- Docker containers use bridge networking (secure isolation)

## Prerequisites

- Root access to the production server
- Tor daemon (will be installed in Step 1)
- Application already deployed using standard deployment process
- Access to `/opt/bisq-support/` directory

## Deployment Steps

### Step 1: Install Tor on Host System

```bash
# Update package repositories
sudo apt update

# Install Tor
sudo apt install -y tor

# Verify installation
tor --version
```

### Step 2: Configure Tor Hidden Service

Create the Tor configuration file with security hardening:

```bash
# Backup original config
sudo cp /etc/tor/torrc /etc/tor/torrc.backup

# Create new secure configuration
sudo tee /etc/tor/torrc > /dev/null <<'EOF'
## Bisq Support Agent - Tor Hidden Service Configuration
## Security Hardening Applied

###############################################################################
# GENERAL TOR SETTINGS
###############################################################################

# Run Tor as a specific user (never root)
User debian-tor

# Data directory with restricted permissions
DataDirectory /var/lib/tor

# Log to syslog for centralized logging
Log notice syslog

# Control port for monitoring (bind to localhost only)
ControlPort 9051
CookieAuthentication 1
CookieAuthFile /var/lib/tor/control_auth_cookie
CookieAuthFileGroupReadable 1

###############################################################################
# HIDDEN SERVICE CONFIGURATION
###############################################################################

# Primary Hidden Service for Web/API
HiddenServiceDir /var/lib/tor/bisq-support/
HiddenServicePort 80 127.0.0.1:80
HiddenServiceVersion 3
HiddenServiceDirGroupReadable 0

# Optional: Metrics Hidden Service (internal monitoring only)
# HiddenServiceDir /var/lib/tor/bisq-support-metrics/
# HiddenServicePort 9090 127.0.0.1:9090
# HiddenServiceVersion 3
# HiddenServiceDirGroupReadable 0

###############################################################################
# SECURITY & PERFORMANCE SETTINGS
###############################################################################

# Circuit Isolation - Prevent traffic correlation
IsolateDestAddr 1
IsolateDestPort 1

# Stream Isolation (different SOCKS ports for different purposes)
SocksPort 9050 IsolateDestAddr IsolateDestPort
SocksPort 9052 IsolateDestAddr IsolateDestPort  # For external API calls

# DoS Protection
MaxClientCircuitsPending 48
MaxCircuitDirtiness 600

# Connection Limits
ConnLimit 1000
MaxMemInQueues 8 GB

# Bandwidth Management (optional - remove limits if not needed)
# RelayBandwidthRate 1000 KB
# RelayBandwidthBurst 2000 KB

# Disable unused features for security
DisableNetwork 0
ExitRelay 0
ExitPolicy reject *:*

###############################################################################
# SYSTEMD INTEGRATION
###############################################################################

# Enable systemd notify support
Type notify
NotifyAccess main
EOF
```

### Step 3: Harden Tor Service with Systemd

Create systemd drop-in for additional security:

```bash
# Create systemd override directory
sudo mkdir -p /etc/systemd/system/tor.service.d/

# Create hardening configuration
sudo tee /etc/systemd/system/tor.service.d/hardening.conf > /dev/null <<'EOF'
[Service]
# Security Hardening
NoNewPrivileges=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/var/lib/tor
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
RestrictNamespaces=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
SystemCallFilter=@system-service
SystemCallErrorNumber=EPERM

# Resource Limits
LimitNOFILE=65536
TasksMax=4096
EOF

# Reload systemd
sudo systemctl daemon-reload
```

### Step 4: Start and Enable Tor Service

```bash
# Enable Tor to start on boot
sudo systemctl enable tor

# Start Tor service
sudo systemctl start tor

# Check status
sudo systemctl status tor

# Verify Tor is running
sudo ss -tlnp | grep tor
```

### Step 5: Get Your .onion Address

#### Option A: Use Random Address (Fastest)

```bash
# Primary web/API hidden service address
sudo cat /var/lib/tor/bisq-support/hostname

# Optional: Metrics hidden service address (if configured)
# sudo cat /var/lib/tor/bisq-support-metrics/hostname
```

#### Option B: Use Custom Vanity Address (Recommended)

For better branding, generate a custom .onion address locally (e.g., `bisq*.onion`):

📖 **See guide**: [Generate Custom Vanity .onion Address](generate-vanity-onion.md)

**Quick start**:
```bash
# On your local machine (more powerful CPU)
./scripts/generate-vanity-onion.sh bisq

# Transfer keys to server and install
# (Script provides complete instructions)
```

**Benefits**:
- Memorable address (e.g., `bisq7abc...onion` instead of random)
- Better branding and trust
- Generate offline on powerful machine
- 4-6 character prefix takes seconds to minutes

**Important**: Save this .onion address securely. You'll need it for the next step.

### Step 6: Configure Application Environment

Update the application environment file with your .onion address:

```bash
# Edit environment file
sudo nano /opt/bisq-support/docker/.env

# Add or update the following lines:
TOR_HIDDEN_SERVICE=your-address-here.onion
COOKIE_SECURE=false  # Must be false for .onion (HTTP-only)
```

**Example**:
```bash
TOR_HIDDEN_SERVICE=abc123def456ghi789jkl.onion
COOKIE_SECURE=false
```

### Step 7: Update Docker Compose Configuration

The production docker-compose.yml is already configured correctly:
- Nginx binds to `127.0.0.1:80:80` (localhost only)
- Bridge networking (no `network_mode: host`)
- Security headers enabled via `default.prod.conf`

**No changes needed** - the configuration is already Tor-ready.

### Step 8: Restart Application Services

```bash
# Navigate to scripts directory
cd /opt/bisq-support/scripts/

# Restart services to apply configuration
./restart.sh
```

### Step 9: Verify Tor Integration

Test the verification endpoints:

```bash
# Check verification endpoint (should return your .onion address)
curl -s http://localhost/.well-known/onion-verify/verification-info | jq

# Expected output:
# {
#   "status": "available",
#   "onion_address": "your-address.onion",
#   "timestamp": "2025-10-03T...",
#   "verification_hash": "...",
#   ...
# }
```

### Step 10: Test .onion Access

From a machine with Tor Browser or torsocks:

```bash
# Using torsocks
torsocks curl -I http://your-address.onion

# Or access via Tor Browser:
# http://your-address.onion
```

## Monitoring & Maintenance

### Check Tor Service Status

```bash
# Service status
sudo systemctl status tor

# View logs
sudo journalctl -u tor -f

# Check Tor circuits
sudo -u debian-tor tor --verify-config
```

### Prometheus Metrics

The application exposes Tor-specific metrics at `/metrics`:

- `tor_connection_status` - Tor daemon connectivity
- `tor_hidden_service_configured` - Whether .onion is configured
- `tor_onion_address_info` - .onion address information
- `tor_verification_requests_total` - Verification endpoint requests
- `tor_cookie_secure_mode` - Cookie security status

### Backup .onion Private Keys

**Critical**: Backup your hidden service keys regularly:

```bash
# Create backup directory
sudo mkdir -p /opt/bisq-support/backups/tor-keys

# Backup keys
sudo cp -r /var/lib/tor/bisq-support /opt/bisq-support/backups/tor-keys/

# Set permissions
sudo chown -R bisq-support:bisq-support /opt/bisq-support/backups/

# Compress and encrypt (recommended)
sudo tar czf /opt/bisq-support/backups/tor-keys-$(date +%Y%m%d).tar.gz \
  -C /opt/bisq-support/backups/tor-keys bisq-support
```

**Store this backup securely offline**. If you lose these keys, you'll get a new .onion address.

### Restore from Backup

```bash
# Stop Tor
sudo systemctl stop tor

# Restore keys
sudo tar xzf /path/to/tor-keys-YYYYMMDD.tar.gz \
  -C /var/lib/tor/

# Fix permissions
sudo chown -R debian-tor:debian-tor /var/lib/tor/bisq-support

# Start Tor
sudo systemctl start tor
```

## Security Considerations

### Onion-Location Header (Optional)

To advertise your .onion address to Tor Browser users, the application automatically includes the `Onion-Location` header when `TOR_HIDDEN_SERVICE` is configured.

### Cookie Security

- **MUST set `COOKIE_SECURE=false`** for .onion deployments
- .onion addresses use HTTP (not HTTPS) - Tor provides encryption
- Setting `Secure` flag would break authentication over .onion

### Rate Limiting

The nginx configuration uses **session-based rate limiting** (not IP-based) to preserve Tor anonymity:
- Multiple users behind Tor exit nodes share IPs
- Session cookies used for rate limiting instead
- Admin endpoints: 50 concurrent connections (increased for Tor)

### Access Control

Admin endpoints are accessible via:
- Localhost (127.0.0.1)
- Docker bridge network (172.16.0.0/12)
- .onion address (when Tor is configured)

## Troubleshooting

### Tor Service Won't Start

```bash
# Check configuration syntax
sudo -u debian-tor tor --verify-config

# Check permissions
sudo ls -la /var/lib/tor/

# Fix permissions if needed
sudo chown -R debian-tor:debian-tor /var/lib/tor/
```

### Can't Access .onion Address

```bash
# Verify Tor is listening
sudo ss -tlnp | grep tor

# Check hidden service directory
sudo ls -la /var/lib/tor/bisq-support/

# Verify hostname file exists
sudo cat /var/lib/tor/bisq-support/hostname

# Check nginx is bound to localhost
docker ps | grep nginx
```

### Verification Endpoints Return 503

```bash
# Check environment variable is set
cd /opt/bisq-support/docker/
grep TOR_HIDDEN_SERVICE .env

# Restart API to reload configuration
docker compose restart api

# Check API logs
docker compose logs api | grep -i tor
```

### Security Test Suite

Run the automated security tests:

```bash
cd /opt/bisq-support
./scripts/test-tor-security.sh
```

This tests:
- Verification endpoints
- Security headers (CSP, X-Frame-Options, etc.)
- Cookie security flags
- Tor metrics
- Admin authentication
- Rate limiting

## Advanced Configuration

### External API Calls via Tor (DNS Leak Prevention)

If your application makes external API calls (OpenAI, etc.), route them through Tor:

```bash
# Edit environment file
sudo nano /opt/bisq-support/docker/.env

# Add Tor proxy configuration
TOR_SOCKS_PROXY=socks5://host.docker.internal:9052
USE_TOR_FOR_EXTERNAL_APIS=true
```

This prevents DNS leaks when making external API requests.

### Multiple Hidden Services

To expose different services on different .onion addresses:

```bash
# Edit /etc/tor/torrc
sudo nano /etc/tor/torrc

# Add additional hidden service
HiddenServiceDir /var/lib/tor/bisq-support-admin/
HiddenServicePort 80 127.0.0.1:8081
HiddenServiceVersion 3
```

### Tor Browser Security Headers

The production nginx config already includes Tor-compatible security headers:
- CSP without `upgrade-insecure-requests` (no HTTPS on .onion)
- No HSTS header (.onion doesn't need it)
- Proper `Referrer-Policy` for privacy

## References

- [Tor Project - Hidden Services](https://community.torproject.org/onion-services/)
- [OWASP Tor Security Guidelines](https://owasp.org/www-community/controls/Tor)
- [Bisq Network Documentation](https://bisq.network/docs)
- Full implementation details: [docs/requirements/tor-deployment.md](requirements/tor-deployment.md)

## Support

For issues or questions:
1. Check application logs: `docker compose logs -f`
2. Check Tor logs: `sudo journalctl -u tor -f`
3. Run security tests: `./scripts/test-tor-security.sh`
4. Consult [troubleshooting guide](troubleshooting.md)
