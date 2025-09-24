# --- Builder Stage ---
FROM python:3.11-slim as builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set up work directory
WORKDIR /app

# Copy dependency files
COPY api/requirements.in api/requirements.txt /app/

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt


# --- Development Stage ---
FROM python:3.11-slim as development

# Install build dependencies and tools for development
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set up work directory
WORKDIR /app

# Install pip-tools for requirements management
RUN pip install --no-cache-dir pip-tools==7.5.0

# Copy dependency files
COPY api/requirements.in /app/api/
COPY api/requirements.txt /app/api/

# Install dependencies in development mode
RUN pip install --no-cache-dir -r api/requirements.txt

# Set environment variables
ENV PYTHONPATH=/app

# Expose the port the app runs on
EXPOSE 8000

# Default command for development (can be overridden)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


# --- Final Stage ---
FROM python:3.11-slim as final

# Install curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
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
COPY api /app/api

# Set ownership of the app directory
RUN chown -R bisq-support:bisq-support /app

# Switch to the non-root user
USER bisq-support

# Set environment variables
ENV PYTHONPATH=/app

# Expose the port the app runs on
EXPOSE 8000

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]