# --- Builder Stage ---
FROM python:3.11-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set up work directory
WORKDIR /app

# Copy dependency files
COPY api/requirements.in api/requirements.txt /app/

# Install CPU-only PyTorch (avoids ~5GB of CUDA libraries) then remaining deps
# This is a CPU-only server (DigitalOcean droplet), no GPU available
# hadolint ignore=DL3013
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt


# --- Development Stage ---
FROM python:3.11-slim AS development

# Install build dependencies and tools for development
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set up work directory
WORKDIR /app

# Install pip-tools for requirements management
RUN pip install --no-cache-dir pip-tools==7.5.1

# Copy dependency files
COPY api/requirements.in /app/api/
COPY api/requirements.txt /app/api/

# Install CPU-only PyTorch (avoids ~5GB of CUDA libraries) then remaining deps
# hadolint ignore=DL3013
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r api/requirements.txt

# Set environment variables
ENV PYTHONPATH=/app

# Expose the port the app runs on
EXPOSE 8000

# Default command for development (can be overridden)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


# --- Final Stage ---
FROM python:3.11-slim AS final

# Install curl for health checks and gosu for privilege dropping
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Arguments for user and group IDs
ARG APP_UID=1001
ARG APP_GID=1001

# Create a non-root user
RUN groupadd -g "${APP_GID}" bisq-support && \
    useradd -l -u "${APP_UID}" -g bisq-support -s /bin/false -m bisq-support

# Set up work directory
WORKDIR /app

# Copy dependencies from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
# ⚠️ CRITICAL: This COPY instruction bakes code into the image
# Any changes to api/app/ require container REBUILD, not just restart
# The deployment script checks for these changes using needs_api_rebuild()
COPY api/app /app/app

# Set ownership of the app directory
RUN chown -R bisq-support:bisq-support /app

# Copy and set up entrypoint script
COPY docker/api/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Set build arguments
ARG BUILD_ID=bisq-support-build

# Set environment variables
ENV PYTHONPATH=/app
ENV BUILD_ID=${BUILD_ID}

# Expose the port the app runs on
EXPOSE 8000

# Use entrypoint to fix permissions on startup, then drop privileges
# Entrypoint will run as root initially to fix permissions, then exec as bisq-support user
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
