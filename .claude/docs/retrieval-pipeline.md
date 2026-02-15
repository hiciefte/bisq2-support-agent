# RAG Retrieval Pipeline

## Overview

The Bisq Support Agent uses a **three-layer hybrid retrieval pipeline** combining metadata filtering, keyword search (BM25), and semantic search (embeddings) with weighted score fusion.

```
User Query
    ↓
Translation (if non-English)
    ↓
Query Rewriter (ENABLE_QUERY_REWRITE, default: on)
    ├─ Gate: needs rewrite? → no → pass through (0ms)
    ├─ Cache hit? → return cached (0ms)
    ├─ Track 1: Heuristic (pronoun resolution + entity substitution, <1ms)
    └─ Track 2: LLM rewrite (gpt-4o-mini, ~300ms)
    ↓
Version Detection → Bisq Easy or Bisq 1?
    ↓
Stage 1: Protocol-specific retrieval (k=6)
    ↓
Stage 2: General content if needed (k=4)
    ↓
Stage 3: Cross-protocol fallback (k=2)
    ↓
Hybrid Fusion: 70% semantic + 30% keyword
    ↓
Deduplication by title:type
    ↓
Optional ColBERT reranking (top 5)
    ↓
Context Assembly → LLM Generation
```

## 0. Pre-Retrieval Query Rewriting

**Location**: `api/app/services/rag/query_rewriter.py`

Resolves ambiguous follow-up queries before they reach the retrieval pipeline. Without this, queries like "How do I do that?" produce empty BM25 tokens and semantically meaningless embeddings.

### Two-Track Strategy

| Track | Method | Latency | Cost | Trigger |
|-------|--------|---------|------|---------|
| Heuristic | Pronoun resolution + entity substitution | <1ms | $0 | Anaphoric pronouns detected |
| LLM | Context-aware rewrite via gpt-4o-mini | ~300ms | ~$0.00004 | Short queries or follow-up phrases |

### Gate Logic

The rewriter skips queries that don't need rewriting:
- No chat history → pass through
- Self-contained queries (>12 words, contains "bisq", no pronouns) → pass through
- Short queries (<5 words) with history → rewrite
- Anaphoric references (it, that, this, those, they) → rewrite

### Shared Entity Dictionary

**Location**: `api/app/services/rag/bisq_entities.py`

Single source of truth for informal-to-canonical entity mappings, consumed by:
- **ProtocolDetector**: Keyword lists for version routing
- **QueryRewriter**: Heuristic entity substitution + LLM prompt examples

Examples: "old bisq" -> "Bisq 1", "escrow" -> "multisig escrow (Bisq 1)", "reputation score" -> "Bisq Easy reputation score"

### Configuration

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `ENABLE_QUERY_REWRITE` | `True` | Feature flag |
| `QUERY_REWRITE_MODEL` | `openai:gpt-4o-mini` | LLM model for Track 2 |
| `QUERY_REWRITE_TIMEOUT_SECONDS` | `2.0` | LLM timeout (falls back gracefully) |
| `QUERY_REWRITE_MAX_HISTORY_TURNS` | `4` | Max chat history turns for context |

## 1. Metadata Filtering (Protocol Prioritization)

**Location**: `api/app/services/rag/document_retriever.py` (lines 58-223)

### Protocol Categories

Documents are tagged with protocol metadata:
- `bisq_easy` - Bisq 2/Bisq Easy content (primary for most users)
- `multisig_v1` - Bisq 1 multisig protocol content
- `musig` - Future MuSig protocol (reserved)
- `all` - Protocol-agnostic, general content

### Multi-Stage Retrieval Strategy

**For Bisq Easy queries (default):**

| Stage | Filter | k | Trigger Condition |
|-------|--------|---|-------------------|
| 1 (Primary) | `protocol="bisq_easy"` | 6 | Always runs first |
| 2 (Secondary) | `protocol="all"` | 4 | If total docs < 4 |
| 3 (Fallback) | `protocol="multisig_v1"` | 2 | If total docs < 3 |

**For Bisq 1/Multisig queries:**

| Stage | Filter | k | Trigger Condition |
|-------|--------|---|-------------------|
| 1 (Primary) | `protocol="multisig_v1"` | 4 | Always runs first |
| 2 (Secondary) | `protocol="all"` | 2 | If total docs < 3 |
| 3 | *(skipped)* | - | Explicitly avoids bisq_easy |

**Rationale**: Users get protocol-specific answers first, general content second, cross-protocol content only as last resort to avoid confusion.

## 2. Keyword Search (BM25)

**Location**: `api/app/services/rag/bm25_tokenizer.py` (lines 175-469)

### BM25 Configuration

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `K1` | 1.5 | Term frequency saturation (standard default) |
| `B` | 0.75 | Document length normalization (75% effect) |

### Token Processing Pipeline

```
Raw Query
    ↓ lowercase
    ↓ regex extraction
Tokenized
    ↓ stopword filtering (125 common words removed)
    ↓ remove tokens < 3 chars
    ↓ filter pure numbers
    ↓ filter Bitcoin addresses
Clean Tokens
    ↓
Vocabulary Lookup → Unknown tokens handled gracefully
    ↓
Token Indices + IDF Weights → Sparse Vector
```

### IDF Calculation

```
IDF(token) = log((N - df + 0.5) / (df + 0.5) + 1)
```

Where:
- `N` = total documents in collection
- `df` = documents containing the token

**Effect**: Rare technical terms (like "multisig", "bisq") get higher weights; common words get lower weights.

### Security Limits

| Limit | Value | Purpose |
|-------|-------|---------|
| `MAX_VOCABULARY_SIZE` | 500,000 | Prevent memory exhaustion |
| `MAX_INPUT_SIZE` | 1,000,000 chars | Prevent malicious inputs |

## 3. Semantic Search (Vector Similarity)

**Location**: `api/app/services/simplified_rag_service.py` (lines 520-526)

### Embedding Configuration

| Parameter | Value | Location |
|-----------|-------|----------|
| Model | `text-embedding-3-small` | `config.py:91` |
| Dimensions | 1536 | Standard for OpenAI embeddings |
| Distance Metric | Cosine similarity | ChromaDB default |

### ChromaDB Settings

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `k` | 8 | Balance diversity and relevance |
| `score_threshold` | 0.3 | ~73° angle; filters obvious non-matches |

### Similarity Score Interpretation

- **1.0**: Identical content
- **0.8+**: Very similar (near paraphrase)
- **0.6-0.8**: Similar topic
- **0.3-0.6**: Somewhat related
- **< 0.3**: Filtered out (irrelevant)

## 4. Hybrid Fusion Pipeline

**Location**: `api/app/services/rag/qdrant_hybrid_retriever.py` (lines 351-455)

### Fusion Architecture

```
Dense Search (k×3 candidates)     Sparse Search (k×3 candidates)
         ↓                                  ↓
   Cosine Scores                       BM25 Scores
         ↓                                  ↓
   Min-Max Normalize                Min-Max Normalize
         ↓                                  ↓
         └──────────────┬──────────────────┘
                        ↓
          Weighted Combination:
    score = (0.7 × dense) + (0.3 × sparse)
                        ↓
              Sort → Take top k
```

### Default Weights

| Weight | Value | Rationale |
|--------|-------|-----------|
| `HYBRID_SEMANTIC_WEIGHT` | 0.7 | Semantic understanding captures paraphrasing |
| `HYBRID_KEYWORD_WEIGHT` | 0.3 | Exact terms catch technical terminology |

**Location**: `config.py:133-134`

### Why k×3 Candidates?

Fetching 3× candidates compensates for ranking disagreement between dense and sparse methods before merging. This ensures adequate coverage when combining two independent ranking lists.

### Normalization Strategy

```python
normalized[id] = (score - min_score) / (max_score - min_score)
```

- Handles "all scores equal" edge case by returning 1.0
- Makes scores from different algorithms directly comparable
- Allows weights to meaningfully control balance

## 5. Complete Hyperparameter Reference

### Retrieval Pipeline Parameters

| Parameter | Value | Location | Rationale |
|-----------|-------|----------|-----------|
| `ENABLE_QUERY_REWRITE` | `True` | config.py:134 | Pre-retrieval query rewriting |
| `QUERY_REWRITE_MODEL` | `openai:gpt-4o-mini` | config.py:135 | LLM model for rewrite Track 2 |
| `QUERY_REWRITE_TIMEOUT_SECONDS` | `2.0` | config.py:136 | LLM rewrite timeout |
| `QUERY_REWRITE_MAX_HISTORY_TURNS` | `4` | config.py:137 | Max chat history context |
| `RETRIEVER_BACKEND` | `"chromadb"` | config.py:119 | Default; lower ops overhead than Qdrant |
| `ChromaDB k` | 8 | simplified_rag_service.py:522 | Diversity before deduplication |
| `score_threshold` | 0.3 | simplified_rag_service.py:523 | Filter obvious mismatches |
| `HYBRID_SEMANTIC_WEIGHT` | 0.7 | config.py:133 | Primary: semantic meaning |
| `HYBRID_KEYWORD_WEIGHT` | 0.3 | config.py:134 | Secondary: exact terms |
| `BM25_K1` | 1.5 | bm25_tokenizer.py:175 | Standard term saturation |
| `BM25_B` | 0.75 | bm25_tokenizer.py:176 | Standard length normalization |
| `COLBERT_TOP_N` | 5 | config.py:129 | Final reranked count |
| `ENABLE_COLBERT_RERANK` | True | config.py:130 | Optional fine-grained reranking |
| `MAX_CONTEXT_LENGTH` | 15000 | config.py:114 | ~11K tokens for LLM context |
| `MAX_CHAT_HISTORY_LENGTH` | 10 | config.py:111 | Conversation memory limit |

### Multi-Stage Retrieval Parameters

| Stage | Bisq Easy Query | Bisq 1 Query | Purpose |
|-------|-----------------|--------------|---------|
| Stage 1 k | 6 (bisq_easy) | 4 (multisig_v1) | Primary protocol content |
| Stage 2 threshold | < 4 docs | < 3 docs | Trigger general backfill |
| Stage 2 k | 4 (all) | 2 (all) | Supplement with general knowledge |
| Stage 3 threshold | < 3 docs | N/A | Last resort trigger |
| Stage 3 k | 2 (fallback) | N/A | Minimal cross-protocol |

### Threshold Rationale

- **< 4 docs for Stage 2**: 4 documents is practical minimum for well-rounded context
- **< 3 docs for Stage 3**: 3 documents is hard minimum for reasonable answer generation
- **k=8 base**: More candidates for subsequent deduplication and filtering

## 6. Backend Options

### ChromaDB (Default)

```yaml
RETRIEVER_BACKEND: "chromadb"
```

- **Pros**: Simple setup, good for single-node deployments
- **Cons**: No native hybrid search (dense only)

### Qdrant (Optional)

```yaml
RETRIEVER_BACKEND: "qdrant"
QDRANT_HOST: "qdrant"
QDRANT_PORT: 6333
QDRANT_COLLECTION: "bisq_docs"
```

- **Pros**: Native hybrid search, better scalability
- **Cons**: Additional infrastructure

### Hybrid Mode

```yaml
RETRIEVER_BACKEND: "hybrid"
```

Uses Qdrant for hybrid search with ChromaDB fallback.

## 7. Deduplication

**Location**: `simplified_rag_service.py:1006-1007`

After retrieval, documents are deduplicated by `title:type` key to prevent redundant FAQ entries from inflating result count.

## 8. Optional ColBERT Reranking

**Location**: `config.py:128-130`

```yaml
ENABLE_COLBERT_RERANK: True
COLBERT_MODEL: "colbert-ir/colbertv2.0"
COLBERT_TOP_N: 5
```

When enabled:
1. Initial retrieval returns top candidates
2. ColBERT reranker performs fine-grained token-level matching
3. Final top 5 documents selected for context

**Rationale**: ColBERT provides better precision through late interaction, but adds latency. Lazy-loaded only when enabled.

## 9. Related Documentation

- **Knowledge Base System**: `.claude/docs/knowledge-base.md`
- **RAG Architecture (Detailed)**: `docs/rag-architecture.md`
- **Environment Configuration**: `.claude/docs/environment-config.md`
