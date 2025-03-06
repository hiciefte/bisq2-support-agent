# FAQ Update Automation

This document explains how to set up automated FAQ extraction and API updates on your server.

## Overview

The FAQ extractor processes support chat conversations to create a database of frequently asked questions. Running this regularly ensures that the AI assistant has access to the most up-to-date information.

The automation:
1. Runs the FAQ extractor script
2. Waits for the extraction to complete
3. Restarts the API service to load the new FAQs

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

3. Make the script executable:
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
cat /var/log/bisq-faq-updater.log
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

### Checking Logs

To monitor the script execution:
```bash
tail -f /var/log/bisq-faq-updater.log
```