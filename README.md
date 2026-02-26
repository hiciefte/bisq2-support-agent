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

If you want Dockerized support-agent services to use a manually started Bisq2 headless API on the host:

```bash
BISQ_API_URL=http://host.docker.internal:8090 ./run-local.sh
```

Important: the Bisq2 API process must be reachable from Docker (bind host `0.0.0.0`, not only `127.0.0.1`).

If the Bisq2 API runs with `authorizationRequired=true`, enable authenticated support-agent access:

```bash
BISQ_API_AUTH_ENABLED=true
# Either provide existing client credentials...
BISQ_API_CLIENT_ID=...
BISQ_API_CLIENT_SECRET=...
# ...or provide pairing bootstrap input:
# BISQ_API_PAIRING_CODE_ID=...
# BISQ_API_PAIRING_QR_FILE=/path/to/pairing_qr_code.txt
```

Note: the current Bisq2 permission mapping must include `/api/v1/support/*` for fully authorized support export/send.

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

After deployment, you must configure the following settings in `/opt/bisq-support/docker/.env`:

1. **CORS Settings** - Required to access the admin interface:
   ```bash
   # Update CORS_ORIGINS to include your server IP/domain:
   CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://YOUR_SERVER_IP
   ```

2. **Privacy and Security Settings** (recommended for GDPR compliance):
   ```bash
   # Data retention period in days (default: 30)
   DATA_RETENTION_DAYS=30

   # Enable privacy-preserving features (recommended for production)
   ENABLE_PRIVACY_MODE=true

   # Enable PII detection in logs to prevent logging sensitive data
   PII_DETECTION_ENABLED=true

   # Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
   LOG_LEVEL=INFO
   ```

3. **Cookie Security** - For Tor/.onion deployments:
   ```bash
   # Set to false for HTTP/Tor deployments (default: true for HTTPS)
   COOKIE_SECURE=false
   ```

4. **Security Headers** (enabled by default in production):
   - The production deployment uses `docker/nginx/conf.d/default.prod.conf` with security headers enabled
   - Headers include: CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy
   - Configuration is automatically applied via `docker-compose.yml`
   - **No additional setup required** - security headers work out of the box

5. **Restart services** after making changes:
   ```bash
   cd /opt/bisq-support/scripts/
   ./restart.sh
   ```

6. **Access admin interface**: Navigate to `http://YOUR_SERVER_IP/admin` and use the `ADMIN_API_KEY` from the `.env` file

#### Optional: Tor Hidden Service Deployment

To expose the application as a Tor hidden service (.onion address) for private, censorship-resistant access:

**This is completely optional** - the application works perfectly without Tor configuration.

📖 **See the complete guide**: [Tor Hidden Service Deployment](docs/tor-deployment.md)

Quick overview:
- Install Tor daemon on the host system
- Configure hidden service in `/etc/tor/torrc`
- Add `.onion` address to `TOR_HIDDEN_SERVICE` environment variable
- Set `COOKIE_SECURE=false` for .onion deployments
- Restart services

The guide includes:
- ✅ Step-by-step deployment instructions
- ✅ Security hardening configuration
- ✅ Backup and recovery procedures
- ✅ Monitoring and troubleshooting
- ✅ Automated security testing

#### Managing the Application

Once deployed, the production application should be managed using the following scripts located in `/opt/bisq-support/scripts/`:

-   **`start.sh`**: Starts the application containers using the production configuration.
-   **`stop.sh`**: Stops and removes the application containers.
-   **`restart.sh`**: Performs a graceful stop followed by a start.
-   **`cleanup_old_data.sh`**: Cleans up personal data older than `DATA_RETENTION_DAYS` (GDPR compliance).

These scripts are location-aware and source their configuration from a production environment file (`/etc/bisq-support/deploy.env`). They should not be used for local development.

**Note**: If you encounter "Permission denied" errors when running scripts, ensure they are executable:
```bash
chmod +x /opt/bisq-support/scripts/*.sh
```

#### Automated Data Cleanup (Privacy Compliance)

To automatically clean up personal data on production servers, set up a cron job:

```bash
# Edit root crontab
sudo crontab -e

# Add this line to run cleanup daily at 2 AM
0 2 * * * /opt/bisq-support/scripts/cleanup_old_data.sh >> /var/log/bisq-data-cleanup.log 2>&1
```

The cleanup script:
- Removes raw chat data older than `DATA_RETENTION_DAYS` (default: 30 days)
- Preserves anonymized FAQs permanently
- Respects the `ENABLE_PRIVACY_MODE` setting
- Can be run manually with `--dry-run` flag to preview deletions

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
-   `feedback.db`: SQLite database storing user feedback (automatically created on first run).
-   `faqs.db`: SQLite database storing FAQs (authoritative source, automatically created on first run).
-   `bm25_vocabulary.json`: BM25 vocabulary used by the hybrid retriever (runtime-generated).
-   `qdrant_index_metadata.json`: Qdrant index build metadata (runtime-generated).

These are automatically created during deployment. For local development, create the wiki directory if needed: `mkdir -p api/data/wiki`.

### Feedback Storage Migration

The feedback system has been migrated from JSONL files to SQLite for better data integrity and query performance:

-   **SQLite Database**: `api/data/feedback.db` - Primary feedback storage (automatically created)
-   **Database Schema**: Includes tables for feedback entries, conversation history, metadata, and issues
-   **Migration**: Existing JSONL feedback files can be migrated using `python -m app.scripts.migrate_feedback_to_sqlite`
-   **Permissions**: The database file must be writable by the API container user (UID 1001, the `bisq-support` user in production). If you encounter permission errors, fix ownership with: `sudo chown 1001:1001 api/data/feedback.db`

For new deployments, no migration is needed - the database will be created automatically on first startup.

## Support Agent Configuration

The FAQ extraction system needs to identify which users in the support chat are official support agents. This is configured using the `SUPPORT_AGENT_NICKNAMES` environment variable.

### Setting Up Support Agent Detection

Add support agent nicknames to your environment configuration:

```bash
# Single support agent
SUPPORT_AGENT_NICKNAMES=suddenwhipvapor

# Multiple support agents (comma-separated)
SUPPORT_AGENT_NICKNAMES=suddenwhipvapor,strayorigin,toruk-makto
```

**Important Notes:**
- **Required for FAQ extraction**: If not configured, no messages will be marked as support messages
- **No fallback behavior**: The system will NOT automatically detect support agents if this is not configured
- **Case-sensitive**: Nicknames must match exactly as they appear in the support chat
- **Comma-separated**: Use commas to separate multiple nicknames (no spaces recommended)

### How Support Detection Works

When processing support chat conversations:
1. Messages from configured nicknames are marked as support messages
2. Support messages are used to identify Q&A conversations for FAQ extraction
3. Only conversations with both user questions and support answers are extracted as FAQs

If `SUPPORT_AGENT_NICKNAMES` is not configured:
- ❌ No messages will be marked as support messages
- ❌ No FAQs will be extracted from conversations
- ⚠️ The system will operate normally for answering questions, but won't learn from new support chats

## RAG System Content

The RAG system uses a **hybrid retrieval pipeline** combining:
- **Metadata Filtering**: Protocol-based prioritization (Bisq Easy vs Bisq 1)
- **Keyword Search**: BM25 sparse vectors for exact term matching
- **Semantic Search**: Dense vector embeddings for meaning-based retrieval
- **Weighted Fusion**: 60% semantic + 40% keyword scoring (configurable via `HYBRID_SEMANTIC_WEIGHT`/`HYBRID_KEYWORD_WEIGHT`)

### Retrieval Pipeline

```
User Query → Version Detection → Multi-Stage Protocol Filtering
    → Hybrid Search (Semantic 60% + Keyword 40%)
    → Deduplication → Optional ColBERT Reranking
    → Context Assembly → LLM Generation
```

**Key Parameters**:
- Qdrant hybrid retrieval (dense + sparse vectors) with protocol-aware staged filtering
- BM25 with K1=1.5, B=0.75
- Embedding model: `text-embedding-3-small` (1536 dimensions)
- Hybrid weighting defaults: semantic 0.6 + keyword 0.4

For detailed architecture, see [RAG Architecture](docs/rag-architecture.md).

### 1. Wiki Documents
-   **Location**: `api/data/wiki/`
-   **Purpose**: Primary knowledge base with structured Bisq 1/2 documentation
-   **Processing**: XML dumps → `process_wiki_dump.py` → JSONL with metadata
-   **Source Weight**: 1.1 (slightly higher than FAQs)
-   **Protocol Tagging**: Documents auto-categorized as `bisq_easy`, `multisig_v1`, or `all`

**Metadata Structure**:
```json
{
  "title": "Document Title",
  "category": "bisq2|bisq1|general",
  "type": "wiki",
  "source_weight": 1.1,
  "protocol": "bisq_easy|multisig_v1|all"
}
```

### 2. FAQ Data
-   **Storage**: SQLite database (`api/data/faqs.db`) - authoritative source
-   **Extraction**: Automatic from support chat via Training Pipeline
-   **Manual Addition**: Admin interface at `/admin/manage-faqs`
-   **Source Weight**: 1.0

### Multi-Stage Protocol Filtering

For **Bisq Easy queries** (default):
| Stage | Filter | k | Trigger |
|-------|--------|---|---------|
| 1 | `protocol="bisq_easy"` | 6 | Always |
| 2 | `protocol="all"` | 4 | If < 4 docs |
| 3 | `protocol="multisig_v1"` | 2 | If < 3 docs |

For **Bisq 1 queries**:
| Stage | Filter | k | Trigger |
|-------|--------|---|---------|
| 1 | `protocol="multisig_v1"` | 4 | Always |
| 2 | `protocol="all"` | 2 | If < 3 docs |

### Content Processing

When the API service starts, it processes wiki and FAQ sources, then ensures the Qdrant hybrid index is up to date (Qdrant data persists in the Docker volume `bisq2-qdrant-data`).

```bash
# Add new wiki content
cp your_document.md api/data/wiki/
docker compose -f docker/docker-compose.yml restart api
```

For FAQ extraction details, see [FAQ Extraction Documentation](docs/faq_extraction.md).

## Monitoring and Security

The project includes Prometheus and Grafana for monitoring.
-   **Prometheus**: Collects metrics from the API and web services.
-   **Grafana**: Provides dashboards for visualizing metrics.

For details on securing these services, see the [Monitoring Security Guide](docs/monitoring-security.md).

## Development

### Code Quality and Pre-commit Hooks

This project uses pre-commit hooks to automatically enforce code quality standards. The hooks run before each commit to check formatting, imports, types, and tests.

**Setting up pre-commit hooks:**

```bash
# Install pre-commit (if not already installed)
cd api
pip install pre-commit

# Install the git hooks
pre-commit install

# (Optional) Run hooks on all files to verify setup
pre-commit run --all-files
```

**What runs on each commit:**

- ✅ **black** - Python code formatting
- ✅ **isort** - Import sorting
- ✅ **mypy** - Type checking
- ✅ **flake8** - Code linting
- ✅ **pytest** - Fast tests (non-slow tests only)
- ✅ File checks (trailing whitespace, end-of-file, YAML/JSON syntax)

**Bypassing hooks (use sparingly):**

```bash
# Skip all hooks for a single commit (only when necessary)
git commit --no-verify -m "Emergency fix"
```

**Note:** The same checks run in CI, so bypassing hooks locally will cause CI failures.

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
- [AISuite](https://github.com/andrewyng/aisuite) - For unified LLM interface
- [LangChain](https://langchain.com/) - For RAG infrastructure (embeddings and vector stores)
- [FastAPI](https://fastapi.tiangolo.com/) - For the API framework
- [Next.js](https://nextjs.org/) - For the web frontend
