# RAG Evaluation

This directory contains evaluation data and results for comparing the RAG retrieval system performance using realistic test data.

## Files

- `bisq2_realistic_qa_samples.json` - Realistic test samples extracted from Bisq 2 Support Chat (user questions + staff answers)
- `chromadb_realistic_baseline.json` - ChromaDB baseline RAGAS metrics with realistic questions
- `qdrant_realistic_evaluation.json` - Qdrant hybrid retriever RAGAS metrics with realistic questions

## Test Data Source

Test samples are extracted from actual Bisq 2 Support Chat conversations, not derived from FAQ data. This avoids data leakage where test questions match documents in the vector store.

**Extraction script**: `api/app/scripts/extract_realistic_test_data.py`

## Current Results (Realistic Questions)

| Metric | ChromaDB (Baseline) | Qdrant Hybrid | Improvement |
|--------|---------------------|---------------|-------------|
| context_precision | 0.4934 | 0.5081 | +2.98% |
| context_recall | 0.3333 | 0.3417 | +2.52% |
| faithfulness | 0.5030 | 0.5437 | +8.10% |
| answer_relevancy | 0.0 | 0.0 | (RAGAS bug) |
| avg_response_time | 3.63s | 4.63s | +27.5% slower |

## Running Evaluation

### Prerequisites

1. API service running with desired backend:

   ```bash
   # For ChromaDB (baseline):
   RETRIEVER_BACKEND=chromadb docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml up -d api

   # For Qdrant hybrid (new system):
   RETRIEVER_BACKEND=qdrant docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml up -d api qdrant
   ```

2. Qdrant collection populated (if using Qdrant):

   ```bash
   docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml exec api python -m app.scripts.migrate_to_qdrant
   ```

### Running Evaluation

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml exec api python -m app.scripts.run_ragas_evaluation \
    --samples /data/evaluation/bisq2_realistic_qa_samples.json \
    --output /data/evaluation/[backend]_realistic_evaluation.json \
    --backend [chromadb|qdrant]
```

### Extracting New Test Samples

To extract fresh Q&A pairs from support chat:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml exec api python -m app.scripts.extract_realistic_test_data \
    --max-samples 50 \
    --verbose
```

## Notes

- The `answer_relevancy` metric consistently returns 0.0/NaN due to a RAGAS configuration issue with OpenAIEmbeddings
- Realistic test questions reveal true system performance (~50% precision vs ~95% with FAQ-derived questions)
- Hybrid retrieval (Qdrant + BM25) shows modest but consistent improvement over semantic-only (ChromaDB)
