# Docker Maintenance Scripts

This directory contains maintenance scripts for the Bisq Support Agent services.

## Docker Cleanup Script

The `docker-cleanup.sh` script performs automatic cleanup of Docker resources to prevent disk space issues. It:

1. Checks current disk usage
2. Performs basic cleanup for normal conditions
3. Performs aggressive cleanup if disk space is critically low
4. Logs all actions to `/var/log/bisq-support/`

### Setting up Automatic Cleanup

To run the cleanup script automatically, add it to the system's crontab:

```bash
# Edit the system crontab
sudo crontab -e

# Add this line to run cleanup at 2:00 AM every Sunday
0 2 * * 0 /absolute/path/to/bisq2-support-agent/docker/scripts/maintenance/docker-cleanup.sh
```

Or if you prefer to use the user's crontab:

```bash
# Edit the current user's crontab
crontab -e

# Add this line to run cleanup at 2:00 AM every Sunday
0 2 * * 0 /absolute/path/to/bisq2-support-agent/docker/scripts/maintenance/docker-cleanup.sh
```

### Manual Execution

You can also run the script manually when needed:

```bash
cd /path/to/bisq2-support-agent/docker
./scripts/maintenance/docker-cleanup.sh
```