"""
BM25 Sparse Vector Tokenizer for Qdrant Hybrid Search.

This module provides a vocabulary-based tokenizer that creates sparse vectors
for BM25-style keyword matching in Qdrant hybrid search.

Key Features:
- Deterministic vocabulary-based indexing (no hash collisions)
- Proper TF-IDF weighting with corpus statistics
- Stopword removal for efficiency
- Alignment between document indexing and query tokenization
- Serializable vocabulary for persistence

Usage:
    tokenizer = BM25SparseTokenizer()

    # Index documents
    for doc in documents:
        indices, values = tokenizer.tokenize_document(doc.content)

    # Query
    query_indices, query_values = tokenizer.tokenize_query("search terms")
"""

import json
import logging
import math
import re
import threading
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Common English stopwords
STOPWORDS: Set[str] = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "he",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "was",
    "were",
    "will",
    "with",
    "this",
    "they",
    "but",
    "have",
    "had",
    "what",
    "when",
    "where",
    "who",
    "which",
    "why",
    "how",
    "all",
    "each",
    "every",
    "both",
    "few",
    "more",
    "most",
    "other",
    "some",
    "such",
    "no",
    "nor",
    "not",
    "only",
    "own",
    "same",
    "so",
    "than",
    "too",
    "very",
    "can",
    "just",
    "should",
    "now",
    "i",
    "you",
    "your",
    "my",
    "we",
    "our",
    "me",
    "him",
    "her",
    "them",
    "their",
    "do",
    "does",
    "did",
    "if",
    "then",
    "else",
    "also",
    "about",
    "into",
    "over",
    "after",
    "before",
    "between",
    "under",
    "again",
    "further",
    "once",
    "here",
    "there",
    "any",
    "being",
    "during",
    "through",
    "while",
    "above",
    "below",
    "up",
    "down",
    "out",
    "off",
    "am",
    "been",
    "because",
    "until",
    "against",
    "would",
    "could",
    "might",
    "must",
    "shall",
}

# Regex pattern for Bitcoin addresses (to filter them out)
BITCOIN_ADDRESS_PATTERN = re.compile(
    r"^(bc1|[13])[a-zA-HJ-NP-Z0-9]{25,39}$", re.IGNORECASE
)

# Pattern to match alphanumeric tokens with optional version numbers
TOKEN_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9]*[0-9]*|[a-zA-Z0-9]+")


class BM25SparseTokenizer:
    """BM25-style sparse vector tokenizer for Qdrant hybrid search.

    This tokenizer creates sparse vectors using vocabulary-based indexing
    and proper TF-IDF/BM25 weighting for improved keyword matching.

    Attributes:
        token_to_index: Mapping from tokens to unique indices
        document_frequencies: Count of documents containing each token
        num_documents: Total number of indexed documents
        avg_doc_length: Average document length for BM25 normalization
    """

    # BM25 parameters
    K1 = 1.5  # Term frequency saturation parameter
    B = 0.75  # Document length normalization parameter

    # Security limits to prevent DoS attacks
    MAX_VOCABULARY_SIZE = 500_000  # Maximum number of unique tokens
    MAX_INPUT_SIZE = 1_000_000  # Maximum input text size in characters (1MB)

    def __init__(self, corpus: Optional[List[str]] = None):
        """Initialize the tokenizer.

        Args:
            corpus: Optional list of documents to build initial vocabulary
        """
        self._token_to_index: Dict[str, int] = {}
        self._index_to_token: Dict[int, str] = {}
        self._document_frequencies: Counter = Counter()
        self._num_documents: int = 0
        self._total_doc_length: int = 0
        self._next_index: int = 0

        # Thread safety lock for vocabulary updates (RLock for reentrant access)
        self._update_lock = threading.RLock()

        # Build vocabulary from corpus if provided
        if corpus:
            self._build_vocabulary_from_corpus(corpus)

    def _build_vocabulary_from_corpus(self, corpus: List[str]) -> None:
        """Build vocabulary and IDF statistics from corpus.

        Args:
            corpus: List of document texts
        """
        for doc in corpus:
            tokens = self._extract_tokens(doc)
            unique_tokens = set(tokens)

            # Update document frequencies
            for token in unique_tokens:
                self._document_frequencies[token] += 1
                if token not in self._token_to_index:
                    self._add_token_to_vocabulary(token)

            self._num_documents += 1
            self._total_doc_length += len(tokens)

    def _add_token_to_vocabulary(self, token: str) -> int:
        """Add a token to the vocabulary if not already present.

        Thread-safe: acquires _update_lock to make check-and-insert atomic.
        Enforces MAX_VOCABULARY_SIZE limit to prevent unbounded growth.

        Args:
            token: Token to add

        Returns:
            Index of the token in vocabulary, or -1 if vocabulary is at limit
        """
        with self._update_lock:
            if token not in self._token_to_index:
                # Enforce vocabulary size limit
                if len(self._token_to_index) >= self.MAX_VOCABULARY_SIZE:
                    logger.warning(
                        f"Vocabulary at limit ({self.MAX_VOCABULARY_SIZE}), "
                        f"rejecting new token: {token[:20]}..."
                    )
                    return -1

                idx = self._next_index
                self._token_to_index[token] = idx
                self._index_to_token[idx] = token
                self._next_index += 1
                return idx
            return self._token_to_index[token]

    def _validate_input_size(self, text: str) -> None:
        """Validate input text size to prevent memory exhaustion.

        Args:
            text: Input text to validate

        Raises:
            ValueError: If input exceeds MAX_INPUT_SIZE
        """
        if text and len(text) > self.MAX_INPUT_SIZE:
            raise ValueError(
                f"Input size ({len(text)} chars) exceeds maximum allowed "
                f"({self.MAX_INPUT_SIZE} chars)"
            )

    def _extract_tokens(self, text: str) -> List[str]:
        """Extract tokens from text with preprocessing.

        Args:
            text: Input text

        Returns:
            List of cleaned, filtered tokens

        Raises:
            ValueError: If input exceeds MAX_INPUT_SIZE
        """
        if not text:
            return []

        # Validate input size
        self._validate_input_size(text)

        # Lowercase
        text = text.lower()

        # Extract alphanumeric tokens
        raw_tokens = TOKEN_PATTERN.findall(text)

        # Filter and clean tokens
        tokens = []
        for token in raw_tokens:
            # Skip very short tokens
            if len(token) < 2:
                continue

            # Skip stopwords
            if token in STOPWORDS:
                continue

            # Skip Bitcoin addresses
            if BITCOIN_ADDRESS_PATTERN.match(token):
                continue

            # Skip pure numbers (but keep alphanumeric like "bisq2")
            if token.isdigit():
                continue

            tokens.append(token)

        return tokens

    def _get_idf(self, token: str) -> float:
        """Calculate IDF (Inverse Document Frequency) for a token.

        Uses smoothed IDF formula: log((N - df + 0.5) / (df + 0.5) + 1)

        Args:
            token: Token to calculate IDF for

        Returns:
            IDF score (always positive)
        """
        if self._num_documents == 0:
            return 1.0  # Default IDF when no corpus

        df = self._document_frequencies.get(token, 0)
        if df == 0:
            # Unseen token - assign high IDF (rare)
            # Use smoothed IDF: log(N + 1) + 1 to ensure positive value
            return math.log(self._num_documents + 1) + 1

        # BM25 IDF formula
        idf = math.log((self._num_documents - df + 0.5) / (df + 0.5) + 1)

        # Ensure positive IDF
        return max(idf, 0.1)

    def _get_avg_doc_length(self) -> float:
        """Get average document length for BM25 normalization.

        Returns:
            Average document length (tokens per document)
        """
        if self._num_documents == 0:
            return 100.0  # Default assumption
        return self._total_doc_length / self._num_documents

    def tokenize(self, text: str) -> Tuple[List[int], List[float]]:
        """Tokenize text into sparse vector format.

        This is the main entry point for tokenization, suitable for
        both documents and queries.

        Args:
            text: Input text to tokenize

        Returns:
            Tuple of (indices, values) for Qdrant SparseVector
        """
        return self.tokenize_document(text)

    def tokenize_document(self, text: str) -> Tuple[List[int], List[float]]:
        """Tokenize a document for indexing.

        Note: This method has side effects - it updates vocabulary, document
        frequencies, and corpus statistics (_num_documents, _total_doc_length).
        Each call is treated as indexing a new document. All mutations are
        performed atomically under a lock to ensure thread safety.

        Args:
            text: Document text

        Returns:
            Tuple of (indices, values) for Qdrant SparseVector
        """
        tokens = self._extract_tokens(text)

        if not tokens:
            return [], []

        # Count term frequencies
        term_counts = Counter(tokens)
        doc_length = len(tokens)
        avg_length = self._get_avg_doc_length()

        indices = []
        values = []

        # Thread-safe vocabulary and corpus statistics update
        with self._update_lock:
            # Track which tokens we've already incremented DF for in this document
            # (term_counts already gives us unique tokens per document)
            for token, count in term_counts.items():
                # Add to vocabulary if new
                idx = self._add_token_to_vocabulary(token)

                # Skip token if vocabulary is at limit (-1 returned)
                if idx == -1:
                    continue

                # Increment document frequency once per document for each token
                self._document_frequencies[token] = (
                    self._document_frequencies.get(token, 0) + 1
                )

                # Calculate BM25 weight
                tf = count
                idf = self._get_idf(token)

                # BM25 TF component with length normalization
                numerator = tf * (self.K1 + 1)
                denominator = tf + self.K1 * (
                    1 - self.B + self.B * doc_length / avg_length
                )
                bm25_weight = idf * (numerator / denominator)

                indices.append(idx)
                values.append(float(bm25_weight))

            # Update corpus statistics
            self._num_documents += 1
            self._total_doc_length += doc_length

        return indices, values

    def tokenize_query(self, text: str) -> Tuple[List[int], List[float]]:
        """Tokenize a query for searching.

        Tokens not in the vocabulary are added for query-side expansion,
        allowing the query to potentially match future documents containing
        these terms.

        Args:
            text: Query text

        Returns:
            Tuple of (indices, values) for Qdrant SparseVector
        """
        tokens = self._extract_tokens(text)

        if not tokens:
            return [], []

        # Count term frequencies
        term_counts = Counter(tokens)

        indices = []
        values = []

        for token, count in term_counts.items():
            # Get or create vocabulary entry for token
            if token not in self._token_to_index:
                # Add unknown tokens for query-side vocabulary expansion
                idx = self._add_token_to_vocabulary(token)
                # Skip if vocabulary is at limit
                if idx == -1:
                    continue
            else:
                idx = self._token_to_index[token]

            # Simple TF-IDF weight for queries (no length normalization)
            tf = 1 + math.log(count) if count > 1 else 1.0
            idf = self._get_idf(token)
            weight = tf * idf

            indices.append(idx)
            values.append(float(weight))

        return indices, values

    def tokenize_single(self, token: str) -> Tuple[int, float]:
        """Tokenize a single term.

        Args:
            token: Single token to tokenize

        Returns:
            Tuple of (index, weight) for the token
        """
        token = token.lower().strip()

        if not token or token in STOPWORDS:
            return -1, 0.0

        if token not in self._token_to_index:
            idx = self._add_token_to_vocabulary(token)
        else:
            idx = self._token_to_index[token]

        idf = self._get_idf(token)

        return idx, float(idf)

    def has_token(self, index: int) -> bool:
        """Check if an index exists in the vocabulary.

        Args:
            index: Token index to check

        Returns:
            True if index exists in vocabulary
        """
        return index in self._index_to_token

    def get_token(self, index: int) -> Optional[str]:
        """Get token for a given index.

        Args:
            index: Token index

        Returns:
            Token string or None if not found
        """
        return self._index_to_token.get(index)

    def export_vocabulary(self) -> str:
        """Export vocabulary and IDF scores as JSON.

        Returns:
            JSON string with vocabulary data
        """
        data = {
            "token_to_index": self._token_to_index,
            "idf_scores": {
                token: self._get_idf(token) for token in self._token_to_index
            },
            "document_frequencies": dict(self._document_frequencies),
            "num_documents": self._num_documents,
            "total_doc_length": self._total_doc_length,
            "next_index": self._next_index,
        }
        return json.dumps(data, indent=2)

    def load_vocabulary(self, vocab_json: str) -> None:
        """Load vocabulary from JSON string.

        Thread-safe: acquires _update_lock to prevent concurrent modifications.

        Args:
            vocab_json: JSON string with vocabulary data
        """
        data = json.loads(vocab_json)

        with self._update_lock:
            self._token_to_index = data.get("token_to_index", {})
            self._index_to_token = {int(v): k for k, v in self._token_to_index.items()}
            self._document_frequencies = Counter(data.get("document_frequencies", {}))
            self._num_documents = data.get("num_documents", 0)
            self._total_doc_length = data.get("total_doc_length", 0)
            self._next_index = data.get("next_index", len(self._token_to_index))

    @property
    def vocabulary_size(self) -> int:
        """Get the current vocabulary size.

        Returns:
            Number of unique tokens in vocabulary
        """
        return len(self._token_to_index)

    def get_statistics(self) -> Dict[str, Any]:
        """Get tokenizer statistics.

        Returns:
            Dictionary with tokenizer stats
        """
        vocab_size = self.vocabulary_size
        return {
            "vocabulary_size": vocab_size,
            "num_documents": self._num_documents,
            "avg_doc_length": self._get_avg_doc_length(),
            "total_tokens_processed": self._total_doc_length,
            "vocabulary_at_limit": vocab_size >= self.MAX_VOCABULARY_SIZE,
            "max_vocabulary_size": self.MAX_VOCABULARY_SIZE,
        }

    # ==========================================================================
    # Incremental Vocabulary Update Methods
    # ==========================================================================

    def update_vocabulary(
        self, documents: List[str], return_stats: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Incrementally update vocabulary with new documents.

        This method adds new documents to the existing vocabulary without
        requiring a full rebuild. It updates document frequencies and IDF
        values for all terms.

        Args:
            documents: List of new document texts to add
            return_stats: If True, return statistics about the update

        Returns:
            Update statistics if return_stats=True, else None
        """
        if not documents:
            if return_stats:
                return {
                    "new_tokens_added": 0,
                    "documents_added": 0,
                    "vocabulary_size": self.vocabulary_size,
                }
            return None

        initial_vocab_size = self.vocabulary_size
        docs_added = 0

        for doc in documents:
            if not doc or not doc.strip():
                continue
            self._add_document_to_vocabulary(doc)
            docs_added += 1

        if return_stats:
            return {
                "new_tokens_added": self.vocabulary_size - initial_vocab_size,
                "documents_added": docs_added,
                "vocabulary_size": self.vocabulary_size,
            }
        return None

    def _add_document_to_vocabulary(self, doc: str) -> List[str]:
        """Add a single document to vocabulary.

        Thread-safe method that acquires lock before modifying vocabulary.

        Args:
            doc: Document text

        Returns:
            List of newly added tokens
        """
        tokens = self._extract_tokens(doc)
        if not tokens:
            return []

        unique_tokens = set(tokens)
        new_tokens = []

        # Thread-safe vocabulary modification
        with self._update_lock:
            # Update document frequencies
            for token in unique_tokens:
                self._document_frequencies[token] += 1
                if token not in self._token_to_index:
                    idx = self._add_token_to_vocabulary(token)
                    # Only track as new if actually added (not rejected due to limit)
                    if idx != -1:
                        new_tokens.append(token)

            self._num_documents += 1
            self._total_doc_length += len(tokens)

        return new_tokens

    def update_single_document(self, doc: str) -> List[str]:
        """Add a single document and return newly added tokens.

        This is an efficient method for adding one document at a time,
        useful for real-time FAQ additions.

        Args:
            doc: Document text to add

        Returns:
            List of newly added tokens (tokens not previously in vocabulary)
        """
        if not doc or not doc.strip():
            return []
        return self._add_document_to_vocabulary(doc)

    def get_vocabulary_drift_metrics(self, original_size: int) -> Dict[str, Any]:
        """Calculate metrics showing vocabulary drift from original.

        Useful for monitoring vocabulary growth over time.

        Args:
            original_size: Original vocabulary size for comparison

        Returns:
            Dictionary with drift metrics
        """
        current_size = self.vocabulary_size
        tokens_added = current_size - original_size
        growth_pct = (tokens_added / original_size * 100) if original_size > 0 else 0

        return {
            "original_size": original_size,
            "current_size": current_size,
            "tokens_added": tokens_added,
            "growth_percentage": round(growth_pct, 2),
        }
