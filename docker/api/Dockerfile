# Use the official Python image as the base image
# Use a specific version to ensure consistency with the CI/CD environment
FROM python:3.11.11-slim as builder

# Set the working directory
WORKDIR /app

# Upgrade pip before installing dependencies
RUN python -m pip install --upgrade pip

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential=12.9 \
    libxml2-dev=2.9.14+dfsg-1.3~deb12u2 \
    libxslt1-dev=1.1.35-1+deb12u1 \
    pkg-config=1.8.1-1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY api/requirements.txt .
# Install PyTorch with native MPS support - with cleanup to save space
RUN pip install --no-cache-dir torch==2.0.1 && \
    find /usr/local/lib/python3.11/site-packages/ -name "*.pyc" -delete && \
    find /usr/local/lib/python3.11/site-packages/ -name "__pycache__" -delete
# Then install the rest of the requirements
RUN pip install --no-cache-dir -r requirements.txt

# Use the same slim Python version for the final image
# This ensures a small footprint while maintaining consistency
FROM python:3.11.11-slim as final

# Set the working directory
WORKDIR /app

# Install curl for healthcheck and libxml2 runtime for mwxml
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl=7.88.1-10+deb12u12 \
    libxml2=2.9.14+dfsg-1.3~deb12u2 \
    libxslt1.1=1.1.35-1+deb12u1 \
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
RUN pip install --no-cache-dir "uvicorn[standard]==0.34.3"

# Expose the port the app runs on
EXPOSE 8000

# Run the application using Uvicorn
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]