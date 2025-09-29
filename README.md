# Bisq 2 Support Assistant

A RAG-based support assistant for Bisq 2, providing automated support through a chat interface.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview

This project consists of the following components:

- **API Service**: FastAPI-based backend implementing the RAG (Retrieval Augmented Generation) system
- **Web Frontend**: Next.js web application for the chat interface
- **Bisq Integration**: Connection to Bisq 2 API for support chat data
- **Monitoring**: Prometheus and Grafana for system monitoring

## Getting Started

This project includes two primary methods for getting started:
-   **Local Development:** Use the `run-local.sh` script for a fully containerized local environment on your machine.
-   **Production Deployment:** Use the `scripts/deploy.sh` script for initial setup on a dedicated server.

### Local Development Environment

For developing on your local machine, the project provides a comprehensive Docker Compose setup that mirrors the production environment.

**Prerequisites:** Docker, Git, Python 3.11+, Node.js 20+, Java 17+.

**To start the local environment, use the provided shell script:**
```bash
# This script handles building all containers and starting them in the correct order.
./run-local.sh
```
This is the **only** command needed for local development. It uses `docker/.env` for secrets and `docker-compose.local.yml` for development-specific configurations like hot-reloading. The scripts in the `scripts/` directory are **not** intended for local use.

### Production Deployment

This project is designed to be deployed via Docker on a dedicated server. The `scripts/` directory contains the necessary automation for installation, updates, and management.

#### Initial Server Setup

The `scripts/deploy.sh` script is the main entrypoint for setting up a new production server. It performs the following actions:
1.  Creates a dedicated application user (`bisq-support`).
2.  Clones the repository into `/opt/bisq-support`.
3.  Creates all necessary data and logging directories.
4.  Sets the correct file ownership to the `bisq-support` user.
5.  Builds and starts all Docker containers.

To run it, execute the script from your server:
```bash
curl -sSL https://raw.githubusercontent.com/bisq-network/bisq2-support-agent/main/scripts/deploy.sh | sudo bash
```

#### Post-Deployment Configuration

After deployment, you must configure CORS to access the admin interface:

1. **Edit CORS settings** in `/opt/bisq-support/docker/.env`:
   ```bash
   # Update CORS_ORIGINS to include your server IP/domain:
   CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://YOUR_SERVER_IP
   ```

2. **Restart services**:
   ```bash
   cd /opt/bisq-support/scripts/
   ./restart.sh
   ```

3. **Access admin interface**: Navigate to `http://YOUR_SERVER_IP/admin` and use the `ADMIN_API_KEY` from the `.env` file

#### Managing the Application

Once deployed, the production application should be managed using the following scripts located in `/opt/bisq-support/scripts/`:

-   **`start.sh`**: Starts the application containers using the production configuration.
-   **`stop.sh`**: Stops and removes the application containers.
-   **`restart.sh`**: Performs a graceful stop followed by a start.

These scripts are location-aware and source their configuration from a production environment file (`/etc/bisq-support/deploy.env`). They should not be used for local development.

**Note**: If you encounter "Permission denied" errors when running scripts, ensure they are executable:
```bash
chmod +x /opt/bisq-support/scripts/*.sh
```

### Updating the Application

The `scripts/update.sh` script handles pulling the latest changes from the Git repository, rebuilding Docker images, and restarting the services. It includes a rollback mechanism in case of failure.

### Handling Git Permission Changes

The deployment script may make scripts executable, which Git sees as a file modification. The `update.sh` script is designed to handle this by stashing changes. If you encounter issues, you can resolve them manually by resetting the branch: `git fetch origin && git reset --hard origin/main`.

### Troubleshooting Deployment

-   **Kernel Updates:** The script may warn about a pending kernel upgrade. It is safe to proceed, but you should `sudo reboot` after the deployment is complete.
-   **Environment Variables:** Ensure all required variables are exported correctly before running scripts with `sudo -E`. For a full list, see the `deploy.sh` script and the [Environment Configuration](docs/environment-configuration.md) doc.

## Data Directory Structure

The project uses the following data directories within `api/data/`:

-   `wiki/`: Contains wiki documents for the RAG knowledge base.
-   `vectorstore/`: Stores vector embeddings for semantic search.
-   `feedback/`: Stores user feedback.
-   `extracted_faq.jsonl`: Stores FAQs automatically generated from support chats.

These are automatically created during deployment. For local development, create them manually if needed: `mkdir -p api/data/{wiki,vectorstore,feedback}`.

## RAG System Content

The RAG system's knowledge base is built from two sources:

### 1. Wiki Documents
-   **Location**: `api/data/wiki/`
-   **Purpose**:
    - Primary knowledge base for the RAG system
    - Provides structured documentation about Bisq 1 and Bisq 2
    - Used to generate accurate and context-aware responses to user queries
-   **Supported Formats**:
    - MediaWiki XML dump file (`bisq_dump.xml`) for bulk import
-   **Processing Pipeline**:
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
-   **Metadata Structure**:
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
-   **Automatic Extraction**:
    - FAQs are automatically extracted from support chat conversations
    - The system uses OpenAI to identify and format FAQs
    - Extracted FAQs are stored in `api/data/extracted_faq.jsonl`
-   **Manual Addition**:
    - You can manually add FAQs by appending to the JSONL file
    - Each FAQ entry should follow this format:
      ```json
      {"question": "Your question here", "answer": "Your answer here", "category": "Category name", "source": "Bisq Support Chat"}
      ```

### Content Processing

When the API service starts, it automatically processes all content from the `wiki` and `faq` sources, converts it into vector embeddings, and stores it in the ChromaDB vector store (`api/data/vectorstore/`).

To add new content, simply add files to the `api/data/wiki/` directory or add entries to the FAQ file, then restart the API service.

```bash
# To add new wiki content and rebuild the vector store
cp your_document.md api/data/wiki/
docker compose -f docker/docker-compose.yml restart api
```

For more details on the automated FAQ extraction process, see [FAQ Extraction Documentation](docs/faq_extraction.md).

## Monitoring and Security

The project includes Prometheus and Grafana for monitoring.
-   **Prometheus**: Collects metrics from the API and web services.
-   **Grafana**: Provides dashboards for visualizing metrics.

For details on securing these services, see the [Monitoring Security Guide](docs/monitoring-security.md).

## Development

### Updating Python Dependencies

When you need to update Python dependencies or if GitHub Actions fails with "requirements.txt is not up to date":

**❌ Don't do this (creates platform-specific dependencies):**
```bash
pip-compile api/requirements.in -o api/requirements.txt
```

**✅ Do this instead (creates cross-platform compatible dependencies):**
```bash
# Use Docker to generate requirements.txt in the same Linux environment as CI
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml run --build --rm api pip-compile api/requirements.in -o api/requirements.txt --upgrade --no-strip-extras
```

This ensures the generated `requirements.txt` is compatible with both your local development environment and the Linux-based GitHub Actions CI environment.

### Adding New Dependencies

1. Add the package to `api/requirements.in`
2. Regenerate `requirements.txt` using the Docker command above
3. Restart the API service: `./run-local.sh` or restart containers manually

## Troubleshooting

See the [troubleshooting guide](docs/troubleshooting.md) for solutions to common problems.
-   `bisq2-api` connection, Docker configuration, and more.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1.  Fork the repository
2.  Create your feature branch (`git checkout -b feature/amazing-feature`)
3.  Commit your changes (`git commit -m 'Add <descriptive message>'`)
4.  Push to the branch (`git push origin feature/amazing-feature`)
5.  Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [Bisq](https://bisq.network/) - The decentralized exchange
- [LangChain](https://langchain.com/) - For RAG implementation
- [FastAPI](https://fastapi.tiangolo.com/) - For the API framework
- [Next.js](https://nextjs.org/) - For the web frontend
