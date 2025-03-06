# Setting Up the Bisq 2 API for FAQ Extraction

This guide provides instructions for setting up the Bisq 2 API project both locally and on a cloud instance to work with the FAQ extractor.

## Prerequisites

- Java JDK 22 or later
- Git
- Docker and Docker Compose (for the support agent)
- Linux/macOS/Windows with WSL

## Local Setup

### 1. Clone the Bisq 2 Repository

```bash
# Clone the repository with the support API branch
git clone https://github.com/hiciefte/bisq2.git -b add-support-api
cd bisq2
```

### 2. Initialize Git Submodules

```bash
git submodule init
git submodule update
```

### 3. Build and Run the Bisq 2 API

```bash
# Build and run the HTTP API app
./gradlew :apps:http-api-app:run
```

If you need to specify a custom data directory:

```bash
./gradlew :apps:http-api-app:run --args="--data-dir=/path/to/data"
```

### 4. Verify the API is Running

```bash
# Test the support export endpoint
curl -X GET http://localhost:8090/api/v1/support/export/csv
```

If successful, you should receive a CSV response with support chat data.

## Cloud Instance Setup

### 1. Set Up the Server

```bash
# Update the system
sudo apt update
sudo apt upgrade -y

# Install required packages
sudo apt install -y openjdk-22-jdk git curl unzip tor
```

### 2. Clone the Repository

```bash
# Create a workspace directory
mkdir -p ~/workspace
cd ~/workspace

# Clone the repository with the support API branch
git clone https://github.com/hiciefte/bisq2.git -b add-support-api
cd bisq2
```

### 3. Initialize Git Submodules

```bash
git submodule init
git submodule update
```

### 4. Create a Systemd Service

Create a service file to run the Bisq API as a background service:

```bash
sudo nano /etc/systemd/system/bisq2-api.service
```

Add the following content:

```
[Unit]
Description=Bisq2 Headless API
After=network.target

[Service]
Type=simple
User=<your-username>
WorkingDirectory=/home/<your-username>/workspace/bisq2
ExecStart=/home/<your-username>/workspace/bisq2/gradlew :apps:http-api-app:run -Djava.awt.headless=true
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
# Create a specific data directory
Environment="BISQ_DATA_DIR=/home/<your-username>/.local/share/bisq2"
# Set API to listen on all interfaces (important for Docker access)
Environment="BISQ_API_HOST=0.0.0.0"
# Set Java memory limits
Environment="JAVA_OPTS=-Xmx1g"

[Install]
WantedBy=multi-user.target
```

Replace `<your-username>` with your actual username.

### 5. Enable and Start the Service

```bash
sudo systemctl daemon-reload
sudo systemctl enable bisq2-api.service
sudo systemctl start bisq2-api.service
```

### 6. Check Service Status

```bash
sudo systemctl status bisq2-api.service
```

### 7. Verify the API is Running

```bash
# Test the support export endpoint
curl -X GET http://localhost:8090/api/v1/support/export/csv
```

### 8. Configure Firewall (Optional but Recommended)

If you want to restrict access to the Bisq API:

```bash
# Allow only Docker containers to access the API
sudo ufw allow from 172.17.0.0/16 to any port 8090

# Deny all other access to this port
sudo ufw deny 8090
```

## Configuring the Support Agent to Use the Bisq API

### 1. Update the .env File

In your Bisq Support Agent project:

```bash
# For local development
BISQ_API_URL=http://localhost:8090

# For Docker on the same machine
BISQ_API_URL=http://172.17.0.1:8090
```

### 2. Update docker-compose.yml

Ensure the `faq-extractor` service has the correct Bisq API URL:

```yaml
faq-extractor:
  build:
    context: ..
    dockerfile: docker/api/Dockerfile
  command: ["python", "-m", "app.scripts.extract_faqs"]
  volumes:
    - ../api/data:/app/data
  environment:
    - BISQ_API_URL=http://172.17.0.1:8090  # Docker host IP
  depends_on:
    - api
  networks:
    - bisq-support-network
```

## Troubleshooting

### 1. Tor Not Installed Error

If you see an error like `bisq.network.tor.TorNotInstalledException`:

```bash
# Install Tor
sudo apt install tor

# Restart the Bisq API service
sudo systemctl restart bisq2-api.service
```

### 2. Connection Refused

If the FAQ extractor can't connect to the Bisq API:

1. Check if the Bisq API is running:
   ```bash
   sudo systemctl status bisq2-api.service
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

### 3. No Data in Export

If the API returns an empty CSV:

1. Make sure you have some support chat data in your Bisq instance
2. Check the Bisq logs for any errors:
   ```bash
   sudo journalctl -u bisq2-api.service | grep -i error
   ``` 