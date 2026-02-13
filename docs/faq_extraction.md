# FAQ Extraction Process Documentation

## Overview

The FAQ extraction process is a key component of the Bisq Support Agent system. It automatically generates Frequently Asked Questions (FAQs) from support chat conversations, which are then used to enhance the Retrieval-Augmented Generation (RAG) system's knowledge base.

This document explains how the FAQ extraction works, its architecture, configuration, and maintenance.

## Architecture

The FAQ extraction functionality is implemented through the following components:

1. **FAQService Class**: The core service responsible for loading, processing, and extracting FAQ data.
2. **extract_faqs.py Script**: A thin wrapper script that utilizes the FAQService to run the extraction process.
3. **Unified Training Scheduler**: The `scheduler` service triggers Bisq/Matrix sync endpoints that feed FAQ extraction.

### FAQService

Located in `api/app/services/faq_service.py`, this service handles:

- Loading and organizing messages from support chats
- Building conversation threads
- Extracting FAQs using OpenAI
- Managing processed conversation IDs
- Saving and loading FAQ data

### Extract FAQs Script

Located in `api/app/scripts/extract_faqs.py`, this script:

- Initializes the necessary services
- Runs the FAQ extraction process
- Logs the results and any errors

### Scheduler Integration

The `scheduler` service in Docker Compose periodically calls:

- `POST /admin/training/sync/bisq`
- `POST /admin/training/sync/matrix`

These endpoints run the unified training pipeline and persist extracted FAQ entries to `faqs.db`.

## Data Flow

The FAQ extraction process follows these steps:

1. **Data Collection**:
   - Fetch new support messages from Bisq and/or Matrix sources (depending on configured sync endpoint)
   - Combine with existing messages from previous runs

2. **Message Processing**:
   - Parse messages into structured objects
   - Track references between messages
   - Build conversation threads based on references

3. **Conversation Validation**:
   - Ensure conversations are complete and meaningful
   - Check for user and support messages
   - Verify time spans and message continuity

4. **FAQ Extraction**:
   - Filter out already processed conversations
   - Format conversations for the OpenAI API
   - Send batches to OpenAI for FAQ extraction
   - Parse responses into structured FAQ objects

5. **Data Storage**:
   - Save extracted FAQs to the SQLite database
   - Update the list of processed message IDs
   - Save all conversations for future reference

## Configuration

### Environment Variables

The FAQ extraction process relies on several environment variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `BISQ_API_URL` | URL to the Bisq API | `http://bisq2-api:8090` (Docker network) |
| `OPENAI_API_KEY` | API key for OpenAI | - |
| `OPENAI_MODEL` | OpenAI model to use | `openai:gpt-4o-mini` |
| `DATA_DIR` | Directory for storing data files | - |

### File Paths

The following file paths are used:

| Path | Description | Default Location |
|------|-------------|------------------|
| `FAQ_DB_PATH` | Path to the FAQ SQLite database | `{DATA_DIR}/faqs.db` |
| `CHAT_EXPORT_FILE_PATH` | Path to the support chat export CSV | `{DATA_DIR}/support_chat_export.csv` |
| `PROCESSED_CONVS_FILE_PATH` | Path to the processed conversations JSON | `{DATA_DIR}/processed_conversations.json` |
| `CONVERSATIONS_FILE_PATH` | Path to the conversations JSONL | `{DATA_DIR}/conversations.jsonl` |

## Running the Extraction Process

### Manual Execution

To manually run the FAQ extraction process for local development or testing, first ensure your local development environment is running. You can start it with the `run-local.sh` script.

Once the services are running, execute the following command from the project root. This command runs the extraction script inside the `api` service container, which has the correct environment and network access to connect to the `bisq2-api`.

```bash
# In the project root, this command executes the script inside the 'api' service container
docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml exec -- api python -m app.scripts.extract_faqs
```

### Scheduled Execution

In the production environment, the unified training sync runs via the `scheduler` service **every 12 hours** (`poll-matrix.sh`). This keeps FAQ data current from both Bisq and Matrix sources.

## Integration with RAG System

The extracted FAQs are integrated into the hybrid retrieval pipeline:

### Document Preparation
1. The `FAQService` loads FAQ data from SQLite (`faqs.db`) during initialization
2. Each FAQ is converted into a `Document` with metadata:
   - `type`: "faq"
   - `protocol`: "bisq_easy", "multisig_v1", or "all" (for version filtering)
   - `source_weight`: 1.0 (base weight)
3. Documents are embedded and indexed in the Qdrant hybrid collection

### Retrieval Integration
FAQs participate in the hybrid retrieval pipeline:
- **Semantic Search**: FAQ embeddings matched via dense vectors (weight: 0.6)
- **Keyword Search**: FAQ text indexed for BM25 sparse vectors (weight: 0.4)
- **Protocol Filtering**: FAQs filtered by protocol metadata based on query version detection

### Multi-Stage Retrieval
FAQs and wiki documents are retrieved together in protocol-prioritized stages:
- Stage 1: Protocol-specific content (e.g., `bisq_easy` for Bisq 2 queries)
- Stage 2: General content (`all` protocol) if insufficient results
- Stage 3: Cross-protocol fallback if needed

For full retrieval pipeline details, see [RAG Architecture](rag-architecture.md).

## Monitoring and Maintenance

### Logs

The FAQ extraction process logs detailed information about each step:

- Number of messages processed
- Number of conversations generated
- Number of new FAQs extracted
- Errors and warnings

These logs can be accessed via Docker:

```bash
docker compose -f docker/docker-compose.yml logs scheduler
```

### Common Issues and Solutions

1. **Connection to Bisq API fails**:
   - Verify the `BISQ_API_URL` environment variable is set to `http://bisq2-api:8090` (Docker network hostname)
   - Ensure the Bisq API service (`bisq2-api`) is running and healthy
   - Check Docker network connectivity between the `api` and `bisq2-api` containers
   - For local development outside Docker, use `http://localhost:8090` instead

2. **OpenAI API errors**:
   - Verify the `OPENAI_API_KEY` is valid
   - Check OpenAI API parameter changes (e.g., `max_tokens` vs `max_completion_tokens`)
   - Increase retry counts or delays for rate-limited requests

3. **No FAQs are extracted**:
   - Check if all conversations are already marked as processed
   - Clear the processed conversations file to force reprocessing
   - Verify the conversation validation logic isn't filtering out too many conversations

## Improving the FAQ Extraction

### Quality Improvements

To improve the quality of the extracted FAQs:

1. **Prompt Engineering** *(Implemented)*: Adjust the prompt used for OpenAI to improve extraction quality
2. **Filtering** *(In Progress)*: Add more sophisticated filtering of low-quality or duplicative FAQs
3. **Human Review** *(Under Consideration)*: Implement a review process for FAQs before adding them to the knowledge base

### Performance Improvements

For better performance:

1. **Batch Processing** *(Implemented)*: Adjust batch sizes for OpenAI requests
2. **Parallel Processing** *(In Progress)*: Implement parallel processing of conversation batches
3. **Caching** *(Under Investigation)*: Cache OpenAI responses to avoid redundant processing

## Conclusion

The FAQ extraction process is a critical component for keeping the support agent's knowledge base up-to-date with real user questions and expert answers. By automatically processing support chats into structured FAQs, it enables the RAG system to provide more accurate and relevant responses to user queries.
