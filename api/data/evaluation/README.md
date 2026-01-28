# RAG Evaluation

This directory contains evaluation data and results for comparing the RAG retrieval system performance.

## Files

- `bisq_qa_baseline_samples.json` - Test samples with questions and ground truth answers
- `baseline_scores.json` - Baseline RAGAS metrics (ChromaDB backend)
- `new_scores.json` - New evaluation results (Qdrant backend, after migration)

## Running Evaluation

### Prerequisites

1. API service running with desired backend:

   ```bash
   # For ChromaDB (baseline):
   RETRIEVER_BACKEND=chromadb docker compose up -d api

   # For Qdrant (new system):
   RETRIEVER_BACKEND=qdrant docker compose up -d api qdrant
   ```

2. Qdrant collection populated (if using Qdrant):

   ```bash
   docker compose exec api python -m api.app.scripts.migrate_to_qdrant
   ```

### Recording Baseline

```bash
docker compose exec api python -m api.app.scripts.record_baseline_metrics \
    --samples api/data/evaluation/bisq_qa_baseline_samples.json \
    --output api/data/evaluation/baseline_scores.json
```

### Running New Evaluation

```bash
docker compose exec api python -m api.app.scripts.run_ragas_evaluation \
    --backend qdrant \
    --samples api/data/evaluation/bisq_qa_baseline_samples.json \
    --output api/data/evaluation/new_scores.json
```

### Comparing Results

```bash
docker compose exec api python -m api.app.scripts.compare_metrics \
    --baseline api/data/evaluation/baseline_scores.json \
    --new api/data/evaluation/new_scores.json \
    --detailed
```

## Target Metrics

From the RAG upgrade plan, the target improvements are:

| Metric | Baseline | Target |
|--------|----------|--------|
| Context Precision | 0.525 | 0.70 |
| Context Recall | 0.45 | 0.65 |
| Faithfulness | 0.49 | 0.65 |
| Answer Relevancy | 0.00 | 0.75 |

## Notes

- Baseline was recorded with 30 samples from verified FAQ data
- The `answer_relevancy` baseline of 0.00 may indicate an issue with the metric calculation
- Response time is also tracked as a secondary metric
