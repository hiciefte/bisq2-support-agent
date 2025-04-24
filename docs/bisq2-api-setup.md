# Setting Up the Bisq 2 API for FAQ Extraction

This guide provides instructions for setting up the Bisq 2 API project locally for development and testing purposes. For production deployment, the `deploy.sh` script handles the Bisq 2 API setup automatically.

## Prerequisites

- Java JDK 21 or later
- Git
- Docker and Docker Compose (for the support agent)
- Linux/macOS/Windows with WSL

## Local Setup

### 1. Clone the Bisq 2 Repository

```bash
# Clone the repository with the support API branch
git clone --recurse-submodules https://github.com/hiciefte/bisq2.git -b add-support-api
cd bisq2
```

Note: The `--recurse-submodules` flag automatically initializes and updates all submodules in one step.

### 2. Update to Latest Version (if needed)

```bash
git pull --recurse-submodules
```

### 3. Build and Run the Bisq 2 API

```bash
# Build and run the HTTP API app
./gradlew :apps:http-api-app:run
```

### 4. Verify the API is Running

```bash
# Test the support export endpoint
curl -X GET http://localhost:8090/api/v1/support/export/csv
```

If successful, you should receive a CSV response with support chat data.

## Configuring the Support Agent to Use the Bisq API

### 1. Update the Environment Files

#### For Docker Deployment:

Edit the `docker/.env` file:

```bash
# Copy the example file if needed
cp docker/.env.example docker/.env
nano docker/.env
```

Set the Bisq API URL:

```
# For Docker on Linux
BISQ_API_URL=http://172.17.0.1:8090

# For Docker on macOS/Windows
# BISQ_API_URL=http://host.docker.internal:8090
```

#### For Local API Development:

Edit the `api/.env` file:

```bash
# Copy the example file if needed
cp api/.env.example api/.env
nano api/.env
```

Set the Bisq API URL:

```
# For local development
BISQ_API_URL=http://localhost:8090
```

## Troubleshooting

### 1. Tor Not Installed Error

If you see an error like `bisq.network.tor.TorNotInstalledException`:

```bash
# Install Tor
sudo apt install tor  # For Debian/Ubuntu
brew install tor     # For macOS
```

### 2. Connection Refused

If the FAQ extractor can't connect to the Bisq API:

1. Check if the Bisq API is running:
   ```bash
   # If running as a service
   sudo systemctl status bisq2-api.service
   
   # If running in terminal
   ps aux | grep http-api-app
   ```

2. Verify the API is listening on the correct interface:
   ```bash
   ss -tuln | grep 8090
   ```

3. Ensure the Docker network can reach the host:
   ```bash
   # From inside a Docker container
   curl http://172.17.0.1:8090/api/v1/support/export/csv
   ```

### 3. Java Version Issues

If you encounter Java-related errors:

```bash
# Check Java version
java -version

# Install JDK 21 if needed
# For Debian/Ubuntu
sudo apt install openjdk-21-jdk

# For macOS
brew install openjdk@21
```

### 4. Git Submodule Issues

If you encounter issues with Git submodules:

```bash
# Reinitialize submodules
git submodule init
git submodule update

# Or use the recursive approach
git clone --recurse-submodules https://github.com/hiciefte/bisq2.git -b add-support-api
```

### 5. Multiple LLM Provider Support

The support agent now supports multiple LLM providers:

- Configure `LLM_PROVIDER` in your `.env` files to select the provider (options: `openai`, `xai`)
- Each provider has its own configuration settings (API keys, models, etc.)
- This allows for flexibility in choosing the best LLM for your needs
