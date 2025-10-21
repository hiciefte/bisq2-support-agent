import logging
import os
from pathlib import Path

from pydantic import field_validator
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

    # Tor hidden service settings
    TOR_HIDDEN_SERVICE: str = ""  # .onion address if Tor hidden service is configured

    # OpenAI settings (using AISuite for LLM interface)
    OPENAI_API_KEY: str = ""
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    OPENAI_MODEL: str = "openai:gpt-4o-mini"  # Full model ID with provider prefix
    MAX_TOKENS: int = 4096
    LLM_TEMPERATURE: float = 0.7  # Temperature for LLM responses (0.0-2.0)

    # RAG settings
    MAX_CHAT_HISTORY_LENGTH: int = (
        10  # Maximum number of chat history entries to include
    )
    MAX_CONTEXT_LENGTH: int = 15000  # Maximum length of context to include in prompt
    MAX_SAMPLE_LOG_LENGTH: int = 200  # Maximum length to log in samples

    # Admin settings
    MAX_UNIQUE_ISSUES: int = 15  # Maximum number of unique issues to track in analytics
    ADMIN_API_KEY: str = ""  # Required in production, empty allowed for testing/mypy

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
        env_parse_json=False,  # Disable trying to parse values as JSON
        env_file_override=True,  # Ensure environment variables take precedence
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

    def get_data_path(self, *path_parts) -> str:
        """Utility method to construct paths within DATA_DIR

        Args:
            *path_parts: Path components to join with DATA_DIR

        Returns:
            Complete path within DATA_DIR
        """
        return os.path.join(self.DATA_DIR, *path_parts)

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

        # Fallback for unexpected types
        return ["*"]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Make paths absolute
        self.DATA_DIR = os.path.abspath(self.DATA_DIR)

        # Create directories if they don't exist
        Path(self.DATA_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.FEEDBACK_DIR_PATH).mkdir(parents=True, exist_ok=True)

    @field_validator("ADMIN_API_KEY")
    @classmethod
    def validate_admin_key_in_production(cls, v: str, info) -> str:
        """Ensure ADMIN_API_KEY is set in production environments.

        Args:
            v: The ADMIN_API_KEY value
            info: Validation info containing other field values

        Returns:
            The validated ADMIN_API_KEY

        Raises:
            ValueError: If ADMIN_API_KEY is empty in production
        """
        # Get environment from data if available
        environment = info.data.get("ENVIRONMENT", "development")

        # Require ADMIN_API_KEY in production
        if environment == "production" and not v:
            raise ValueError(
                "ADMIN_API_KEY is required in production environment. "
                "Set the ADMIN_API_KEY environment variable."
            )

        return v


# Lazy initialization pattern - settings only created when first accessed
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get cached application settings instance with lazy initialization.

    Settings are only created once on first access, then cached for subsequent calls.
    This prevents module-level side effects and allows testing without environment variables.

    Returns:
        Settings: Application settings object
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset the cached settings instance.

    Useful for testing when you need to reload settings with different values.
    """
    global _settings
    _settings = None
