# FAQ Update Automation

This document explains how to set up automated FAQ extraction and API updates on your server.

## Overview

The FAQ extractor processes support chat conversations from the Bisq 2 API to create a database of frequently asked questions. Running this regularly ensures that the AI assistant has access to the most up-to-date information.

The automation:
1. Fetches support chat data from the Bisq 2 API
2. Runs the FAQ extractor script to process the data
3. Waits for the extraction to complete
4. Restarts the API service to load the new FAQs

## Prerequisites

Before setting up the FAQ automation, ensure you have:

1. A running Bisq 2 API instance (see [Bisq 2 API Setup](bisq2-api-setup.md))
2. The Bisq Support Agent deployed and running
3. Proper configuration in the `.env` file pointing to the Bisq 2 API

## Setup Instructions

### 1. Prepare the Update Script

1. Copy the `update-faqs.sh` script to your server:
   ```bash
   scp docker/scripts/update-faqs.sh user@your-server:/path/to/scripts/
   ```

2. Edit the script on your server to set the correct project directory:
   ```bash
   # Open the script
   nano /path/to/scripts/update-faqs.sh
   
   # Update this line with your actual project path
   PROJECT_DIR="/path/to/bisq2-support-agent"
   ```

3. Make sure your `.env` file exists in the project directory with the correct Bisq API URL:
   ```bash
   # Check if .env file exists
   ls -la /path/to/bisq2-support-agent/.env
   
   # If it doesn't exist, copy the example file
   cp /path/to/bisq2-support-agent/.env.example /path/to/bisq2-support-agent/.env
   
   # Edit the .env file with your configuration
   nano /path/to/bisq2-support-agent/.env
   
   # Ensure the BISQ_API_URL is set correctly
   # For Docker on the same machine:
   BISQ_API_URL=http://172.17.0.1:8090
   ```

4. Make the script executable:
   ```bash
   chmod +x /path/to/scripts/update-faqs.sh
   ```

### 2. Set Up the Cron Job

1. Open the crontab editor:
   ```bash
   crontab -e
   ```

2. Add a line to run the script weekly (every Sunday at midnight):
   ```
   0 0 * * 0 /path/to/scripts/update-faqs.sh
   ```

3. Save and exit the editor.

### 3. Test the Script

Run the script manually to ensure it works correctly:
```bash
/path/to/scripts/update-faqs.sh
```

Check the log file for any errors:
```bash
cat /path/to/bisq2-support-agent/logs/faq-updater.log
```

## Enhanced Automation (Optional)

For more robust automation, you can use the enhanced script that includes:
- Backup management
- Health checks
- Email notifications

1. Copy the enhanced script:
   ```bash
   cp docker/scripts/update-faqs-enhanced.sh /path/to/scripts/
   ```

2. Configure email notifications:
   ```bash
   # Edit the script
   nano /path/to/scripts/update-faqs-enhanced.sh
   
   # Update the email address
   ADMIN_EMAIL="your-email@example.com"
   ```

3. Make it executable:
   ```bash
   chmod +x /path/to/scripts/update-faqs-enhanced.sh
   ```

4. Update the cron job to use the enhanced script:
   ```
   0 0 * * 0 /path/to/scripts/update-faqs-enhanced.sh
   ```

## Log Rotation

To prevent logs from growing too large, set up log rotation:

1. Copy the log rotation script:
   ```bash
   cp docker/scripts/rotate-logs.sh /path/to/scripts/
   ```

2. Make it executable:
   ```bash
   chmod +x /path/to/scripts/rotate-logs.sh
   ```

3. Add it to crontab to run monthly:
   ```
   0 0 1 * * /path/to/scripts/rotate-logs.sh
   ```

## Customizing the Schedule

The cron schedule `0 0 * * 0` runs the script at midnight every Sunday. You can adjust this to your preferred schedule:

- `0 0 * * *` - Run daily at midnight
- `0 0 * * 1-5` - Run on weekdays at midnight
- `0 0 1 * *` - Run on the first day of each month

For more cron schedule options, see [crontab.guru](https://crontab.guru/).

## Troubleshooting

### Common Issues

1. **Permission Denied**: Ensure the script is executable and the user running the cron job has permission to execute Docker commands.
   ```bash
   sudo usermod -aG docker $USER
   ```

2. **Docker Compose Not Found**: Ensure Docker Compose is installed and in the PATH for the user running the cron job.

3. **Log File Access**: Ensure the user running the cron job has permission to write to the log file:
   ```bash
   sudo touch /var/log/bisq-faq-updater.log
   sudo chown $USER:$USER /var/log/bisq-faq-updater.log
   ```

4. **Environment File Not Found**: If you see an error like `no configuration file provided: not found`, make sure your `.env` file exists in the project directory:
   ```bash
   # Check if .env file exists
   ls -la /path/to/bisq2-support-agent/.env
   
   # Create it if it doesn't exist
   cp /path/to/bisq2-support-agent/.env.example /path/to/bisq2-support-agent/.env
   nano /path/to/bisq2-support-agent/.env  # Edit with your settings
   ```

5. **Bisq API Connection Issues**: If the FAQ extractor can't connect to the Bisq API:
   - Check if the Bisq API is running: `systemctl status bisq2-api.service`
   - Verify the API URL in the `.env` file is correct
   - Test the connection: `curl http://172.17.0.1:8090/api/v1/support/export/csv`

6. **Docker Compose Version Issues**: If you're using Docker Compose V2, you might need to use `docker compose` instead of `docker-compose` in the scripts. Check your Docker Compose version:
   ```bash
   docker compose version
   ```

### Checking Logs

To monitor the script execution:
```bash
tail -f /path/to/bisq2-support-agent/logs/faq-updater.log
```

To check the FAQ extractor logs:
```bash
cat /path/to/bisq2-support-agent/logs/faq-extractor-*.log
```