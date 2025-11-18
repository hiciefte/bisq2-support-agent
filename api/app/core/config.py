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
