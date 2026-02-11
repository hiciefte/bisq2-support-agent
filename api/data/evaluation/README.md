# RAG Evaluation

This directory contains evaluation data and results for comparing the RAG retrieval system performance using realistic test data.

## Files

- `matrix_realistic_qa_samples_30_20260211.json` - Current curated 30-question benchmark set (mixed Matrix + Bisq2 export, 15x `multisig_v1`, 15x `bisq_easy`)
- `matrix_realistic_qa_review_30_20260211.json` - Human review file and curation notes for the current 30-question benchmark set
- `qdrant_realistic_evaluation.json` - Historical Qdrant evaluation result (latest agreed reference)
- `kb_snapshots/` - Frozen knowledge-base snapshots (`wiki` + `faqs.db` + `bm25` inputs) for reproducible runs
- `benchmarks/` - Repeated-run benchmark outputs and A/B comparison reports (create as needed)

## Test Data Source

Current benchmark samples are curated from Matrix support chat plus Bisq2 support export, then reviewed before use. Samples are not derived from FAQ data, which avoids data leakage where test questions match indexed documents.

**Extraction script**: `api/app/scripts/extract_matrix_eval_samples.py`

## Samples vs Results

Important distinction:

- **Sample files** (input): list of `{question, ground_truth, metadata, ...}`
- **Evaluation files** (output): include computed `metrics` and `individual_results`

`qdrant_realistic_evaluation.json` is an **output artifact**, not a sample input file.

### About `contexts` in sample files

- For retrieval evaluation, sample `contexts` should be empty (or ignored).
- The evaluation script queries the live API and builds contexts from returned sources.
- Pre-populated sample contexts are **not** used as retrieval evidence in `run_ragas_evaluation`.

## Running Evaluation

### Freeze Knowledge Base (for reproducibility)

Before running benchmarks that you want to compare over time, snapshot retrieval inputs:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml exec api python -m app.scripts.manage_kb_snapshot create \
    --name kb_2026_02_11 \
    --note "Pre-benchmark frozen wiki+faq+bm25 inputs"
```

Restore and verify later:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml exec api python -m app.scripts.manage_kb_snapshot restore \
    --snapshot kb_2026_02_11

docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml exec api python -m app.scripts.manage_kb_snapshot verify \
    --snapshot kb_2026_02_11
```

After restore, rebuild the Qdrant index to ensure collection contents match the frozen sources.

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
    --samples /data/evaluation/matrix_realistic_qa_samples_30_20260211.json \
    --output /data/evaluation/[backend]_realistic_evaluation.json \
    --backend [chromadb|qdrant]
```

Recommended options for comparable retrieval evaluation:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml exec api python -m app.scripts.run_ragas_evaluation \
    --samples /data/evaluation/matrix_realistic_qa_samples_30_20260211.json \
    --output /data/evaluation/qdrant_realistic_eval_current.json \
    --backend qdrant \
    --bypass-hooks escalation \
    --ragas-timeout 60 \
    --ragas-max-retries 2 \
    --ragas-max-wait 10 \
    --ragas-max-workers 32 \
    --ragas-batch-size 8
```

## Repeated Benchmark Harness

Run repeated evaluation (reduces single-run variance):

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml exec api python -m app.scripts.retrieval_benchmark_harness run \
    --samples /data/evaluation/matrix_realistic_qa_samples_30_20260211.json \
    --backend qdrant \
    --run-name qdrant_current \
    --repeats 3 \
    --output-dir /data/evaluation/benchmarks \
    --bypass-hooks escalation \
    --kb-manifest /data/evaluation/kb_snapshots/kb_2026_02_11/manifest.json
```

Compare two benchmark summaries:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml exec api python -m app.scripts.retrieval_benchmark_harness compare \
    --baseline /data/evaluation/benchmarks/chromadb_initial.summary.json \
    --candidate /data/evaluation/benchmarks/qdrant_current.summary.json \
    --output /data/evaluation/benchmarks/chromadb_vs_qdrant.compare.json
```

The compare report includes:

- overall metric deltas
- protocol-slice metric deltas (if sample metadata has `protocol`)
- per-question faithfulness deltas
- gate checks for metric/latency regressions

### Extracting New Test Samples

To extract fresh Q&A pairs from support chat:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml exec api python -m app.scripts.extract_realistic_test_data \
    --max-samples 50 \
    --verbose
```

To extract a Bisq1-inclusive review set from Matrix export:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml exec api python -m app.scripts.extract_matrix_eval_samples \
    --input "/data/evaluation/matrix-export.json" \
    --output /data/evaluation/matrix_realistic_qa_samples_30_YYYYMMDD.json \
    --review-output /data/evaluation/matrix_realistic_qa_review_30_YYYYMMDD.json \
    --max-samples 30 \
    --bisq1-ratio 0.65
```

Review the generated `matrix_realistic_qa_review_*.json` before using the sample set for metrics.

## Notes

- The `answer_relevancy` metric consistently returns 0.0/NaN due to a RAGAS configuration issue with OpenAIEmbeddings
- Keep the sample set and KB snapshot fixed when comparing git states; otherwise metric deltas are not comparable.
