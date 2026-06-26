# RAG System Architecture

## Overview

The Bisq Support Agent uses a hybrid Retrieval Augmented Generation (RAG) pipeline with a Qdrant-backed index.

Core stages:

1. Query translation (multilingual support)
2. Pre-retrieval query rewriting (anaphoric resolution, entity substitution)
3. Protocol/version detection (Bisq Easy vs Bisq 1)
4. Multi-stage protocol filtering
5. Hybrid retrieval (dense + sparse/BM25)
6. Weighted fusion and deduplication
7. Optional ColBERT reranking
8. Context assembly and LLM generation

## Request Flow

```text
User Query
  -> Translation (if non-English)
  -> Query Rewriter (feature-flagged, enabled by default)
     ├─ Gate: needs rewrite? → no → pass through (0ms)
     ├─ Cache hit? → return cached (0ms)
     ├─ Track 1: Heuristic (pronoun resolution + entity substitution, <1ms)
     └─ Track 2: LLM rewrite (gpt-4o-mini, ~300ms)
  -> Protocol Detector
  -> Protocol-Aware Retrieval Stages
     -> Qdrant Dense Search
     -> Qdrant Sparse (BM25) Search
     -> Weighted Fusion (semantic + keyword)
  -> Deduplication
  -> Optional ColBERT Rerank
  -> Prompt Assembly
  -> LLM Response
```

## Main Components

### RAG Orchestration

- `api/app/services/simplified_rag_service.py`
- Loads wiki, FAQ, and internal LLM Wiki documents
- Rebuilds/validates Qdrant index via index manager
- Initializes retriever and response generation chain

### Pre-Retrieval Query Rewriting

- `api/app/services/rag/query_rewriter.py` - Two-track rewriter (heuristic + LLM)
- `api/app/services/rag/query_context.py` - Anaphoric detection and topic extraction
- `api/app/services/rag/bisq_entities.py` - Shared entity dictionary (DRY for ProtocolDetector + QueryRewriter)
- Resolves anaphoric follow-ups ("How do I do that?") using chat history context
- Substitutes informal terms ("old bisq" -> "Bisq 1", "escrow" -> "multisig escrow")
- Feature-flagged via `ENABLE_QUERY_REWRITE` (enabled by default)

### Protocol-Aware Retrieval Logic

- `api/app/services/rag/document_retriever.py`
- Applies staged protocol filters (`bisq_easy`, `multisig_v1`, `all`)
- Prioritizes relevant protocol content while preserving fallback behavior

### Hybrid Retriever

- `api/app/services/rag/qdrant_hybrid_retriever.py`
- Executes dense and sparse searches against Qdrant
- Applies weighted score fusion
- Handles filter translation and compatibility across qdrant-client versions

### Index Management

- `api/app/services/rag/qdrant_index_manager.py`
- Maintains index metadata and freshness checks
- Builds/rebuilds index from authoritative sources

### BM25 Sparse Vectors

- `api/app/services/rag/bm25_tokenizer.py`
- Produces sparse vectors used by Qdrant hybrid search
- Controlled by BM25 parameters and vocabulary file

## Data Sources

### Wiki

- Source: `api/data/wiki/processed_wiki.jsonl`
- Optional: `api/data/wiki/payment_methods_reference.jsonl`
- Metadata includes protocol tags used for filtering

### FAQ

- Source of truth: `api/data/faqs.db`
- Includes manually managed and pipeline-extracted FAQs

### Internal LLM Wiki

- Source: `api/data/knowledge/llm_wiki/pages/*.md`
- Loader: `api/app/services/rag/llm_wiki_loader.py`
- Purpose: compiled internal support knowledge derived from canonical docs, verified FAQs, and support evidence
- Only markdown files with `status: reviewed` or `status: active` and non-empty `source_refs` enter the RAG index
- Draft, proposed, and deprecated pages are ignored so AI-generated synthesis never becomes authoritative before review
- Admin-only sections such as `Review Notes` and `Last Change Summary` are stripped before indexing

Example frontmatter:

```yaml
---
id: bisq-easy-deposit-limits
title: Bisq Easy deposit limits
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: bisq_easy
reviewed_by: support-admin
reviewed_at: "2026-05-12"
risk_level: low
source_refs:
  - wiki:bisq-easy
  - faq:123
---
```

### Staff-Only Code Evidence

- Source: `{DATA_DIR}/code_knowledge/code_evidence.jsonl`
- Loader/retriever: `api/app/services/rag/code_evidence.py`
- Staff brief builder: `api/app/channels/staff_assist/grounding.py`
- Purpose: implementation-derived evidence for human support admins
- Boundary: only `audience=staff_only` records are retrieved, and only into `StaffAssistPayload.grounding_brief`
- Current status: code evidence is file-backed and not inserted into the public Qdrant collection
- Promotion path: durable facts must become reviewed LLM Wiki guidance before customer-facing use

See [Code Evidence Schema](code-evidence-schema.md).

## Configuration Reference

| Setting | Value / Default | Notes |
|---|---|---|
| `RETRIEVER_BACKEND` | app default: `qdrant` | Qdrant-only backend |
| `RETRIEVER_BACKEND` in Docker Compose | default: `qdrant` | Effective runtime default in local/prod compose runs |
| `HYBRID_SEMANTIC_WEIGHT` | `0.6` | Dense score contribution |
| `HYBRID_KEYWORD_WEIGHT` | `0.4` | Sparse/BM25 score contribution |
| `ENABLE_QUERY_REWRITE` | `True` | Pre-retrieval query rewriting |
| `QUERY_REWRITE_MODEL` | `openai:gpt-4o-mini` | LLM model for query rewriting |
| `QUERY_REWRITE_TIMEOUT_SECONDS` | `2.0` | Timeout for LLM rewrite |
| `QUERY_REWRITE_MAX_HISTORY_TURNS` | `4` | Max chat history turns for context |
| `ENABLE_COLBERT_RERANK` | app default: `false` | Compose default currently enables it (`true`) |
| `COLBERT_TOP_N` | `5` | Final docs retained after rerank |
| `LLM_WIKI_DIR_PATH` | `{DATA_DIR}/knowledge/llm_wiki/pages` | Internal LLM Wiki page directory |
| `BM25_K1` | `1.5` | BM25 term frequency saturation |
| `BM25_B` | `0.75` | BM25 document length normalization |

## Storage

- Qdrant vectors: Docker volume `bisq2-qdrant-data`
- BM25 vocabulary: `api/data/bm25_vocabulary.json` (runtime generated)
- Qdrant index metadata: `api/data/qdrant_index_metadata.json` (runtime generated)

## Evaluation References

For reproducible retrieval evaluation, use:

- `api/data/evaluation/matrix_realistic_qa_samples_30_20260211.json`
- `api/data/evaluation/kb_snapshots/`
- `api/data/evaluation/retrieval_strict.lock.json`
- `api/app/scripts/retrieval_benchmark_harness.py`

## Related Documentation

- `README.md`
- `docs/environment-configuration.md`
- `api/data/evaluation/README.md`
