import logging
import os
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # API settings
    DEBUG: bool = False
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "BISQ Support"

    # CORS settings
    # Start with string to avoid JSON parsing, we'll convert it in validator
    CORS_ORIGINS: str = "*"

    # Directory settings
    DATA_DIR: str = "api/data"

    # External URLs
    BISQ_API_URL: str = "http://localhost:8090"

    # Tor hidden service settings
    TOR_HIDDEN_SERVICE: str = ""  # .onion address if Tor hidden service is configured

    # LLM Provider setting
    LLM_PROVIDER: str = "openai"  # Can be "openai" or "xai"

    # OpenAI settings
    OPENAI_API_KEY: str = ""
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    OPENAI_MODEL: str = "gpt-4o-mini"
    MAX_TOKENS: int = 4096

    # xAI settings
    XAI_API_KEY: str = ""
    XAI_MODEL: str = "llama3-70b-8192"

    # RAG settings
    MAX_CHAT_HISTORY_LENGTH: int = (
        10  # Maximum number of chat history entries to include
    )
    MAX_CONTEXT_LENGTH: int = 15000  # Maximum length of context to include in prompt
    MAX_SAMPLE_LOG_LENGTH: int = 200  # Maximum length to log in samples

    # Admin settings
    MAX_UNIQUE_ISSUES: int = 15  # Maximum number of unique issues to track in analytics
    ADMIN_API_KEY: str  # No default, must be set via environment

    # Security settings for cookie handling
    COOKIE_SECURE: bool = True  # Set to False for .onion/HTTP development environments

    # Privacy and data protection settings
    DATA_RETENTION_DAYS: int = 30  # Days to retain personal data before cleanup
    ENABLE_PRIVACY_MODE: bool = True  # Enable privacy-preserving features
    PII_DETECTION_ENABLED: bool = True  # Enable PII detection in logs

    # Environment settings
    ENVIRONMENT: str = "development"

    # Simple config - let Pydantic handle things
    model_config = SettingsConfigDict(
        env_file=".env",  # Enable .env file loading
        env_parse_json=False,  # Disable trying to parse values as JSON
        env_file_override=True,  # Ensure environment variables take precedence
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

    @field_validator("CORS_ORIGINS", mode="after")
    @classmethod
    def parse_cors_origins(cls, v):
        """Convert string CORS_ORIGINS to list of hosts"""
        if isinstance(v, str):
            if v == "*":
                return ["*"]
            return [host.strip() for host in v.split(",") if host.strip()]
        return v

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Make paths absolute
        self.DATA_DIR = os.path.abspath(self.DATA_DIR)

        # Create directories if they don't exist
        Path(self.DATA_DIR).mkdir(parents=True, exist_ok=True)
        Path(self.FEEDBACK_DIR_PATH).mkdir(parents=True, exist_ok=True)


@lru_cache()
def get_settings():
    return Settings()
