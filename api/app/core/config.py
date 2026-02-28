import logging
import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# =============================================================================
# Pipeline Threshold Constants
# =============================================================================
# These constants are used by both UnifiedPipelineService and LearningEngine
# to ensure consistent routing decisions across the training pipeline.
#
# - AUTO_APPROVE: High-confidence candidates that can be auto-approved
# - SPOT_CHECK: Medium-confidence candidates that need quick human verification
# - FULL_REVIEW: Low-confidence candidates requiring thorough human review
# - DUPLICATE_FAQ: Semantic similarity threshold for duplicate detection

PIPELINE_AUTO_APPROVE_THRESHOLD: float = 0.90
PIPELINE_SPOT_CHECK_THRESHOLD: float = 0.75
PIPELINE_DUPLICATE_FAQ_THRESHOLD: float = 0.85


class Settings(BaseSettings):
    # API settings
    DEBUG: bool = False
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "BISQ Support"

    # CORS settings - accepts string or list, normalized to list[str] by validator
    CORS_ORIGINS: str | list[str] = "*"

    # Directory settings
    DATA_DIR: str = "api/data"

    # External URLs
    BISQ_API_URL: str = "http://bisq2-api:8090"
    PROMETHEUS_URL: str = "http://prometheus:9090"  # Prometheus metrics server
    MCP_HTTP_URL: str = "http://localhost:8000/mcp"  # MCP HTTP server URL for AISuite

    # Bisq2 API Authorization (for production-grade support API access)
    BISQ_API_AUTH_ENABLED: bool = False
    BISQ_API_CLIENT_ID: str = ""
    BISQ_API_CLIENT_SECRET: str = ""
    BISQ_API_SESSION_ID: str = ""
    BISQ_API_PAIRING_CODE_ID: str = ""
    BISQ_API_PAIRING_QR_FILE: str = ""
    BISQ_API_PAIRING_CLIENT_NAME: str = "bisq-support-agent"
    BISQ_API_AUTH_STATE_FILE: str = "bisq_api_auth.json"

    # Bisq 2 MCP Integration Settings
    BISQ_API_TIMEOUT: int = Field(
        default=5,
        ge=1,
        le=30,
        description="Timeout in seconds for Bisq API requests",
    )
    BISQ_WS_REST_FALLBACK_INTERVAL_SECONDS: float = Field(
        default=30.0,
        ge=0.0,
        le=3600.0,
        description=(
            "REST export fallback interval in seconds when support-message websocket "
            "stream is configured"
        ),
    )
    BISQ_WS_STARTUP_TIMEOUT_SECONDS: float = Field(
        default=5.0,
        ge=0.1,
        le=120.0,
        description=(
            "Timeout for Bisq support websocket connect/subscribe startup handshake "
            "before degrading to REST polling"
        ),
    )
    REACTION_NEGATIVE_STABILIZATION_SECONDS: float = Field(
        default=20.0,
        ge=0.0,
        le=300.0,
        description=(
            "Stabilization window before auto-escalating negative reactions to avoid "
            "false positives from quick reaction changes"
        ),
    )
    REACTION_FEEDBACK_FOLLOWUP_TTL_SECONDS: float = Field(
        default=900.0,
        ge=30.0,
        le=7200.0,
        description=(
            "How long a channel waits for user clarification after a negative reaction "
            "before expiring the follow-up"
        ),
    )
    BISQ_CACHE_TTL_PRICES: int = Field(
        default=120,
        ge=10,
        le=600,
        description="Cache TTL in seconds for market prices",
    )
    BISQ_CACHE_TTL_OFFERS: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Cache TTL in seconds for offerbook data",
    )
    BISQ_CACHE_TTL_REPUTATION: int = Field(
        default=300,
        ge=60,
        le=3600,
        description="Cache TTL in seconds for reputation data",
    )
    ENABLE_BISQ_MCP_INTEGRATION: bool = Field(
        default=False,
        description="Enable live Bisq 2 data integration (market prices, offers, reputation)",
    )

    # Matrix integration settings
    MATRIX_HOMESERVER_URL: str = ""  # e.g., "https://matrix.org"

    # Channel plugin enablement flags
    WEB_CHANNEL_ENABLED: bool = True
    BISQ2_CHANNEL_ENABLED: bool = False

    # Matrix sync lane (training ingestion)
    MATRIX_SYNC_ENABLED: bool = False
    MATRIX_SYNC_USER: str = ""  # Required when MATRIX_SYNC_ENABLED=true
    MATRIX_SYNC_PASSWORD: str = ""  # Required when MATRIX_SYNC_ENABLED=true
    MATRIX_SYNC_ROOMS: str | list[str] = ""  # Room IDs to monitor
    MATRIX_SYNC_SESSION_FILE: str = "matrix_session.json"
    MATRIX_SYNC_IGNORE_UNVERIFIED_DEVICES: bool = True

    # Matrix alert lane (Alertmanager notifications)
    MATRIX_ALERT_USER: str = ""  # Required when MATRIX_ALERT_ROOM is set
    MATRIX_ALERT_PASSWORD: str = ""  # Required when MATRIX_ALERT_ROOM is set
    MATRIX_ALERT_ROOM: str = ""  # Room ID for Alertmanager notifications
    MATRIX_ALERT_SESSION_FILE: str = "matrix_alert_session.json"

    # Tor hidden service settings
    TOR_HIDDEN_SERVICE: str = ""  # .onion address if Tor hidden service is configured

    # OpenAI settings (using AISuite for LLM interface)
    OPENAI_API_KEY: str = ""
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    OPENAI_MODEL: str = "openai:gpt-4o-mini"  # Full model ID with provider prefix
    MAX_TOKENS: int = 4096
    LLM_TEMPERATURE: float = 0.7  # Temperature for LLM responses (0.0-2.0)

    # Embedding Provider Configuration (LiteLLM multi-provider support)
    EMBEDDING_PROVIDER: str = "openai"  # Provider: openai, cohere, voyage, ollama
    EMBEDDING_MODEL: str = (
        "text-embedding-3-small"  # Model name (without provider prefix)
    )
    EMBEDDING_DIMENSIONS: int | None = None  # Optional dimensions (model-dependent)
    COHERE_API_KEY: str = ""  # API key for Cohere embeddings
    VOYAGE_API_KEY: str = ""  # API key for Voyage embeddings

    # Token pricing (for cost tracking in metrics)
    # Default values are for GPT-4o-mini as of 2024
    OPENAI_INPUT_COST_PER_TOKEN: float = 0.00000015  # $0.15 per 1M tokens
    OPENAI_OUTPUT_COST_PER_TOKEN: float = 0.0000006  # $0.60 per 1M tokens

    # RAG settings
    MAX_CHAT_HISTORY_LENGTH: int = (
        10  # Maximum number of chat history entries to include
    )
    MAX_CONTEXT_LENGTH: int = 15000  # Maximum length of context to include in prompt
    MAX_SAMPLE_LOG_LENGTH: int = 200  # Maximum length to log in samples

    # Retrieval Backend Configuration
    # Qdrant is the only supported backend.
    RETRIEVER_BACKEND: str = "qdrant"

    # Qdrant Vector Database Settings
    QDRANT_HOST: str = "qdrant"  # Docker service name
    QDRANT_PORT: int = 6333
    QDRANT_COLLECTION: str = "bisq_docs"
    QDRANT_GRPC_PORT: int = 6334  # Optional gRPC port for performance

    # ColBERT Reranking Settings
    COLBERT_MODEL: str = "colbert-ir/colbertv2.0"
    COLBERT_TOP_N: int = 5  # Number of documents to return after reranking
    ENABLE_COLBERT_RERANK: bool = False  # Disabled by default; opt-in for production

    # Query Rewriting Settings
    ENABLE_QUERY_REWRITE: bool = True
    QUERY_REWRITE_MODEL: str = "openai:gpt-4o-mini"
    QUERY_REWRITE_TIMEOUT_SECONDS: float = 2.0
    QUERY_REWRITE_MAX_HISTORY_TURNS: int = 4

    # Hybrid Search Weights (must sum to 1.0)
    # Optimized via RAGAS evaluation: 0.6/0.4 shows +6% faithfulness improvement
    HYBRID_SEMANTIC_WEIGHT: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Weight for dense/semantic vectors in hybrid search",
    )
    HYBRID_KEYWORD_WEIGHT: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="Weight for sparse/BM25 vectors in hybrid search",
    )

    @field_validator("RETRIEVER_BACKEND")
    @classmethod
    def validate_retriever_backend(cls, v: str) -> str:
        """Validate RETRIEVER_BACKEND is a supported value.

        Fails fast on typos to prevent runtime errors in the retrieval selector.

        Args:
            v: Retriever backend value

        Returns:
            Validated retriever backend value

        Raises:
            ValueError: If backend is not supported
        """
        allowed = {"qdrant"}
        if v not in allowed:
            raise ValueError(
                f"RETRIEVER_BACKEND must be one of {', '.join(sorted(allowed))}, got '{v}'"
            )
        return v

    @model_validator(mode="after")
    def validate_hybrid_weights_sum(self) -> "Settings":
        """Ensure HYBRID_SEMANTIC_WEIGHT + HYBRID_KEYWORD_WEIGHT == 1.0."""
        total = self.HYBRID_SEMANTIC_WEIGHT + self.HYBRID_KEYWORD_WEIGHT
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"HYBRID_SEMANTIC_WEIGHT ({self.HYBRID_SEMANTIC_WEIGHT}) + "
                f"HYBRID_KEYWORD_WEIGHT ({self.HYBRID_KEYWORD_WEIGHT}) must sum to 1.0, "
                f"got {total}"
            )
        return self

    # BM25 Tokenizer Settings
    BM25_VOCABULARY_FILE: str = "bm25_vocabulary.json"  # Vocabulary file in DATA_DIR

    # LLM Message Classification Settings (Provider-Agnostic)
    # Supports multiple LLM providers via AISuite: openai, anthropic, ollama
    ENABLE_LLM_CLASSIFICATION: bool = False  # Enable LLM-based message classification
    LLM_CLASSIFICATION_MODEL: str = (
        "openai:gpt-4o-mini"  # Model for classification (format: "provider:model")
    )
    LLM_PATTERN_CONFIDENCE_THRESHOLD: float = (
        0.85  # Min pattern confidence to skip LLM (0.0-1.0)
    )
    LLM_CLASSIFICATION_THRESHOLD: float = (
        0.75  # Min LLM confidence to use result (0.0-1.0)
    )
    LLM_CLASSIFICATION_CACHE_SIZE: int = (
        1000  # LRU cache size for classifications (reduced for privacy)
    )
    LLM_CLASSIFICATION_CACHE_TTL_HOURS: int = (
        1  # Cache time-to-live in hours (GDPR-friendly)
    )
    LLM_CLASSIFICATION_MAX_CONCURRENT: int = (
        2  # Max concurrent LLM API calls (cost control)
    )
    LLM_CLASSIFICATION_TEMPERATURE: float = (
        0.2  # LLM temperature for classification (0.0-2.0)
    )
    LLM_CLASSIFICATION_RATE_LIMIT_REQUESTS: int = 10  # Max requests per user per window
    LLM_CLASSIFICATION_RATE_LIMIT_WINDOW: int = 60  # Rate limit window in seconds

    # Full LLM Extraction Settings (Phase 2: Question Extraction with LLM)
    # Enables complete LLM-based question extraction from conversations
    ENABLE_LLM_EXTRACTION: bool = Field(
        default=False,
        description="Enable full LLM extraction (replaces pattern-based)",
    )
    LLM_EXTRACTION_MODEL: str = Field(
        default="openai:gpt-4o-mini",
        description="Model for extraction (format: 'provider:model')",
    )
    LLM_EXTRACTION_BATCH_SIZE: int = Field(
        default=2000,
        description="Maximum number of messages to process in a single LLM batch (gpt-4o-mini supports ~128K tokens)",
    )
    LLM_EXTRACTION_CACHE_TTL: int = Field(
        default=3600,
        description="Cache time-to-live in seconds (1 hour)",
    )
    LLM_EXTRACTION_CACHE_SIZE: int = Field(
        default=100,
        description="Maximum cache entries",
    )
    LLM_EXTRACTION_MAX_TOKENS: int = Field(
        default=4000,
        description="Max tokens per conversation (for truncation)",
    )
    LLM_EXTRACTION_TEMPERATURE: float = Field(
        default=0.0,
        description="LLM temperature for extraction (deterministic)",
    )

    # LLM Extraction Filtering Settings (Question Extraction Optimization)
    LLM_EXTRACTION_MIN_CONFIDENCE: float = Field(
        default=0.80,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for initial_question classification",
    )
    ENABLE_PRE_LLM_FILTERING: bool = Field(
        default=True,
        description="Enable pre-LLM message filtering to remove obvious noise",
    )
    ENABLE_POST_LLM_VALIDATION: bool = Field(
        default=True,
        description="Enable post-LLM question validation",
    )
    LLM_EXTRACTION_MIN_QUESTION_LENGTH: int = Field(
        default=10,
        ge=1,
        le=1000,
        description="Minimum character length for valid questions",
    )
    ENABLE_MESSAGE_NORMALIZATION: bool = Field(
        default=True,
        description="Enable message normalization before LLM processing",
    )

    # Security Settings for Regex Processing
    REGEX_TIMEOUT_SECONDS: float = Field(
        default=0.5,
        ge=0.1,
        le=5.0,
        description="Maximum seconds for regex pattern matching",
    )
    MAX_MESSAGE_LENGTH: int = Field(
        default=10000,
        ge=100,
        le=100000,
        description="Maximum message length in characters before truncation",
    )

    # Provider-specific API keys (separate from classification config)
    ANTHROPIC_API_KEY: str = ""  # For Anthropic Claude models
    OLLAMA_API_URL: str = "http://localhost:11434"  # For local Ollama deployment

    # Admin settings
    MAX_UNIQUE_ISSUES: int = 15  # Maximum number of unique issues to track in analytics
    ADMIN_API_KEY: str = ""  # Required in production, empty allowed for testing/mypy
    ESCALATION_RATING_TOKEN_SECRET: str = ""
    ESCALATION_RATING_TOKEN_TTL_SECONDS: int = 3600

    # CRITICAL: Single-Admin System Design Constraint
    # This system is designed for SINGLE CONCURRENT ADMIN operation.
    # The SQLite FAQ repository uses optimistic concurrency (last-write-wins).
    #
    # If multiple support agents need concurrent access, you MUST:
    # 1. Add optimistic locking (version column in faqs table)
    # 2. Implement connection pooling for concurrent reads (remove _read_lock serialization)
    # 3. Migrate to PostgreSQL when exceeding any of these thresholds:
    #    - 3+ concurrent support admins
    #    - 50+ concurrent read requests
    #    - 10,000+ FAQs in database
    #    - Geographic distribution required
    MAX_CONCURRENT_ADMINS: int = 1  # Enforced by application design (not runtime check)

    # Security settings for cookie handling
    COOKIE_SECURE: bool = True  # Set to False for .onion/HTTP development environments
    ADMIN_SESSION_MAX_AGE: int = (
        86400  # Session duration in seconds (default: 24 hours)
    )

    # Privacy and data protection settings
    DATA_RETENTION_DAYS: int = 30  # Days to retain personal data before cleanup
    ENABLE_PRIVACY_MODE: bool = True  # Enable privacy-preserving features
    PII_DETECTION_ENABLED: bool = True  # Enable PII detection in logs

    # Multilingual detection/translation policy settings
    MULTILINGUAL_LID_BACKEND: str = Field(
        default="langdetect",
        description="Primary local language ID backend (langdetect or none)",
    )
    MULTILINGUAL_LID_CONFIDENCE_THRESHOLD: float = Field(
        default=0.80,
        ge=0.0,
        le=1.0,
        description="Minimum local LID confidence to accept without LLM tie-break",
    )
    MULTILINGUAL_LID_SHORT_TEXT_CHARS: int = Field(
        default=24,
        ge=1,
        le=500,
        description="Text-length threshold below which LLM tie-break is allowed",
    )
    MULTILINGUAL_LID_MIXED_MARGIN_THRESHOLD: float = Field(
        default=0.20,
        ge=0.0,
        le=1.0,
        description="Top1-top2 confidence gap below which text is treated as mixed",
    )
    MULTILINGUAL_LID_MIXED_SECONDARY_MIN: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Minimum secondary confidence to classify as mixed language",
    )
    MULTILINGUAL_LID_ENABLE_LLM_TIEBREAKER: bool = Field(
        default=True,
        description="Allow LLM to resolve low-confidence/mixed local language detections",
    )
    MULTILINGUAL_TRANSLATION_SKIP_EN_CONFIDENCE: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Confidence threshold to skip translation when detected language is English",
    )

    @field_validator("MULTILINGUAL_LID_BACKEND")
    @classmethod
    def validate_lid_backend(cls, v: str) -> str:
        """Validate MULTILINGUAL_LID_BACKEND is a supported value."""
        allowed = {"langdetect", "none"}
        if v not in allowed:
            raise ValueError(
                "MULTILINGUAL_LID_BACKEND must be one of "
                f"{', '.join(sorted(allowed))}, got '{v}'"
            )
        return v

    # Support agent configuration
    SUPPORT_AGENT_NICKNAMES: str | list[str] = ""  # Comma-separated or list (required)
    # Known support staff usernames for message filtering (Matrix localparts without @ or :server)
    KNOWN_SUPPORT_STAFF: str | list[str] = Field(
        default="darawhelan,luis3672,mwithm,pazza83,strayorigin,suddenwhipvapor",
        description="Comma-separated list of support staff Matrix usernames (localparts only)",
    )

    # Auto-Training Pipeline Settings
    AUTO_TRAINING_ENABLED: bool = Field(
        default=False,
        description="Enable automatic training pipeline for staff answer ingestion",
    )
    # Trusted staff Matrix IDs for auto-training (full Matrix IDs like @user:matrix.org)
    # SECURITY: Always use full Matrix IDs to prevent impersonation from other homeservers
    # NOTE: No default - must be explicitly configured via TRUSTED_STAFF_IDS env var
    TRUSTED_STAFF_IDS: str | list[str] = Field(
        default="",
        description="Comma-separated list of trusted staff full Matrix IDs for auto-training",
    )

    # Escalation Learning Pipeline Settings
    ESCALATION_CLAIM_TTL_MINUTES: int = 30
    ESCALATION_AUTO_CLOSE_HOURS: int = 24
    ESCALATION_DELIVERY_MAX_RETRIES: int = 3
    ESCALATION_RETENTION_DAYS: int = 90
    ESCALATION_ENABLED: bool = True
    ESCALATION_BISQ2_WS_ENABLED: bool = False
    ESCALATION_POLL_TIMEOUT_MINUTES: int = 30

    # Environment settings
    ENVIRONMENT: str = "development"

    # Simple config - let Pydantic handle things
    model_config = SettingsConfigDict(
        env_file=".env",  # Enable .env file loading
        extra="allow",  # Allow extra fields for backward compatibility during migration
    )

    # Path properties that return complete paths
    @property
    def ESCALATION_DB_PATH(self) -> str:
        """Complete path to the escalation SQLite database."""
        return os.path.join(self.DATA_DIR, "escalations.db")

    @property
    def FAQ_DB_PATH(self) -> str:
        """Complete path to the FAQ SQLite database (authoritative source)"""
        return os.path.join(self.DATA_DIR, "faqs.db")

    @property
    def CHAT_EXPORT_FILE_PATH(self) -> str:
        """Complete path to the support chat export file"""
        return os.path.join(self.DATA_DIR, "support_chat_export.csv")

    @property
    def PROCESSED_CONVS_FILE_PATH(self) -> str:
        """Complete path to the processed conversations file"""
        return os.path.join(self.DATA_DIR, "processed_conversations.json")

    @property
    def WIKI_DIR_PATH(self) -> str:
        """Complete path to the wiki data directory"""
        return os.path.join(self.DATA_DIR, "wiki")

    @property
    def FEEDBACK_DIR_PATH(self) -> str:
        """Complete path to the feedback directory"""
        return os.path.join(self.DATA_DIR, "feedback")

    @property
    def CONVERSATIONS_FILE_PATH(self) -> str:
        """Complete path to the conversations file"""
        return os.path.join(self.DATA_DIR, "conversations.jsonl")

    @property
    def PROCESSED_MESSAGE_IDS_FILE_PATH(self) -> str:
        """Complete path to the processed message IDs file"""
        return os.path.join(self.DATA_DIR, "processed_message_ids.jsonl")

    @property
    def MATRIX_SYNC_SESSION_PATH(self) -> str:
        """Complete path to Matrix sync session persistence file."""
        if os.path.isabs(self.MATRIX_SYNC_SESSION_FILE):
            return self.MATRIX_SYNC_SESSION_FILE
        return os.path.join(self.DATA_DIR, self.MATRIX_SYNC_SESSION_FILE)

    @property
    def MATRIX_ALERT_SESSION_FILE_PATH(self) -> str:
        """Complete path to Matrix alert session persistence file."""
        if os.path.isabs(self.MATRIX_ALERT_SESSION_FILE):
            return self.MATRIX_ALERT_SESSION_FILE
        return os.path.join(self.DATA_DIR, self.MATRIX_ALERT_SESSION_FILE)

    @property
    def MATRIX_SYNC_USER_RESOLVED(self) -> str:
        """Matrix sync/support user (strict lane-specific setting)."""
        return (self.MATRIX_SYNC_USER or "").strip()

    @property
    def MATRIX_SYNC_PASSWORD_RESOLVED(self) -> str:
        """Matrix sync/support password (strict lane-specific setting)."""
        return (self.MATRIX_SYNC_PASSWORD or "").strip()

    @property
    def MATRIX_ALERT_USER_RESOLVED(self) -> str:
        """Matrix alert user (strict lane-specific setting)."""
        return (self.MATRIX_ALERT_USER or "").strip()

    @property
    def MATRIX_ALERT_PASSWORD_RESOLVED(self) -> str:
        """Matrix alert password (strict lane-specific setting)."""
        return (self.MATRIX_ALERT_PASSWORD or "").strip()

    @property
    def BISQ_API_PAIRING_QR_PATH(self) -> str:
        """Complete path to optional Bisq pairing QR payload file."""
        if not self.BISQ_API_PAIRING_QR_FILE:
            return ""
        if os.path.isabs(self.BISQ_API_PAIRING_QR_FILE):
            return self.BISQ_API_PAIRING_QR_FILE
        return os.path.join(self.DATA_DIR, self.BISQ_API_PAIRING_QR_FILE)

    @property
    def BISQ_API_AUTH_STATE_PATH(self) -> str:
        """Complete path to persisted Bisq API auth credentials."""
        if os.path.isabs(self.BISQ_API_AUTH_STATE_FILE):
            return self.BISQ_API_AUTH_STATE_FILE
        return os.path.join(self.DATA_DIR, self.BISQ_API_AUTH_STATE_FILE)

    @property
    def ACTIVE_LLM_CREDENTIAL(self) -> str:
        """Get credential (API key or URL) for currently configured LLM provider.

        Derives the correct credential based on the provider prefix in
        LLM_CLASSIFICATION_MODEL (e.g., "openai:gpt-4o-mini" → OPENAI_API_KEY).
        For Ollama, returns the base URL instead of an API key.

        Returns:
            API key string or URL for the active provider

        Raises:
            ValueError: If provider is not supported or credential is missing
        """
        if not self.LLM_CLASSIFICATION_MODEL:
            raise ValueError("LLM_CLASSIFICATION_MODEL is not configured")

        # Extract provider from model string (format: "provider:model")
        provider = self.LLM_CLASSIFICATION_MODEL.split(":")[0].lower()

        # Map provider to corresponding credential (API key or URL)
        provider_credentials = {
            "openai": self.OPENAI_API_KEY,
            "anthropic": self.ANTHROPIC_API_KEY,
            "ollama": self.OLLAMA_API_URL,  # Ollama uses URL instead of API key
        }

        if provider not in provider_credentials:
            raise ValueError(
                f"Unsupported LLM provider: {provider}. "
                f"Supported providers: {', '.join(provider_credentials.keys())}"
            )

        credential = provider_credentials[provider]
        if not credential:
            if provider == "ollama":
                raise ValueError(
                    "OLLAMA_API_URL is required but not set when using Ollama provider. "
                    "Please configure the Ollama server URL."
                )
            else:
                raise ValueError(
                    f"{provider.upper()}_API_KEY is required but not set. "
                    f"Please configure the API key for {provider} provider."
                )

        return credential

    def get_data_path(self, *path_parts) -> str:
        """Utility method to construct paths within DATA_DIR

        Args:
            *path_parts: Path components to join with DATA_DIR

        Returns:
            Complete path within DATA_DIR
        """
        return os.path.join(self.DATA_DIR, *path_parts)

    @field_validator("PROMETHEUS_URL")
    @classmethod
    def validate_prometheus_url(cls, v: str) -> str:
        """Normalize and validate Prometheus URL.

        Ensures URL has a scheme and removes trailing slashes to prevent
        double-slash requests and misconfigurations.

        Args:
            v: Prometheus URL

        Returns:
            Normalized Prometheus URL with scheme and no trailing slash

        Raises:
            ValueError: If PROMETHEUS_URL is empty
        """
        v = v.strip()
        if not v:
            raise ValueError("PROMETHEUS_URL must be non-empty")
        # Ensure scheme present; don't force TLD to keep internal hosts valid
        if "://" not in v:
            v = "http://" + v
        return v.rstrip("/")

    @field_validator("LLM_TEMPERATURE")
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        """Validate LLM temperature is within acceptable range.

        Args:
            v: Temperature value

        Returns:
            Validated temperature value

        Raises:
            ValueError: If temperature is outside acceptable range
        """
        if not 0.0 <= v <= 2.0:
            raise ValueError(f"LLM_TEMPERATURE must be between 0.0 and 2.0, got {v}")
        return v

    @field_validator("LLM_CLASSIFICATION_TEMPERATURE")
    @classmethod
    def validate_classification_temperature(cls, v: float) -> float:
        """Validate LLM classification temperature is within acceptable range.

        Args:
            v: Temperature value

        Returns:
            Validated temperature value

        Raises:
            ValueError: If temperature is outside acceptable range
        """
        if not 0.0 <= v <= 2.0:
            raise ValueError(
                f"LLM_CLASSIFICATION_TEMPERATURE must be between 0.0 and 2.0, got {v}"
            )
        return v

    @field_validator("LLM_PATTERN_CONFIDENCE_THRESHOLD")
    @classmethod
    def validate_pattern_threshold(cls, v: float) -> float:
        """Validate pattern confidence threshold is within valid range.

        Args:
            v: Threshold value

        Returns:
            Validated threshold value

        Raises:
            ValueError: If threshold is outside valid range
        """
        if not 0.0 <= v <= 1.0:
            raise ValueError(
                f"LLM_PATTERN_CONFIDENCE_THRESHOLD must be between 0.0 and 1.0, got {v}"
            )
        return v

    @field_validator("LLM_CLASSIFICATION_THRESHOLD")
    @classmethod
    def validate_classification_threshold(cls, v: float) -> float:
        """Validate LLM classification threshold is within valid range.

        Args:
            v: Threshold value

        Returns:
            Validated threshold value

        Raises:
            ValueError: If threshold is outside valid range
        """
        if not 0.0 <= v <= 1.0:
            raise ValueError(
                f"LLM_CLASSIFICATION_THRESHOLD must be between 0.0 and 1.0, got {v}"
            )
        return v

    @field_validator("LLM_CLASSIFICATION_MODEL")
    @classmethod
    def validate_classification_model(cls, v: str) -> str:
        """Validate LLM classification model format.

        Args:
            v: Model string

        Returns:
            Validated model string

        Raises:
            ValueError: If model format is invalid
        """
        if not v:
            return v  # Allow empty (feature disabled)

        if ":" not in v:
            raise ValueError(
                f"LLM_CLASSIFICATION_MODEL must be in format 'provider:model', got '{v}'"
            )

        provider, _ = v.split(":", 1)
        supported_providers = ["openai", "anthropic", "ollama"]

        if provider.lower() not in supported_providers:
            raise ValueError(
                f"Unsupported provider '{provider}'. "
                f"Supported providers: {', '.join(supported_providers)}"
            )

        return v

    @field_validator("ADMIN_SESSION_MAX_AGE")
    @classmethod
    def validate_admin_session_max_age(cls, v: int) -> int:
        """Validate admin session max age is within acceptable range.

        Args:
            v: Session max age in seconds

        Returns:
            Validated session max age

        Raises:
            ValueError: If session max age is outside acceptable range
        """
        if v < 60:
            raise ValueError("ADMIN_SESSION_MAX_AGE must be at least 60 seconds")
        if v > 30 * 24 * 3600:  # 30 days
            raise ValueError("ADMIN_SESSION_MAX_AGE must be ≤ 30 days")
        return v

    @field_validator("MATRIX_SYNC_ROOMS", mode="before")
    @classmethod
    def parse_matrix_sync_rooms(cls, v: str | list[str]) -> list[str]:
        """Normalize MATRIX_SYNC_ROOMS to list of room IDs.

        Accepts either a comma-separated string or a list of strings.
        Handles trimming whitespace and ignores empty entries.

        Args:
            v: Matrix room IDs as string (comma-separated) or list of strings

        Returns:
            List of Matrix room IDs with whitespace trimmed and empty entries removed
        """
        # Handle list input
        if isinstance(v, list):
            return [
                room.strip() for room in v if isinstance(room, str) and room.strip()
            ]

        # Handle string input
        if isinstance(v, str):
            return [room.strip() for room in v.split(",") if room.strip()]

        # Fallback for unexpected types
        return []

    @field_validator("SUPPORT_AGENT_NICKNAMES", mode="before")
    @classmethod
    def parse_support_agent_nicknames(cls, v: str | list[str]) -> list[str]:
        """Normalize SUPPORT_AGENT_NICKNAMES to list of nicknames.

        Accepts either a comma-separated string or a list of strings.
        Handles trimming whitespace and ignores empty entries.

        Args:
            v: Support agent nicknames as string (comma-separated) or list of strings

        Returns:
            List of support agent nicknames with whitespace trimmed and empty entries removed
        """
        # Handle list input
        if isinstance(v, list):
            # Filter out empty strings and trim whitespace
            return [
                nickname.strip()
                for nickname in v
                if isinstance(nickname, str) and nickname.strip()
            ]

        # Handle string input
        if isinstance(v, str):
            # Split by comma, trim whitespace, filter empty entries
            return [nickname.strip() for nickname in v.split(",") if nickname.strip()]

        # Fallback for unexpected types
        return []

    @field_validator("KNOWN_SUPPORT_STAFF", mode="before")
    @classmethod
    def parse_known_support_staff(cls, v: str | list[str]) -> list[str]:
        """Normalize KNOWN_SUPPORT_STAFF to list of usernames.

        Accepts either a comma-separated string or a list of strings.
        Handles trimming whitespace and ignores empty entries.
        Converts to lowercase for case-insensitive matching.

        Args:
            v: Support staff usernames as string (comma-separated) or list of strings

        Returns:
            List of support staff usernames (lowercase, trimmed)
        """
        # Handle list input
        if isinstance(v, list):
            return [
                username.strip().lower()
                for username in v
                if isinstance(username, str) and username.strip()
            ]

        # Handle string input
        if isinstance(v, str):
            return [
                username.strip().lower()
                for username in v.split(",")
                if username.strip()
            ]

        # Fallback for unexpected types
        return []

    @field_validator("TRUSTED_STAFF_IDS", mode="before")
    @classmethod
    def parse_trusted_staff_ids(cls, v: str | list[str]) -> list[str]:
        """Normalize TRUSTED_STAFF_IDS to list of full Matrix IDs.

        Accepts either a comma-separated string or a list of strings.
        Handles trimming whitespace and ignores empty entries.
        Preserves case for Matrix ID matching (Matrix IDs are case-sensitive).

        Args:
            v: Trusted staff Matrix IDs as string (comma-separated) or list of strings

        Returns:
            List of trusted staff Matrix IDs (trimmed, case preserved)
        """
        result = []

        # Handle list input
        if isinstance(v, list):
            result = [
                staff_id.strip()
                for staff_id in v
                if isinstance(staff_id, str) and staff_id.strip()
            ]
        # Handle string input
        elif isinstance(v, str):
            result = [staff_id.strip() for staff_id in v.split(",") if staff_id.strip()]

        return result

    @field_validator("TRUSTED_STAFF_IDS")
    @classmethod
    def validate_trusted_staff_ids(cls, v: list[str]) -> list[str]:
        """Validate TRUSTED_STAFF_IDS entries are valid Matrix IDs.

        Args:
            v: List of trusted staff Matrix IDs

        Returns:
            Validated list of Matrix IDs

        Raises:
            ValueError: If any Matrix ID is malformed
        """
        for staff_id in v:
            if not staff_id.startswith("@"):
                raise ValueError(f"Invalid Matrix ID '{staff_id}': must start with @")
            if ":" not in staff_id:
                raise ValueError(
                    f"Invalid Matrix ID '{staff_id}': must contain homeserver (e.g., @user:matrix.org)"
                )
        return v

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        """Normalize CORS_ORIGINS to list of hosts.

        Accepts either a comma-separated string or a list of strings.
        Handles wildcards, trims whitespace, and ignores empty entries.

        Args:
            v: CORS origins as string (comma-separated), list of strings, or "*" for all

        Returns:
            List of CORS origin hosts with whitespace trimmed and empty entries removed
        """
        # Handle list input
        if isinstance(v, list):
            # Filter out empty strings and trim whitespace
            return [
                host.strip() for host in v if isinstance(host, str) and host.strip()
            ]

        # Handle string input
        if isinstance(v, str):
            # Handle wildcard
            if v.strip() == "*":
                return ["*"]
            # Split by comma, trim whitespace, filter empty entries
            return [host.strip() for host in v.split(",") if host.strip()]

        # Fallback for unexpected types: fail-closed (deny all origins)
        return []

    @classmethod
    def _is_production(cls, info: ValidationInfo) -> bool:
        """Check if ENVIRONMENT indicates production.

        Args:
            info: Validation info containing other field values

        Returns:
            True if environment is production, False otherwise
        """
        raw_env = info.data.get("ENVIRONMENT", "development")
        environment = str(raw_env).strip().lower()
        # Normalize "prod" alias to "production"
        if environment in {"prod"}:
            environment = "production"
        return environment == "production"

    @field_validator("CORS_ORIGINS")
    @classmethod
    def validate_cors_in_production(cls, v: list[str], info) -> list[str]:
        """Reject wildcard CORS in production environments.

        Args:
            v: Normalized CORS origins list
            info: Validation info containing other field values

        Returns:
            Validated CORS origins list

        Raises:
            ValueError: If wildcard CORS is used in production
        """
        # Reject wildcard in production
        if cls._is_production(info) and v == ["*"]:
            raise ValueError("CORS wildcard '*' not allowed in production")

        return v

    @field_validator("ADMIN_API_KEY")
    @classmethod
    def validate_admin_key_in_production(cls, v: str, info) -> str:
        """Ensure ADMIN_API_KEY is set in production environments.

        Args:
            v: The ADMIN_API_KEY value
            info: Validation info containing other field values

        Returns:
            The validated and stripped ADMIN_API_KEY

        Raises:
            ValueError: If ADMIN_API_KEY is empty in production
        """
        # Require ADMIN_API_KEY in production
        if cls._is_production(info) and not v.strip():
            raise ValueError("ADMIN_API_KEY required in production")

        return v.strip()

    @field_validator("MATRIX_HOMESERVER_URL")
    @classmethod
    def validate_matrix_homeserver_url(cls, v: str) -> str:
        """Enforce HTTPS for Matrix homeserver URLs (except localhost for dev).

        Args:
            v: Matrix homeserver URL

        Returns:
            Validated URL with HTTPS scheme (or HTTP for localhost)

        Raises:
            ValueError: If URL doesn't use HTTPS protocol (except localhost)
        """
        v = v.strip()
        if not v:
            return v
        # Allow HTTP for localhost/127.0.0.1 for local development
        is_localhost = any(
            v.startswith(prefix) for prefix in ["http://localhost", "http://127.0.0.1"]
        )
        if not v.startswith("https://") and not is_localhost:
            raise ValueError(
                "MATRIX_HOMESERVER_URL must use HTTPS protocol for security "
                "(HTTP allowed only for localhost). "
                f"Got: {v}"
            )
        return v

    @model_validator(mode="after")
    def validate_matrix_auth_in_production(self) -> "Settings":
        """Ensure Matrix lanes have explicit passwords when enabled.

        This is a model validator (mode='after') to ensure all fields are loaded
        before validation.

        Returns:
            The validated Settings instance

        Raises:
            ValueError: If Matrix homeserver is configured but no Matrix password is set
        """
        # Only validate if Matrix integration is enabled
        homeserver = (self.MATRIX_HOMESERVER_URL or "").strip()
        if not homeserver:
            return self  # Matrix not enabled, skip validation

        if self.MATRIX_SYNC_ENABLED and not self.MATRIX_SYNC_PASSWORD_RESOLVED:
            raise ValueError(
                "MATRIX_SYNC_PASSWORD is required when MATRIX_SYNC_ENABLED is true."
            )

        if (
            self.MATRIX_ALERT_ROOM or ""
        ).strip() and not self.MATRIX_ALERT_PASSWORD_RESOLVED:
            raise ValueError(
                "MATRIX_ALERT_PASSWORD is required when MATRIX_ALERT_ROOM is set."
            )

        return self

    @model_validator(mode="after")
    def validate_matrix_sync_enabled_config(self) -> "Settings":
        """Require core sync fields when MATRIX_SYNC_ENABLED is explicitly enabled."""
        if not self.MATRIX_SYNC_ENABLED:
            return self

        missing = []
        if not (self.MATRIX_HOMESERVER_URL or "").strip():
            missing.append("MATRIX_HOMESERVER_URL")
        if not self.MATRIX_SYNC_USER_RESOLVED:
            missing.append("MATRIX_SYNC_USER")
        if not self.MATRIX_SYNC_PASSWORD_RESOLVED:
            missing.append("MATRIX_SYNC_PASSWORD")
        if not self.MATRIX_SYNC_ROOMS:
            missing.append("MATRIX_SYNC_ROOMS")

        if missing:
            raise ValueError(
                "MATRIX_SYNC_ENABLED is True but missing required settings: "
                + ", ".join(missing)
            )

        return self

    @model_validator(mode="after")
    def validate_matrix_alert_config(self) -> "Settings":
        """Require core alert fields when MATRIX_ALERT_ROOM is configured."""
        if not (self.MATRIX_ALERT_ROOM or "").strip():
            return self

        missing = []
        if not (self.MATRIX_HOMESERVER_URL or "").strip():
            missing.append("MATRIX_HOMESERVER_URL")
        if not self.MATRIX_ALERT_USER_RESOLVED:
            missing.append("MATRIX_ALERT_USER")
        if not self.MATRIX_ALERT_PASSWORD_RESOLVED:
            missing.append("MATRIX_ALERT_PASSWORD")
        if missing:
            raise ValueError(
                "MATRIX_ALERT_ROOM is set but missing required settings: "
                + ", ".join(missing)
            )
        return self

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Make paths absolute
        self.DATA_DIR = os.path.abspath(self.DATA_DIR)

    def ensure_data_dirs(self) -> None:
        """Create required data directories if they don't exist.

        This method is called during application startup (lifespan) to avoid
        import-time side effects and I/O operations.
        """
        Path(self.DATA_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.FEEDBACK_DIR_PATH).mkdir(parents=True, exist_ok=True)
        Path(self.WIKI_DIR_PATH).mkdir(parents=True, exist_ok=True)


# Thread-safe lazy initialization using lru_cache
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached application settings instance with lazy initialization.

    Settings are only created once on first access, then cached for subsequent calls.
    This prevents module-level side effects and allows testing without environment variables.
    Thread-safe via lru_cache mechanism.

    Returns:
        Settings: Application settings object
    """
    return Settings()


def reset_settings() -> None:
    """Reset the cached settings instance.

    Useful for testing when you need to reload settings with different values.
    """
    get_settings.cache_clear()
