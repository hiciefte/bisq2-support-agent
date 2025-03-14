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
- Node.js 18+ (for web frontend development)
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
│   │   └── vectorstore/  # Vector embeddings storage
│   └── requirements.txt  # Python dependencies
├── web/                  # Next.js web frontend
├── docker/               # Docker configuration
│   ├── api/              # API service Dockerfile
│   ├── web/              # Web frontend Dockerfile
│   ├── prometheus/       # Prometheus configuration
│   ├── grafana/          # Grafana configuration
│   └── docker-compose.yml # Docker Compose configuration
├── docs/                 # Documentation
│   ├── bisq2-api-setup.md # Bisq 2 API setup guide
│   ├── faq-automation.md # FAQ automation guide
│   ├── troubleshooting.md # Troubleshooting guide
│   └── monitoring-security.md # Monitoring security guide
├── scripts/              # Utility scripts
└── .env.example          # Example environment variables
```

## Setup

### 1. Clone this repository:
```bash
git clone <repository-url>
cd <repository-directory>
```

### 2. Environment Configuration:

Create a `.env` file in the project root for Docker:

```bash
cp .env.example .env
```

Update the `.env` file with your OpenAI API key:

```
OPENAI_API_KEY=your_openai_api_key_here
```

### 3. Data Directory Structure:

**Important**: The project uses existing data directories that contain the necessary content for the RAG system. These directories should be preserved:

- `api/data/wiki/`: Contains Markdown files with documentation
- `api/data/vectorstore/`: Contains vector embeddings for the RAG system

For Docker, these directories are mounted into the container, so both local development and Docker setups use the same data.

If these directories don't exist or are empty, you may need to:
```bash
# Ensure the directories exist
mkdir -p api/data/wiki api/data/vectorstore

# Add content to the wiki directory (if needed)
# Example: cp your-documentation.md api/data/wiki/
```

## Deployment Options

### Local Development

For local development, use the `docker-compose.local.yml` file, which mounts the local data directory into the container:

```bash
# Run the local development environment
./run-local.sh
```

This configuration:
- Mounts the `api/data` directory to `/app/api/data` in the container
- Allows you to modify files locally and see changes immediately
- Is ideal for development and testing

### Cloud Deployment

For cloud deployment, use the standard `docker-compose.yml` file:

```bash
# Run the cloud deployment environment
./run-cloud.sh
```

This configuration:
- Copies the data directory into the container during the build process
- Does not mount local volumes for data (only for app code)
- Is more suitable for production environments

## Running with Docker

1. Start all services:
```bash
docker-compose up -d
```

2. Access the services:
   - Web interface: http://localhost:3000
   - API documentation: http://localhost:8000/docs
   - Prometheus: http://localhost:9090
   - Grafana: http://localhost:3001

## Development

### Environment Configuration for Local Development

When developing locally, each service needs its own environment configuration:

#### API Service:

Create a `.env` file in the `api` directory:

```bash
cp .env.example api/.env
```

**Important**: For local development, set the `DATA_DIR` to `data` (relative path) in the API's `.env` file:

```
DATA_DIR=data
```

This ensures the API service uses the `api/data` directory when running locally, while still working correctly in Docker.

### Running Services Individually

#### API Service:

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

3. Ensure you have a `.env` file in the api directory with the correct configuration:
   ```
   # OpenAI API key (required for the RAG service)
   OPENAI_API_KEY=your_api_key_here
   OPENAI_MODEL=o3-mini
   
   # Bisq API URL
   BISQ_API_URL=http://localhost:8082
   
   # Model Configuration
   EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
   
   # Debug mode
   DEBUG=true
   
   # Data paths - using relative path that works for both Docker and manual runs
   DATA_DIR=data
   VECTOR_STORE_PATH=vectorstore
   FAQ_OUTPUT_PATH=extracted_faq.jsonl
   SUPPORT_CHAT_EXPORT_PATH=support_chat_export.csv
   ```

4. Run the API service:
   ```bash
   python -m app.main
   ```

#### Web Frontend:

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
- **FAQ Data**: The system will automatically extract FAQ data from the wiki documents

When adding new content:
1. Add Markdown files to `api/data/wiki/` or add a MediaWiki XML dump file named `bisq_dump.xml` to the same directory
2. Restart the API service to rebuild the vector store
3. The system will automatically process and index the new content

### Using MediaWiki XML Dumps

The system supports loading content from MediaWiki XML dumps, which can be exported from any MediaWiki instance (including Wikipedia). To use this feature:

1. Export the XML dump from your MediaWiki instance
2. Name the file `bisq_dump.xml` and place it in the `api/data/wiki/` directory
3. Restart the API service to rebuild the vector store

The system will automatically load content from the XML dump, including page titles and sections, and use it for the RAG system.

### MediaWiki XML Namespace Issues

If you encounter namespace conflict warnings when processing an existing MediaWiki XML dump:

```
WARNING:mwxml.iteration.page:Namespace id conflict detected. <title>=File:Example.png, <namespace>=0, mapped_namespace=6
```

**Note**: The latest version of the `download_bisq2_media_wiki.py` script already handles namespaces correctly. This fix is only needed for existing XML files created with older versions of the download script.

You can fix these conflicts by running:

```bash
python3 scripts/fix_xml_namespaces.py
```

This script will fix namespace issues in your existing `api/data/wiki/bisq_dump.xml` file.

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
