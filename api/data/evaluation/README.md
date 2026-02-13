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

### Baseline Comparison (2026-02-11)

These are the currently available comparison runs across the three requested git states (30 samples each):

| State | Commit | Backend | Artifact | Faithfulness | Answer Relevancy | Context Precision | Context Recall |
|---|---|---|---|---:|---:|---:|---:|
| Chroma-only baseline | `7c75417` | chromadb | `api/data/evaluation_results/chromadb_7c75417_ragas30_fixed.json` | 0.3884 | 0.0000 | 0.5594 | 0.2222 |
| Initial Qdrant setup | `824b7b8` | qdrant | `api/data/evaluation_results/qdrant_824b7b8_ragas30.json` | 0.4545 | 0.0000 | 0.5474 | 0.2500 |
| Current setup | `efa7bae` | qdrant | `api/data/evaluation_results/qdrant_efa7bae_ragas30.json` | 0.4199 | 0.5785 | 0.6422 | 0.3889 |
| Soul personality layer | `d5f7ad4` | qdrant | `api/data/evaluation/qdrant_soul_layer_evaluation.json` | 0.6374 | 0.8434 | 0.6425 | 0.4389 |

### Soul Layer Impact Analysis (2026-02-13)

The soul personality layer (`soul_default.md`) injects a cypherpunk-aligned identity and communication style into the system prompt. Error messages were centralized into `api/app/prompts/error_messages.py` with voice-consistent wording. Response length guidelines were relaxed from a rigid "2-3 sentences maximum" to context-dependent length.

| Metric | Baseline (`efa7bae`) | Soul Layer | Delta | Change |
|--------|----:|----:|----:|---:|
| Faithfulness | 0.4199 | 0.6374 | +0.2175 | +52% |
| Answer Relevancy | 0.5785 | 0.8434 | +0.2649 | +46% |
| Context Precision | 0.6422 | 0.6425 | +0.0003 | ~0% |
| Context Recall | 0.3889 | 0.4389 | +0.0500 | +13% |

Key observations:
- **Faithfulness (+52%)**: "Lead with the answer" and "no filler" directives ground responses better in retrieved context.
- **Answer Relevancy (+46%)**: Direct answer-first style without preambles aligns response content more tightly with the question.
- **Context Precision (flat)**: Retrieval pipeline unchanged — expected result.
- **Context Recall (+13%)**: Flexible length guidelines allow more thorough answers that reference more ground truth.

No regressions detected. All metrics improved or held steady.

Notes:
- The two Qdrant artifacts above still contain `"system": "chromadb"` due to a legacy label in the older evaluation script output; backend attribution here follows the run setup and artifact naming.
- `answer_similarity` and `answer_correctness` are `null` in these runs and therefore excluded from the summary table.
