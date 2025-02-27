# Bisq 2 Support Assistant

A RAG-based support assistant for Bisq 2, providing automated support through a chat interface.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview

This project consists of the following components:

- **API Service**: FastAPI-based backend implementing the RAG (Retrieval Augmented Generation) system
- **Web Frontend**: Next.js web application for the chat interface
- **Bisq Integration**: Connection to Bisq 2 API
- **Monitoring**: Prometheus and Grafana for system monitoring

## Prerequisites

- Docker and Docker Compose installed
- OpenAI API key (for the RAG model)
- Python 3.11+ (for local development)
- Node.js 18+ (for web frontend development)

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
│   ├── bisq/             # Bisq API Dockerfile
│   ├── prometheus/       # Prometheus configuration
│   ├── grafana/          # Grafana configuration
│   └── docker-compose.yml # Docker Compose configuration
├── prometheus/           # Prometheus configuration
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
   OPENAI_MODEL=o1-mini
   
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
- **FAQ Data**: The system will automatically extract FAQ data from the wiki documents

When adding new content:
1. Add Markdown files to `api/data/wiki/`
2. Restart the API service to rebuild the vector store
3. The system will automatically process and index the new content

## Troubleshooting

### Common Issues:

1. **Missing or Empty Data Directories**: If the RAG system isn't working properly, check that:
   ```bash
   # Verify the wiki directory contains Markdown files
   ls -la api/data/wiki/
   
   # If empty, add some documentation files
   cp your-documentation.md api/data/wiki/
   ```

2. **Environment Variables**: Check that your `.env` files contain all required variables.

3. **OpenAI API Key**: Verify your OpenAI API key is valid and has sufficient quota.

4. **Docker Networking**: If services can't communicate, check Docker network settings.

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
