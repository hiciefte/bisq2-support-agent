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
   docker compose -f docker/docker-compose.yml restart api
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
   # Check the key in the Docker environment file
   grep OPENAI_API_KEY docker/.env
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