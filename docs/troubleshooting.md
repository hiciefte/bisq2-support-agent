# Troubleshooting Guide

This document provides solutions for common issues you might encounter with the Bisq 2 Support Agent.

## API Service Issues

### RAG Service Cleanup Error

If you see an error like this in your API logs:

```
ERROR: Application shutdown failed. Exiting.
AttributeError: 'Chroma' object has no attribute 'persist'
```

This is caused by a compatibility issue with the Chroma DB version. To fix it:

1. Edit the RAG service file:
   ```bash
   nano /path/to/bisq2-support-agent/api/app/services/rag_service.py
   ```

2. Find the `cleanup` method (around line 285) and modify it to check if the vectorstore has the persist method before calling it:
   ```python
   async def cleanup(self):
       """Clean up resources."""
       logger.info("Cleaning up RAG service resources...")
       # Check if vectorstore has persist method before calling it
       if hasattr(self.vectorstore, 'persist'):
           self.vectorstore.persist()
       logger.info("RAG service cleanup complete")
   ```

3. Restart the API service:
   ```bash
   docker compose restart api
   ```

## Bisq API Connection Issues

### Cannot Connect to Bisq API

If the FAQ extractor can't connect to the Bisq API, you might see errors like:

```
Failed to export chat messages: Cannot connect to host host.docker.internal:8090 ssl:default [Name or service not known]
```

This can be fixed by updating the Bisq API URL in the `.env` file:

1. For Docker on Linux:
   ```
   BISQ_API_URL=http://172.17.0.1:8090
   ```

2. For Docker on macOS/Windows:
   ```
   BISQ_API_URL=http://host.docker.internal:8090
   ```

3. For local development:
   ```
   BISQ_API_URL=http://localhost:8090
   ```

### Bisq API Not Listening on Expected Port

If the Bisq API is running but not listening on the expected port:

1. Check the actual port:
   ```bash
   ss -tuln | grep java
   ```

2. Update the `.env` file with the correct port:
   ```
   BISQ_API_URL=http://172.17.0.1:<actual-port>
   ```

### Tor Not Installed Error

If the Bisq API fails to start with a Tor error:

```
Caused by: bisq.network.tor.TorNotInstalledException
```

Install Tor and restart the service:

```bash
sudo apt install tor
sudo systemctl restart bisq2-api.service
```

## Docker Issues

### Docker Compose Configuration Invalid

If you see an error like:

```
ERROR: Docker Compose configuration is invalid
```

Check that:

1. The Docker Compose file exists:
   ```bash
   ls -la /path/to/bisq2-support-agent/docker/docker-compose.yml
   ```

2. The `.env` file exists:
   ```bash
   ls -la /path/to/bisq2-support-agent/.env
   ```

3. The Docker Compose file is valid:
   ```bash
   docker compose -f /path/to/bisq2-support-agent/docker/docker-compose.yml config
   ```

### Docker Compose Command Not Found

If you see an error like:

```
docker-compose: command not found
```

This could be because:

1. Docker Compose is not installed
2. You're using Docker Compose V2 which uses `docker compose` instead of `docker-compose`

Update your scripts to use the correct command:

```bash
# Change this line
docker-compose -f /path/to/docker-compose.yml up -d

# To this
docker compose -f /path/to/docker-compose.yml up -d
```

## Web UI Issues

### API Connection Timeout

If the web UI shows a timeout when connecting to the API:

1. Check if the API is running:
   ```bash
   docker compose ps
   ```

2. Verify the API URL in the web UI environment:
   ```bash
   # Check the environment variable
   echo $NEXT_PUBLIC_API_URL
   
   # Or check in the docker-compose.yml file
   grep -A 5 "web:" docker/docker-compose.yml
   ```

3. Test the API directly:
   ```bash
   curl http://localhost:8000/health
   ```

## FAQ Extractor Issues

### No New FAQs Generated

If the FAQ extractor runs but doesn't generate new FAQs:

1. Check if there are new support conversations in the Bisq API:
   ```bash
   curl http://localhost:8090/api/v1/support/export/csv | wc -l
   ```

2. Check the FAQ extractor logs:
   ```bash
   cat /path/to/bisq2-support-agent/logs/faq-extractor-*.log
   ```

3. Verify the OpenAI API key is valid:
   ```bash
   # Check the first few characters of the key in the .env file
   grep OPENAI_API_KEY .env
   ```

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
   docker compose restart prometheus
   ```

## Getting Help

If you're still experiencing issues:

1. Check the logs:
   ```bash
   docker compose logs api
   docker compose logs web
   docker compose logs faq-extractor
   ```

2. Open an issue on the GitHub repository with:
   - A clear description of the problem
   - Steps to reproduce
   - Relevant logs
   - Your environment details (OS, Docker version, etc.) 