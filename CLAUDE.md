# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Local Development
```bash
# Start entire local environment (only command needed for development)
./run-local.sh

# Restart API after code changes
docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml restart api

# View logs
docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml logs -f

# Stop local environment
docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml down
```

### Python API Development
```bash
# Lint and format Python code
cd api
black .
isort .
mypy .

# Run tests
pytest
pytest-asyncio

# Install dependencies (if not using Docker)
pip install -r requirements.txt

# Update requirements.txt (use Docker for cross-platform compatibility)
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml run --build --rm api pip-compile api/requirements.in -o api/requirements.txt --upgrade --no-strip-extras

# For enhanced supply-chain security (optional, adds complexity):
# docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml run --build --rm api pip-compile --generate-hashes api/requirements.in -o api/requirements.txt --upgrade --no-strip-extras
```

### Web Frontend Development
```bash
cd web
npm run dev      # Development server
npm run build    # Production build
npm run lint     # ESLint check
npm start        # Production start
```

### Production Management (on server)
```bash
# Deploy to production server
curl -sSL https://raw.githubusercontent.com/bisq-network/bisq2-support-agent/main/scripts/deploy.sh | sudo bash

# Start/stop/restart production services (run from /opt/bisq-support/scripts/)
./start.sh
./stop.sh
./restart.sh

# Update application with rollback capability
./update.sh
```

## Project Architecture

### High-Level Structure
This is a RAG-based support assistant with three main components:
- **API Service**: FastAPI backend with RAG (Retrieval Augmented Generation) system
- **Web Frontend**: Next.js React application
- **Bisq Integration**: WebSocket connection to Bisq 2 API for real-time support data

### API Service (Python/FastAPI)
- **Entry Point**: `api/app/main.py` - FastAPI application with service initialization
- **RAG System**: `api/app/services/simplified_rag_service.py` - Core RAG logic using ChromaDB and LangChain
- **Data Sources**:
  - Wiki documents (`api/data/wiki/`) processed by `wiki_service.py`
  - FAQ data extracted from support chats via `faq_service.py`
- **Routes**: Organized in `api/app/routes/` (chat, admin, feedback, health)
- **Configuration**: Environment-based settings in `api/app/core/config.py`

### Knowledge Base Content Flow
1. **Wiki Processing**: MediaWiki XML dumps → processed by `process_wiki_dump.py` → stored in `api/data/wiki/`
2. **FAQ Extraction**: Support chat conversations → processed by `extract_faqs.py` → stored as JSONL
3. **Vector Store**: Content is embedded and stored in ChromaDB (`api/data/vectorstore/`)
4. **RAG Integration**: Queries retrieve relevant context from both wiki and FAQ sources

### Web Frontend (Next.js/TypeScript)
- **Component Architecture**: Uses Radix UI components with Tailwind CSS
- **State Management**: React hooks for chat interface
- **API Integration**: Communicates with FastAPI backend via nginx proxy
- **API URL Resolution**: Uses `http://${hostname}:8000/api` in production (proxied by nginx)
- **Local Development**: Direct API access via `NEXT_PUBLIC_API_URL=http://localhost:8000`

### Docker Environment
- **Local Development**: Uses `docker-compose.local.yml` with hot-reloading and direct API port exposure (8000:8000)
- **Production**: Uses `docker-compose.yml` with nginx reverse proxy (no direct API exposure)
- **Services**: nginx (reverse proxy), api, web, prometheus, grafana, bisq2-api

#### Nginx Routing Configuration
- **Public API Routes**: `/api/` (general), `/api/admin/faqs`, `/api/admin/feedback`, `/api/admin/auth/`
- **Internal-Only Routes**: All other `/api/admin/` endpoints (restricted to 127.0.0.1 and Docker networks)
- **Rate Limiting**: Different zones for API (5r/s), admin (3r/s), web (20r/s), static (30r/s)
- **Local vs Production**: Local development bypasses nginx restrictions via direct API access

### Bisq Integration
- **WebSocket Client**: `api/app/integrations/bisq_websocket.py` connects to Bisq 2 API
- **Support Chat Data**: Real-time ingestion of support conversations for FAQ extraction
- **API Integration**: `api/app/integrations/bisq_api.py` for HTTP-based interactions

## Development Environment

### Prerequisites
- Docker and Docker Compose
- Python 3.11+ (for local API development)
- Node.js 20+ (for local web development)
- Java 17+ (for Bisq 2 API integration)

### Environment Configuration
- **Local**: Environment variables in `docker/.env` (created by `run-local.sh` if missing)
- **Production**: Environment file at `/etc/bisq-support/deploy.env`
- **Required Variables**: `OPENAI_API_KEY`, `ADMIN_API_KEY`, `XAI_API_KEY` (optional)

#### Post-Deployment Configuration (Production)
After deploying to a server, you must configure CORS to access the admin interface:

1. **Edit CORS settings**: Update `/opt/bisq-support/docker/.env`
   ```bash
   # Change this line to include your server IP/domain:
   CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://YOUR_SERVER_IP

   # For HTTPS (recommended for production):
   CORS_ORIGINS=https://yourdomain.com,http://localhost:3000
   ```

2. **Restart services**: Run `./restart.sh` from `/opt/bisq-support/scripts/`

3. **Access admin interface**: Navigate to `http://YOUR_SERVER_IP/admin` and use the `ADMIN_API_KEY` value to log in

**Common Issues:**
- **403 Forbidden on /admin**: CORS_ORIGINS doesn't include your access URL
- **Admin login fails**: Verify ADMIN_API_KEY matches the value in the .env file
- **Cookie issues with Tor/.onion**: Set `COOKIE_SECURE=false` in .env file for HTTP/Tor deployments

### Code Style and Quality
- **Python**: Black (formatting), isort (imports), mypy (type checking)
- **TypeScript**: Prettier (formatting), ESLint (linting), strict TypeScript config
- **Style Guide**: Detailed formatting standards in `STYLE_GUIDE.md`
- **Cursor Rules**: Python-specific guidelines in `.cursor/rules/project-rule.mdc`

### Data Management
- **Data Directory**: `api/data/` contains wiki content, vector store, feedback, and FAQs
- **Volume Mounts**: Data persisted in Docker volumes for development
- **RAG Updates**: Restart API service to rebuild vector store after content changes

#### FAQ Management System
- **Admin Interface**: Web-based FAQ management at `/admin/manage-faqs`
- **Features**: Complete CRUD operations with pagination and comprehensive filtering
- **Filtering Options**:
  - Text search across questions and answers
  - Category filtering with clickable badges
  - Source filtering (Manual, Extracted, etc.)
  - Combined filters with visual indicators
- **Backend Implementation**:
  - Pagination: `api/app/services/faq_service.py:get_faqs_paginated()`
  - Filtering: `_apply_filters()` helper method supports text, category, and source filters
  - API Endpoint: `/admin/faqs` with query parameters for pagination and filtering
- **Frontend Components**: Uses shadcn/ui components (Badge, Select, Card) for modern UI
- **Data Flow**: FAQ changes trigger automatic reindexing in the vector store for RAG system

### Monitoring
- **Metrics**: Prometheus metrics exposed at `/metrics` endpoint
- **Health Checks**: `/health` and `/healthcheck` endpoints
- **Logging**: Structured JSON logging with python-json-logger
- **Grafana**: Dashboard for system monitoring (local and production)

## Important Notes

### Build and Test Requirements
- Always build Docker image and test locally before committing
- Run linting and type checking before pushing changes
- Use `./run-local.sh` for comprehensive local testing

## Commit Message Guidelines

Follow these seven core rules for writing good commit messages (based on https://cbea.ms/git-commit/):

1. **Separate subject from body with a blank line**
2. **Limit subject line to 50 characters**
3. **Capitalize the subject line**
4. **Do not end the subject line with a period**
5. **Use imperative mood in the subject line**
6. **Wrap body text at 72 characters**
7. **Use the body to explain "what" and "why", not "how"**
8. **Remove Claude Code attribution from commit messages before pushing**

### Subject Line Test
The subject line should complete this sentence: "If applied, this commit will _[subject line]_"

### Example Format
```
Fix authentication bug in user login

Users were unable to log in due to a validation error in the
password hashing function. The bcrypt comparison was using the
wrong salt parameter, causing all login attempts to fail.

This commit corrects the salt parameter and adds unit tests to
prevent regression.
```
- As you navigate and work through the repository do not forget to update the CLAUDE.md file with valuable information that will help you increase your understanding of the codebase
- remember if GitHub Actions errors occur because of an outdated requirements.txt check the section Updating Python Dependencies in the README.md to see how to create the requirements.txt properly