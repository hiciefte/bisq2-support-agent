# RAG System Architecture

## Overview

The Bisq Support Agent uses a **hybrid RAG (Retrieval Augmented Generation)** system combining:

1. **Metadata Filtering**: Protocol-based document prioritization (Bisq Easy vs Bisq 1)
2. **Keyword Search**: BM25 sparse vector search for exact term matching
3. **Semantic Search**: Dense vector embeddings for meaning-based retrieval
4. **Weighted Fusion**: Configurable combination of keyword and semantic scores

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                          User Query                                  │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Version Detection                                 │
│              (Bisq Easy / Bisq 1 / Unknown)                         │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                Multi-Stage Protocol Filtering                        │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │ Stage 1: Primary │→ │ Stage 2: General │→ │ Stage 3: Fallback│  │
│  │ protocol-specific│  │ if < 4 docs      │  │ if < 3 docs      │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Hybrid Search                                   │
│  ┌─────────────────────────┐    ┌─────────────────────────────┐    │
│  │   Semantic Search       │    │     Keyword Search          │    │
│  │   (Dense Vectors)       │    │     (BM25 Sparse)           │    │
│  │   Weight: 0.7           │    │     Weight: 0.3             │    │
│  └─────────────────────────┘    └─────────────────────────────┘    │
│                    │                        │                       │
│                    └──────────┬─────────────┘                       │
│                               ▼                                     │
│                    Min-Max Normalization                            │
│                               ▼                                     │
│                    Weighted Score Fusion                            │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│              Deduplication & Optional ColBERT Reranking             │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Context Assembly                                  │
│              (Wiki docs + FAQs → Prompt)                            │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    LLM Generation                                    │
│              (AISuite → OpenAI gpt-4o-mini)                         │
└─────────────────────────────────────────────────────────────────────┘
```

## Key Components

### 1. Document Retriever

**Location**: `api/app/services/rag/document_retriever.py`

Implements multi-stage retrieval with protocol filtering:

```python
# Bisq Easy Query Flow
Stage 1: filter={"protocol": "bisq_easy"}, k=6
Stage 2: filter={"protocol": "all"}, k=4 (if total < 4)
Stage 3: filter={"protocol": "multisig_v1"}, k=2 (if total < 3)
```

### 2. BM25 Tokenizer

**Location**: `api/app/services/rag/bm25_tokenizer.py`

Sparse vector search with:
- K1 = 1.5 (term frequency saturation)
- B = 0.75 (document length normalization)
- 125-word stopword list
- IDF weighting: `log((N - df + 0.5) / (df + 0.5) + 1)`

### 3. Qdrant Hybrid Retriever

**Location**: `api/app/services/rag/qdrant_hybrid_retriever.py`

True hybrid search combining dense and sparse vectors:

```python
combined_score = (0.7 × normalized_dense) + (0.3 × normalized_sparse)
```

### 4. Prompt Manager

**Location**: `api/app/services/rag/prompt_manager.py`

Manages system prompts, chat history formatting, and context assembly.

### 5. LLM Provider

**Location**: `api/app/services/rag/llm_provider.py`

AISuite wrapper for OpenAI API with configurable temperature and token limits.

## Configuration Reference

### Core Settings (`config.py`)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `RETRIEVER_BACKEND` | `"chromadb"` | Backend: chromadb, qdrant, hybrid |
| `HYBRID_SEMANTIC_WEIGHT` | 0.7 | Dense vector weight |
| `HYBRID_KEYWORD_WEIGHT` | 0.3 | Sparse vector weight |
| `ENABLE_COLBERT_RERANK` | True | Enable ColBERT reranking |
| `COLBERT_TOP_N` | 5 | Final documents after rerank |
| `MAX_CONTEXT_LENGTH` | 15000 | Max context chars for LLM |
| `MAX_CHAT_HISTORY_LENGTH` | 10 | Conversation memory |

### Embedding Settings

| Parameter | Default | Description |
|-----------|---------|-------------|
| `OPENAI_EMBEDDING_MODEL` | `"text-embedding-3-small"` | Embedding model |
| `EMBEDDING_DIMENSIONS` | 1536 | Vector dimensions |
| `EMBEDDING_PROVIDER` | `"openai"` | Provider (openai, cohere, voyage) |

### BM25 Settings

| Parameter | Default | Description |
|-----------|---------|-------------|
| `BM25_K1` | 1.5 | Term frequency saturation |
| `BM25_B` | 0.75 | Length normalization |
| `BM25_VOCABULARY_FILE` | `"bm25_vocabulary.json"` | Vocabulary storage |

## Protocol Metadata

Documents are tagged with protocol for filtering:

| Protocol Value | Display Name | Content Type |
|----------------|--------------|--------------|
| `bisq_easy` | Bisq Easy (Bisq 2) | Reputation-based trading |
| `multisig_v1` | Multisig v1 (Bisq 1) | 2-of-2 multisig trading |
| `musig` | MuSig | Future protocol (reserved) |
| `all` | General | Cross-protocol content |

## Data Sources

### Wiki Documents
- **Location**: `api/data/wiki/processed_wiki.jsonl`
- **Type**: `"wiki"`
- **Source Weight**: 1.1

### FAQ Documents
- **Location**: `api/data/faqs.db` (SQLite)
- **Type**: `"faq"`
- **Source Weight**: 1.0

## ChromaDB Vector Store

**Location**: `api/data/vectorstore/`

Settings:
- k = 8 candidates per query
- score_threshold = 0.3 (cosine similarity)
- Distance metric: cosine

## Current Limitations

1. **No Confidence Scoring**: All answers returned immediately without confidence-based routing
2. **ChromaDB Single Node**: No horizontal scaling for vector store
3. **No Query Expansion**: Single query without reformulation

## Related Documentation

- **Retrieval Pipeline Details**: `.claude/docs/retrieval-pipeline.md`
- **Knowledge Base System**: `.claude/docs/knowledge-base.md`
- **Environment Configuration**: `.claude/docs/environment-config.md`
