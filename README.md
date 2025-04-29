# Bisq 2 Support Assistant

A RAG-based support assistant for Bisq 2, providing automated support through a chat interface.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview

This project consists of the following components:

- **API Service**: FastAPI-based backend implementing the RAG (Retrieval Augmented Generation) system
- **Web Frontend**: Next.js web application for the chat interface
- **Bisq Integration**: Connection to Bisq 2 API for support chat data
- **Monitoring**: Prometheus and Grafana for system monitoring

## Prerequisites

- Docker and Docker Compose installed
- OpenAI API key (for the RAG model)
- Python 3.11+ (for local development)
- Node.js 20+ (for web frontend development)
- Bisq 2 API instance (for FAQ extraction) - see [Bisq 2 API Setup](docs/bisq2-api-setup.md)

## Project Structure

```
bisq-support-assistant/
├── api/                  # Backend API service
│   ├── app/              # FastAPI application
│   │   ├── core/         # Core configuration
│   │   ├── routes/       # API endpoints
│   │   ├── services/     # Core services including RAG
│   │   └── main.py       # Application entry point
│   ├── data/             # Data directory
│   │   ├── wiki/         # Wiki documents for RAG
│   │   ├── feedback/     # User feedback storage
│   │   └── vectorstore/  # Vector embeddings storage
│   └── requirements.txt  # Python dependencies
├── web/                  # Next.js web frontend
├── docker/               # Docker configuration
│   ├── api/              # API service Dockerfile
│   ├── web/              # Web frontend Dockerfile and dev version
│   ├── nginx/            # Nginx configuration for development and testing
│   ├── prometheus/       # Prometheus configuration
│   ├── grafana/          # Grafana configuration
│   ├── scripts/          # Maintenance and automation scripts
│   ├── docker-compose.yml      # Production Docker Compose configuration
│   └── docker-compose.local.yml # Development Docker Compose configuration
├── docs/                 # Documentation
│   ├── bisq2-api-setup.md # Bisq 2 API setup guide
│   ├── troubleshooting.md # Troubleshooting guide
│   └── monitoring-security.md # Monitoring security guide
├── scripts/              # Utility scripts
│   ├── deploy.sh         # Production deployment script
│   ├── update.sh         # Update script
│   ├── download_bisq2_media_wiki.py # Wiki content downloader
│   └── fix_xml_namespaces.py # XML namespace fixer
└── run-local.sh         # Local development script
```

## Deployment

### Production Deployment

For production deployment on a DigitalOcean droplet or similar cloud instance:

1. Clone the repository:
```bash
git clone <repository-url>
cd bisq2-support-agent
```

2. Set up environment variables:
```bash
# Required environment variables
export BISQ_SUPPORT_REPO_URL="git@github.com:hiciefte/bisq2-support-agent.git"
export BISQ2_REPO_URL="git@github.com:hiciefte/bisq2.git"
export BISQ_SUPPORT_INSTALL_DIR="/opt/bisq-support"
export BISQ2_INSTALL_DIR="/opt/bisq2"

# Optional environment variables
export BISQ_SUPPORT_SECRETS_DIR="/opt/bisq-support/secrets"
export BISQ_SUPPORT_LOG_DIR="/opt/bisq-support/logs"
export BISQ_SUPPORT_SSH_KEY_PATH="/root/.ssh/bisq2_support_agent"
```

> **Note:** Always use absolute paths for environment variables. Do not use tilde (`~`) or relative paths as they may cause issues with systemd services.

3. Make the deployment script executable:
```bash
chmod +x ./scripts/deploy.sh
```

4. Run the deployment script with sudo, preserving environment variables:
```bash
# Method 1: Use sudo -E to preserve environment variables
sudo -E ./scripts/deploy.sh
```

> **Note:** When using `sudo`, environment variables are not passed to the sudo environment by default. You must either use `sudo -E` to preserve all environment variables or explicitly pass them to the sudo command as shown above.

The deployment script will:
- Install required dependencies (Docker, git, Java, etc.)
- Configure Docker and enable it on boot
- Clone or update the repository
- Set up the environment and create necessary directories
- Configure environment variables
- Start all services with health checks

After deployment, the following services will be available:
- Web Frontend: http://localhost:3000
- API Service: http://localhost:8000
- Grafana Dashboard: http://localhost:3001
- Prometheus Metrics: http://localhost:9090

### Updating the Application

To update the application to the latest version from the repository after initial deployment:

1.  **Log in** to your server via SSH.
2.  **Navigate** to the installation directory:
    ```bash
    cd /opt/bisq-support # Or your custom BISQ_SUPPORT_INSTALL_DIR
    ```
3.  **(Optional) Use SSH Agent:** If your deployment SSH key (`$BISQ_SUPPORT_SSH_KEY_PATH`) is protected by a passphrase, start `ssh-agent` and add your key:
    ```bash
    eval $(ssh-agent -s)
    ssh-add /path/to/your/private_key # e.g., /root/.ssh/bisq2_support_agent
    # Enter passphrase if prompted
    ```
4.  **Run the update script:** Execute the script with `sudo`.
    ```bash
    sudo ./scripts/update.sh
    ```

The update script will:
- Stash any local, uncommitted changes.
- Pull the latest code from the repository.
- Analyze changes to determine if a container rebuild or just restarts are needed.
- Apply the updates (rebuild/restart relevant services).
- Perform health checks and a basic chat functionality test.
- Attempt to automatically roll back to the previous version if update checks fail.
- Attempt to restore stashed local changes.

### Handling Permission Changes in Git

During deployment or updates, you may encounter Git errors related to permission changes:

```
error: Your local changes to the following files would be overwritten by merge:
        scripts/deploy.sh
Please commit your changes or stash them before you merge.
Aborting
```

This happens because the deployment script changes file permissions (e.g., `chmod +x ./scripts/deploy.sh`), which Git detects as changes to the files. To resolve this:

1. **Option 1: Let `update.sh` handle it.** (Recommended)
2. **Option 2: Force the update manually** (If update script stash fails)
    ```bash
    git fetch origin
    git reset --hard origin/main
    ```
3. **Option 3: Configure Git to ignore permission changes** (Use with caution)
    ```bash
    git config core.fileMode false
    ```

### Troubleshooting Deployment/Update Issues

#### Kernel Updates

The deployment script may detect that your system is running an outdated kernel:

```
Pending kernel upgrade!
Running kernel version:
  6.11.0-9-generic
Diagnostics:
  The currently running kernel version is not the expected kernel version 6.11.0-24-generic.
```

While the deployment can continue, it's recommended to reboot your system after the deployment to load the new kernel:

```bash
sudo reboot
```

### Environment Variables

The deployment script uses the following environment variables:

#### Required Variables
- `BISQ_SUPPORT_REPO_URL`: URL of the Bisq Support Agent repository
- `BISQ2_REPO_URL`: URL of the Bisq 2 repository
- `BISQ_SUPPORT_INSTALL_DIR`: Installation directory for Bisq Support Agent
- `BISQ2_INSTALL_DIR`: Installation directory for Bisq 2

#### Optional Variables
- `BISQ_SUPPORT_SECRETS_DIR`: Directory for secrets (default: `$INSTALL_DIR/secrets`)
- `BISQ_SUPPORT_LOG_DIR`: Directory for logs (default: `$INSTALL_DIR/logs`)
- `BISQ_SUPPORT_SSH_KEY_PATH`: Path to SSH key for GitHub authentication (default: `$HOME/.ssh/bisq2_support_agent`)

For more information about environment variables, see [Environment Configuration](docs/environment-configuration.md).

### Local Development

For local development, use the local configuration:

```bash
# Make the local development script executable
chmod +x ./run-local.sh

# Build and start the local development environment
./run-local.sh
```

This configuration:
- Mounts local directories for real-time code changes
- Uses Dockerfile.dev for the web frontend with hot reloading
- Sets development-specific environment variables
- Provides a simplified setup without Prometheus or Grafana

## Environment Configuration

### Production Environment

The deployment script will create a `.env` file in the `docker` directory. You'll need to provide:

1. OpenAI API key during deployment
2. Review and update other settings in `docker/.env` as needed

### Local Development Environment

For local development, create `.env` files in both the `api` and `docker` directories:

```bash
# For API development
cp api/.env.example api/.env

# For Docker development
cp docker/.env.example docker/.env
```

Required variables:
```
# OpenAI API key (required for the RAG service)
OPENAI_API_KEY=your_api_key_here

# Admin API key for protected endpoints
ADMIN_API_KEY=your_admin_key_here

# Grafana credentials (for monitoring)
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=securepassword
```

## Data Directory Structure

The project uses the following data directories:

- `api/data/wiki/`: Contains Markdown files with documentation
- `api/data/vectorstore/`: Contains vector embeddings for the RAG system
- `api/data/feedback/`: Stores user feedback in monthly files

These directories are automatically created during deployment. For local development, create them manually:

```bash
mkdir -p api/data/wiki api/data/vectorstore api/data/feedback
```

## Running Services Individually

### API Service:

1. Create and activate a virtual environment:
   ```bash
   cd api
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the API service:
   ```bash
   python -m uvicorn app.main:app --reload
   ```

### Web Frontend:

1. Navigate to web directory:
   ```bash
   cd web
   ```

2. Install dependencies and start:
   ```bash
   npm install
   npm run dev
   ```

## Adding Content for the RAG System

The RAG system uses two main sources of content:

### 1. Wiki Documents
- **Location**: `api/data/wiki/`
- **Purpose**: 
  - Primary knowledge base for the RAG system
  - Provides structured documentation about Bisq 1 and Bisq 2
  - Used to generate accurate and context-aware responses to user queries
- **Supported Formats**:
  - MediaWiki XML dump file (`bisq_dump.xml`) for bulk import
- **Processing Pipeline**:
  1. **Initial Processing**:
     - XML dumps are processed by `process_wiki_dump.py`
     - Content is cleaned and categorized (Bisq 1, Bisq 2, or general)
     - Documents are converted to JSONL format with metadata
  2. **Document Preparation**:
     - Documents are loaded by `WikiService`
     - Each document is tagged with metadata (category, version, section)
     - Content is split into chunks for better retrieval
     - Source weights are assigned (wiki content has a weight of 1.1)
  3. **RAG Integration**:
     - Processed documents are converted to embeddings
     - Stored in a Chroma vector database
     - Used alongside FAQ data for comprehensive responses
     - Documents are prioritized based on version relevance (Bisq 2 > Bisq 1 > general)
- **Metadata Structure**:
  ```json
  {
    "title": "Document Title",
    "content": "Document Content",
    "category": "bisq2|bisq1|general",
    "type": "wiki",
    "section": "Section Name",
    "source_weight": 1.1,
    "bisq_version": "Bisq 2|Bisq 1|General"
  }
  ```

### 2. FAQ Data
- **Automatic Extraction**:
  - FAQs are automatically extracted from support chat conversations
  - The system uses OpenAI to identify and format FAQs
  - Extracted FAQs are stored in `api/data/extracted_faq.jsonl`
- **Manual Addition**:
  - You can manually add FAQs by appending to the JSONL file
  - Each FAQ entry should follow this format:
    ```json
    {"question": "Your question here", "answer": "Your answer here", "category": "Category name", "source": "Bisq Support Chat"}
    ```

### Content Processing Flow

1. **Initial Setup**:
   - Wiki documents are loaded and processed by `WikiService`
   - FAQ data is loaded and processed by `FAQService`
   - Both services prepare documents for the RAG system

2. **Vector Store**:
   - Documents are converted to embeddings using OpenAI
   - Stored in a Chroma vector database
   - The vector store is automatically updated when new content is added

3. **FAQ Extraction Process**:
   - Runs automatically via the `scheduler` service
   - Fetches new support chat messages from Bisq API
   - Processes conversations and extracts FAQs
   - Updates the FAQ database
   - The RAG system automatically picks up new FAQs

### Adding New Content

1. **Wiki Documents**:
   ```bash
   # Add new Markdown files
   cp your_document.md api/data/wiki/
   
   # Or add a MediaWiki XML dump
   cp bisq_dump.xml api/data/wiki/
   ```

2. **Manual FAQ Addition**:
   ```bash
   # Append to the FAQ file
   echo '{"question": "New question", "answer": "New answer", "category": "Category", "source": "Bisq Support Chat"}' >> api/data/extracted_faq.jsonl
   ```

3. **Rebuilding the Vector Store**:
   ```bash
   # Restart the API service to rebuild the vector store
   docker compose -f docker/docker-compose.yml restart api
   ```

### Monitoring Content

- Check the API logs for content processing status:
  ```bash
  docker logs docker-api-1
  ```
- Monitor FAQ extraction:
  ```bash
  docker logs docker-faq-extractor-1
  ```

For more details about the FAQ extraction process, see [FAQ Extraction Documentation](docs/faq_extraction.md).

## Monitoring and Security

The project includes Prometheus and Grafana for monitoring:

- **Prometheus**: Collects metrics from the API and web services
- **Grafana**: Provides dashboards for visualizing the metrics

For details on securing these services, see [Monitoring Security Guide](docs/monitoring-security.md).

## Troubleshooting

If you encounter any issues, please refer to the [Troubleshooting Guide](docs/troubleshooting.md). Common issues covered include:

- API service errors
- Bisq API connection issues
- Docker configuration problems
- FAQ extractor issues
- Monitoring setup problems

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [Bisq](https://bisq.network/) - The decentralized exchange
- [LangChain](https://langchain.com/) - For RAG implementation
- [FastAPI](https://fastapi.tiangolo.com/) - For the API framework
- [Next.js](https://nextjs.org/) - For the web frontend
