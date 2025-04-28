# Use Python 3.11 slim as base
FROM python:3.11-slim AS builder

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev \
    libxslt-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY api/requirements.txt .
# Install PyTorch with native MPS support - with cleanup to save space
RUN pip install --no-cache-dir torch==2.0.1 && \
    find /usr/local/lib/python3.11/site-packages/ -name "*.pyc" -delete && \
    find /usr/local/lib/python3.11/site-packages/ -name "__pycache__" -delete
# Then install the rest of the requirements
RUN pip install --no-cache-dir -r requirements.txt

# Final stage
FROM python:3.11-slim

WORKDIR /app

# Install curl for healthcheck and libxml2 runtime for mwxml
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libxml2 \
    libxslt1.1 \
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