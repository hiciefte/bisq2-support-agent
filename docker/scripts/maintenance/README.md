# Docker Maintenance Scripts

This directory contains maintenance scripts for the Bisq Support Agent services.

## Docker Cleanup Script

The `docker-cleanup.sh` script performs automatic cleanup of Docker resources to prevent disk space issues. It:

1. Checks current disk usage
2. Performs basic cleanup for normal conditions
3. Performs aggressive cleanup if disk space is critically low
4. Logs all actions to `/var/log/bisq-support/` (Note: Ensure this directory exists and is writable by the cron user or script runner)

### Setting up Automatic Cleanup

To run the cleanup script automatically, add it to the system's crontab (e.g., root's crontab):

```bash
# Edit the root crontab
sudo crontab -e

# Add this line to run cleanup at 2:00 AM every Sunday
# Adjust the path to match your installation directory if different
0 2 * * 0 /opt/bisq-support/docker/scripts/maintenance/docker-cleanup.sh
```

### Manual Execution

You can also run the script manually when needed (likely requires sudo):

```bash
# Navigate to the installation directory
cd /opt/bisq-support # Or your installation directory

sudo ./docker/scripts/maintenance/docker-cleanup.sh
```
