import logging
import os
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


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
    BISQ_API_URL: str = "http://localhost:8090"
    PROMETHEUS_URL: str = "http://prometheus:9090"  # Prometheus metrics server

    # Matrix integration settings for shadow mode
    MATRIX_HOMESERVER_URL: str = ""  # e.g., "https://matrix.org"
    MATRIX_USER: str = ""  # Bot user ID, e.g., "@bisq-bot:matrix.org"
    MATRIX_PASSWORD: str = (
        ""  # Bot password for automatic session management (recommended)
    )
    MATRIX_TOKEN: str = ""  # DEPRECATED: Access token (use MATRIX_PASSWORD instead)
    MATRIX_ROOMS: str | list[str] = ""  # Room IDs to monitor (comma-separated or list)
    MATRIX_SESSION_FILE: str = (
        "/data/matrix_session.json"  # Session persistence file path
    )

    # Tor hidden service settings
    TOR_HIDDEN_SERVICE: str = ""  # .onion address if Tor hidden service is configured

    # OpenAI settings (using AISuite for LLM interface)
    OPENAI_API_KEY: str = ""
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    OPENAI_MODEL: str = "openai:gpt-4o-mini"  # Full model ID with provider prefix
    MAX_TOKENS: int = 4096
    LLM_TEMPERATURE: float = 0.7  # Temperature for LLM responses (0.0-2.0)

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

    # Provider-specific API keys (separate from classification config)
    ANTHROPIC_API_KEY: str = ""  # For Anthropic Claude models
    OLLAMA_API_URL: str = "http://localhost:11434"  # For local Ollama deployment

    # Admin settings
    MAX_UNIQUE_ISSUES: int = 15  # Maximum number of unique issues to track in analytics
    ADMIN_API_KEY: str = ""  # Required in production, empty allowed for testing/mypy

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

    # Support agent configuration
    SUPPORT_AGENT_NICKNAMES: str | list[str] = ""  # Comma-separated or list (required)

    # Environment settings
    ENVIRONMENT: str = "development"

    # Simple config - let Pydantic handle things
    model_config = SettingsConfigDict(
        env_file=".env",  # Enable .env file loading
        extra="allow",  # Allow extra fields for backward compatibility during migration
    )

    # Path properties that return complete paths
    @property
    def FAQ_FILE_PATH(self) -> str:
        """Complete path to the FAQ file"""
        return os.path.join(self.DATA_DIR, "extracted_faq.jsonl")

    @property
    def CHAT_EXPORT_FILE_PATH(self) -> str:
        """Complete path to the support chat export file"""
        return os.path.join(self.DATA_DIR, "support_chat_export.csv")

    @property
    def PROCESSED_CONVS_FILE_PATH(self) -> str:
        """Complete path to the processed conversations file"""
        return os.path.join(self.DATA_DIR, "processed_conversations.json")

    @property
    def VECTOR_STORE_DIR_PATH(self) -> str:
        """Complete path to the vector store directory"""
        return os.path.join(self.DATA_DIR, "vectorstore")

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
    def FAQ_DB_PATH(self) -> str:
        """Complete path to the SQLite FAQ database file"""
        return os.path.join(self.DATA_DIR, "faqs.db")

    @property
    def ACTIVE_LLM_API_KEY(self) -> str:
        """Get API key for currently configured LLM provider.

        Derives the correct API key based on the provider prefix in
        LLM_CLASSIFICATION_MODEL (e.g., "openai:gpt-4o-mini" → OPENAI_API_KEY).

        Returns:
            API key string for the active provider

        Raises:
            ValueError: If provider is not supported or API key is missing
        """
        if not self.LLM_CLASSIFICATION_MODEL:
            raise ValueError("LLM_CLASSIFICATION_MODEL is not configured")

        # Extract provider from model string (format: "provider:model")
        provider = self.LLM_CLASSIFICATION_MODEL.split(":")[0].lower()

        # Map provider to corresponding API key
        provider_keys = {
            "openai": self.OPENAI_API_KEY,
            "anthropic": self.ANTHROPIC_API_KEY,
            "ollama": self.OLLAMA_API_URL,  # Ollama uses URL instead of API key
        }

        if provider not in provider_keys:
            raise ValueError(
                f"Unsupported LLM provider: {provider}. "
                f"Supported providers: {', '.join(provider_keys.keys())}"
            )

        api_key = provider_keys[provider]
        if not api_key and provider != "ollama":
            raise ValueError(
                f"{provider.upper()}_API_KEY is required but not set. "
                f"Please configure the API key for {provider} provider."
            )

        return api_key

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

        provider, model = v.split(":", 1)
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

    @field_validator("MATRIX_ROOMS", mode="before")
    @classmethod
    def parse_matrix_rooms(cls, v: str | list[str]) -> list[str]:
        """Normalize MATRIX_ROOMS to list of room IDs.

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
        """Enforce HTTPS for Matrix homeserver URLs.

        Args:
            v: Matrix homeserver URL

        Returns:
            Validated URL with HTTPS scheme

        Raises:
            ValueError: If URL doesn't use HTTPS protocol
        """
        v = v.strip()
        if v and not v.startswith("https://"):
            raise ValueError(
                "MATRIX_HOMESERVER_URL must use HTTPS protocol for security. "
                f"Got: {v}"
            )
        return v

    @field_validator("MATRIX_PASSWORD")
    @classmethod
    def validate_matrix_auth_in_production(cls, v: str, info) -> str:
        """Ensure Matrix authentication is configured when Matrix is enabled.

        Args:
            v: The MATRIX_PASSWORD value
            info: Validation info containing other field values

        Returns:
            The validated and stripped MATRIX_PASSWORD

        Raises:
            ValueError: If Matrix is enabled but neither password nor token is set
        """
        v = v.strip()

        # Only validate if Matrix integration is enabled
        homeserver = str(info.data.get("MATRIX_HOMESERVER_URL", "")).strip()
        if not homeserver:
            return v  # Matrix not enabled, skip validation

        # Check if either password or token is provided
        token = str(info.data.get("MATRIX_TOKEN", "")).strip()
        if not v and not token:
            raise ValueError(
                "MATRIX_PASSWORD or MATRIX_TOKEN required when MATRIX_HOMESERVER_URL is set. "
                "MATRIX_PASSWORD is recommended for automatic session management."
            )

        return v

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
        Path(self.VECTOR_STORE_DIR_PATH).mkdir(parents=True, exist_ok=True)
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
