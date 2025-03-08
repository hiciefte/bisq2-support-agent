# Use Python 3.11 slim as base
FROM python:3.11-slim as builder

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY api/requirements.txt .
# Install PyTorch with native MPS support
RUN pip install --no-cache-dir torch>=2.0.0
# Then install the rest of the requirements
RUN pip install --no-cache-dir -r requirements.txt

# Final stage
FROM python:3.11-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy only necessary files from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/

# First copy the application code
COPY api/app /app/app
COPY api/setup.py /app/setup.py
COPY api/requirements.txt /app/requirements.txt
COPY api/.env* /app/

# Create data directory structure
RUN mkdir -p /app/api/data

# Copy the data directory with all its contents
COPY api/data/ /app/api/data/

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Install uvicorn
RUN pip install --no-cache-dir uvicorn

# Expose the port the app runs on
EXPOSE 8000

# Run the application using Uvicorn
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]