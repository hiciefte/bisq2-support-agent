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

### Prerequisites

- Docker and Docker Compose
- Git
- Python 3.11+
- Node.js 20+
- Java 17+ (for running the `bisq2-api` locally)
- An OpenAI API Key

### Environment Setup

1.  **Clone Repositories:**
    This project requires two repositories: the support agent itself and the `bisq2` application which provides the core API.

    ```bash
    # Clone the support agent
    git clone https://github.com/bisq-network/bisq2-support-agent.git
    cd bisq2-support-agent

    # Clone the bisq2 application (in the parent directory)
    git clone https://github.com/bisq-network/bisq2.git ../bisq2
    ```

2.  **Configure Environment Variables:**
    The project uses `.env` files for configuration. Start by copying the examples.

    ```bash
    # For the support agent services (API and Web)
    cp docker/.env.example docker/.env

    # For local Python development (if running API outside of Docker)
    cp api/.env.example api/.env
    ```

    Now, edit `docker/.env` and `api/.env` to add your `OPENAI_API_KEY`.

### Running the Full Stack with Docker (Recommended)

This is the easiest way to get started. It runs all services, including the `bisq2-api`, in a containerized environment.

1.  **Build the `bisq2-api`:**
    The `bisq2-api` Docker image needs to be built from the `bisq2` source code.

    ```bash
    # From the bisq2-support-agent directory
    docker build -t bisq2-api ../bisq2
    ```

2.  **Run the Local Environment:**
    Use the provided script to build and start all containers.

    ```bash
    # Make the script executable
    chmod +x ./run-local.sh

    # Build and start the local development environment
    ./run-local.sh
    ```

    This script uses `docker/docker-compose.local.yml`, which is configured for hot-reloading for the `web` and `api` services.

    Your services will be available at:
    - **Web App**: `http://localhost:3000`
    - **Support Agent API**: `http://localhost:8000`
    - **Bisq 2 API**: `http://localhost:8090` (from host) or `http://bisq2-api:8090` (from other containers)

### Running Services Individually (for Core Development)

If you need to work directly on the `api` or `web` services, you can run them as standalone processes. This requires running the `bisq2-api` manually.

#### Step 1: Run the `bisq2-api` Manually

The support agent needs to connect to the `bisq2-api`. For this to work, the `bisq2-api` must be configured to accept connections from outside its own process (i.e., bind to `0.0.0.0`).

1.  **Build the `bisq2-api`:**
    First, compile the Java application using Gradle.

    ```bash
    # From the bisq2-support-agent directory
    cd ../bisq2
    ./gradlew :http-api-app:installDist
    cd ../bisq2-support-agent
    ```

2.  **Create a Configuration Override:**
    The `bisq2-api` loads a `bisq.conf` file from its data directory to override default settings. We need to create this file to set the WebSocket host.

    ```bash
    # Create a data directory for the bisq2-api
    mkdir -p ../bisq2/data

    # Create the config override file
    cat > ../bisq2/data/bisq.conf << EOF
    application.websocket.server.host = "0.0.0.0"
    EOF
    ```
    This ensures the API is accessible to the support agent's API service.

3.  **Run the `bisq2-api`:**
    Execute the compiled application, pointing it to the data directory.

    ```bash
    # From the bisq2-support-agent directory
    ../bisq2/http-api-app/build/install/http-api-app/bin/http-api-app --data-dir=../bisq2/data
    ```
    The API will start and listen on `0.0.0.0:8090`.

#### Step 2: Run the Support Agent API

1.  **Set the `BISQ_API_URL`:**
    The support agent's API needs to know where the `bisq2-api` is. Edit `api/.env` and set the correct URL.

    ```bash
    # api/.env
    BISQ_API_URL=http://localhost:8090
    ```

2.  **Install Dependencies and Run:**
    From the `api` directory, install Python dependencies and run the server.

    ```bash
    cd api
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    pip install -r requirements.txt
    python -m uvicorn app.main:app --reload
    ```
    The API service will be available at `http://localhost:8000`.

#### Step 3: Run the Web Frontend

1.  **Set the API URL:**
    The web app needs to know where the support agent's API is. From the `web` directory, create a `.env.local` file.

    ```bash
    cd web
    echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
    ```

2.  **Install Dependencies and Run:**

    ```bash
    npm install
    npm run dev
    ```
    The web app will be available at `http://localhost:3000`.

## Development

### Updating Python Dependencies

To ensure the Python dependency lock file (`api/requirements.txt`) is consistent across all environments (local, CI, production), it must be generated within a Linux environment that mirrors production.

**To update `api/requirements.txt` after changing `api/requirements.in`, run this command from the project root:**

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml run --build --rm api pip-compile api/requirements.in -o api/requirements.txt --upgrade --no-strip-extras
```

This command runs `pip-compile` inside a temporary development container and saves the updated `api/requirements.txt` to your local filesystem. Commit both `api/requirements.in` (if changed) and the newly generated `api/requirements.txt`.

## Deployment

### Production Deployment

For production deployment on a cloud instance:

1.  Clone the repository:
    ```bash
    git clone <repository-url>
    cd bisq2-support-agent
    ```

2.  **Set up environment variables:**
    It is highly recommended to store environment variables in a dedicated, secured file, such as `/etc/bisq-support/deploy.env`.

    Create the directory and the file:
    ```bash
    sudo mkdir -p /etc/bisq-support
    sudo nano /etc/bisq-support/deploy.env
    ```

    Add the following content, replacing placeholders with your actual values:
    ```bash
    # /etc/bisq-support/deploy.env
    export BISQ_SUPPORT_REPO_URL="git@github.com:hiciefte/bisq2-support-agent.git"
    export BISQ2_REPO_URL="git@github.com:hiciefte/bisq2.git"
    export BISQ_SUPPORT_INSTALL_DIR="/opt/bisq-support"
    export BISQ2_INSTALL_DIR="/opt/bisq2"
    export ADMIN_API_KEY="your_secure_admin_key"
    export OPENAI_API_KEY="your_openai_api_key"
    export OPENAI_MODEL="o3-mini" # Or your preferred model
    # export BISQ_SUPPORT_SSH_KEY_PATH="/root/.ssh/bisq2_support_agent" # Optional
    ```

3.  **Source the environment file:**
    Load the variables into your current shell session.

    ```bash
    source /etc/bisq-support/deploy.env
    ```

4.  **Run the deployment script:**
    Make the script executable and run it with `sudo -E` to preserve the environment variables you just sourced.

    ```bash
    chmod +x ./scripts/deploy.sh
    sudo -E ./scripts/deploy.sh
    ```

The deployment script will install system dependencies, configure Docker, clone the required repositories, and start all services with health checks.

### Updating the Application

To update a production deployment to the latest version:

1.  **Log in** to your server.
2.  **Navigate** to the installation directory (e.g., `/opt/bisq-support`).
3.  **Load** your environment variables: `source /etc/bisq-support/deploy.env`.
4.  **(Optional) Use SSH Agent:** If your deployment key has a passphrase, start the agent (`eval $(ssh-agent -s)`) and add your key (`ssh-add ...`).
5.  **Run the update script:**
    ```bash
    sudo ./scripts/update.sh
    ```

The script will pull the latest code, rebuild containers if necessary, and restart services, with rollback capabilities on failure.

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

## Troubleshooting

If you encounter any issues, please refer to the [Troubleshooting Guide](docs/troubleshooting.md). It covers common problems with the API service, `bisq2-api` connection, Docker configuration, and more.

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
