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
export BISQ_SUPPORT_REPO_URL="<repository-url>"
export BISQ2_REPO_URL="<bisq2-repository-url>"
export BISQ_SUPPORT_INSTALL_DIR="/opt/bisq-support"
export BISQ2_INSTALL_DIR="/opt/bisq2"

# Optional environment variables
export BISQ_SUPPORT_SECRETS_DIR="/opt/bisq-support/secrets"
export BISQ_SUPPORT_LOG_DIR="/opt/bisq-support/logs"
export BISQ_SUPPORT_SSH_KEY_PATH="$HOME/.ssh/bisq2_support_agent"
```

3. Run the deployment script:
```bash
sudo ./scripts/deploy.sh
```

The deployment script will:
- Install required dependencies (Docker, git)
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

The RAG system uses documents from the following locations:

- **Wiki Documents**: Place Markdown files in `api/data/wiki/`
- **MediaWiki XML Dump**: Place a MediaWiki XML dump file named `bisq_dump.xml` in `api/data/wiki/`
- **FAQ Data**: The system will automatically extract FAQ data from the wiki documents

When adding new content:
1. Add Markdown files to `api/data/wiki/` or add a MediaWiki XML dump file
2. Restart the API service to rebuild the vector store
3. The system will automatically process and index the new content

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
