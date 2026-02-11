# RAG Evaluation

This directory contains evaluation data and results for comparing the RAG retrieval system performance using realistic test data.

## Files

- `matrix_realistic_qa_samples_30_20260211.json` - Current curated 30-question benchmark set (mixed Matrix + Bisq2 export, 15x `multisig_v1`, 15x `bisq_easy`)
- `qdrant_realistic_evaluation.json` - Historical Qdrant evaluation result (latest agreed reference)
- `retrieval_strict.lock.json` - Canonical lockfile for reproducible benchmark runs
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

1. API service running with Qdrant backend (current runtime path):

   ```bash
   RETRIEVER_BACKEND=qdrant docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml up -d api qdrant
   ```

2. Qdrant collection populated:

   ```bash
   docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml exec api python -m app.scripts.rebuild_qdrant_index --force
   ```

### Running Evaluation

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml exec api python -m app.scripts.run_ragas_evaluation \
    --samples /data/evaluation/matrix_realistic_qa_samples_30_20260211.json \
    --output /data/evaluation/qdrant_realistic_evaluation.json \
    --backend qdrant
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

## Strict Reproducible Pipeline (Lockfile)

Use a lockfile to pin all inputs/options for future apples-to-apples runs.

### 1) Create lockfile once

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml exec api python -m app.scripts.retrieval_benchmark_harness lock \
    --output /data/evaluation/retrieval_strict.lock.json \
    --samples /data/evaluation/matrix_realistic_qa_samples_30_20260211.json \
    --backend qdrant \
    --run-name qdrant_strict \
    --output-dir /data/evaluation/benchmarks \
    --repeats 1 \
    --bypass-hooks escalation \
    --kb-manifest /data/evaluation/kb_snapshots/kb_2026_02_11/manifest.json \
    --ragas-timeout 60 \
    --ragas-max-retries 2 \
    --ragas-max-wait 10 \
    --ragas-max-workers 32 \
    --ragas-batch-size 8
```

### 2) Run using lockfile

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml exec api python -m app.scripts.retrieval_benchmark_harness run \
    --lock-file /data/evaluation/retrieval_strict.lock.json
```

`run --lock-file` enforces:
- sample file SHA256
- KB manifest SHA256 (if configured)
- expected runtime environment values (`OPENAI_MODEL`, `OPENAI_EMBEDDING_MODEL`, API key presence)
- API readiness (`/health` + probe query) before evaluation starts

It also writes a runtime manifest alongside summary results.

Compare two benchmark summaries:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.local.yml exec api python -m app.scripts.retrieval_benchmark_harness compare \
    --baseline /data/evaluation/benchmarks/qdrant_baseline.summary.json \
    --candidate /data/evaluation/benchmarks/qdrant_current.summary.json \
    --output /data/evaluation/benchmarks/qdrant_compare.json
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

- On older git states, `answer_relevancy` may still be 0.0/NaN due to legacy RAGAS/OpenAIEmbeddings compatibility. Current scripts pass embeddings explicitly to avoid that on current code.
- Keep the sample set and KB snapshot fixed when comparing git states; otherwise metric deltas are not comparable.

## Metrics In Documentation

Guideline for this repository:

- Store full metrics in machine-readable artifacts (`api/data/evaluation_results/*.json` and `api/data/evaluation/benchmarks/*.json`).
- Keep documentation focused on methodology and reproducibility, not raw per-run dumps.
- If needed, document only the latest **approved baseline summary** (single table with date + commit + key metrics), and link to the exact result artifact.
