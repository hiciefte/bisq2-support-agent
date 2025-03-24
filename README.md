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
│   ├── nginx/            # Nginx configuration for production
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
└── run-local.sh, run-cloud.sh # Deployment scripts
```

## Setup

### 1. Clone this repository:
```bash
git clone <repository-url>
cd <repository-directory>
```

### 2. Environment Configuration:

Create `.env` files in the appropriate directories:

#### For Docker:
```bash
# Copy the example file
cp docker/.env.example docker/.env

# Edit with your settings
nano docker/.env
```

Required variables for Docker:
```
# OpenAI API key (required for the RAG service)
OPENAI_API_KEY=your_api_key_here

# Admin API key for protected endpoints
ADMIN_API_KEY=your_admin_key_here

# Grafana credentials (for monitoring)
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=securepassword
```

#### For Local API Development:
```bash
# Copy the example file
cp api/.env.example api/.env

# Edit with your settings
nano api/.env
```

### 3. Data Directory Structure:

**Important**: The project uses existing data directories that contain the necessary content for the RAG system. These directories should be preserved:

- `api/data/wiki/`: Contains Markdown files with documentation
- `api/data/vectorstore/`: Contains vector embeddings for the RAG system
- `api/data/feedback/`: Stores user feedback in monthly files

For Docker, these directories are mounted into the container, so both local development and Docker setups use the same data.

If these directories don't exist or are empty, you may need to:
```bash
# Ensure the directories exist
mkdir -p api/data/wiki api/data/vectorstore api/data/feedback

# Add content to the wiki directory (if needed)
# Example: cp your-documentation.md api/data/wiki/
```

## Deployment Options

### Production Deployment

For production deployment, use the standard docker configuration:

```bash
# Build and start the production environment
./run-cloud.sh
```

This configuration:
- Uses a two-stage build process for the web frontend to ensure proper module resolution
- Sets up Nginx as a reverse proxy for the web frontend
- Configures monitoring with Prometheus and Grafana
- Includes scheduled tasks for FAQ updates and feedback processing
- Is optimized for production use with proper resource limits and environment settings

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
- Provides a simplified setup without Nginx, Prometheus, or Grafana

## Docker Configuration Details

### Web Frontend

The project uses two different Dockerfiles for the web frontend:

1. **Production (Dockerfile)**:
   - Two-stage build process to ensure proper module resolution
   - First stage installs dependencies and builds the Next.js application
   - Second stage only includes the built artifacts
   - Configured for optimal production performance

2. **Development (Dockerfile.dev)**:
   - Single-stage build optimized for development
   - Mounts local directories for real-time code changes
   - Enables hot reloading for immediate feedback during development

### API Service

The API service Dockerfile:
- Uses a multi-stage build to minimize image size
- Installs dependencies in a builder stage
- Copies only necessary files to the final image
- Configures proper data directories for the RAG system

## Running Services Individually

### API Service:

1. Create and activate a virtual environment:
   ```bash
   # Navigate to API directory
   cd api
   
   # Create a virtual environment
   python -m venv venv
   
   # Activate the virtual environment
   # On macOS/Linux:
   source venv/bin/activate
   # On Windows:
   # venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Ensure you have a `.env` file in the api directory:
   ```bash
   # If you haven't already created it
   cp .env.example .env
   # Edit as needed
   nano .env
   ```

4. Run the API service:
   ```bash
   python -m uvicorn app.main:app --reload
   ```

### Web Frontend:

1. Navigate to web directory:
   ```bash
   cd web
   ```

2. Install Node.js dependencies:
   ```bash
   npm install
   ```

3. Start the development server:
   ```bash
   npm run dev
   ```

## Adding Content for the RAG System

The RAG system uses documents from the following locations:

- **Wiki Documents**: Place Markdown files in `api/data/wiki/`
- **MediaWiki XML Dump**: Place a MediaWiki XML dump file named `bisq_dump.xml` in `api/data/wiki/` to load content from a MediaWiki export
- **FAQ Data**: The system will automatically extract FAQ data from the wiki documents and Bisq support chats

When adding new content:
1. Add Markdown files to `api/data/wiki/` or add a MediaWiki XML dump file named `bisq_dump.xml` to the same directory
2. Restart the API service to rebuild the vector store
3. The system will automatically process and index the new content

### Using MediaWiki XML Dumps

The system supports loading content from MediaWiki XML dumps, which can be exported from any MediaWiki instance (including Wikipedia). To use this feature:

1. Export the XML dump from your MediaWiki instance
2. Name the file `bisq_dump.xml` and place it in the `api/data/wiki/` directory
3. Restart the API service to rebuild the vector store

## Automated FAQ Extraction

The project includes automated FAQ extraction from Bisq support chats:

1. The FAQ extractor connects to the Bisq 2 API to fetch support chat conversations
2. It processes these conversations to generate frequently asked questions and answers
3. The extracted FAQs are added to the RAG system's knowledge base

## Monitoring and Security

The project includes Prometheus and Grafana for monitoring:

- **Prometheus**: Collects metrics from the API and web services
- **Grafana**: Provides dashboards for visualizing the metrics

For details on securing these services, see [Monitoring Security Guide](docs/monitoring-security.md).

## Troubleshooting

If you encounter any issues with the Bisq 2 Support Agent, please refer to the [Troubleshooting Guide](docs/troubleshooting.md). Common issues covered include:

- API service errors
- Bisq API connection issues
- Docker configuration problems
- FAQ extractor issues
- Monitoring setup problems

For detailed solutions and step-by-step instructions, see the [Troubleshooting Guide](docs/troubleshooting.md).

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
