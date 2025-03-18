import os
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import model_validator
from pydantic_settings import BaseSettings

# Get the api directory path
API_DIR = Path(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class Settings(BaseSettings):
    # API Configuration
    DEBUG: bool = False
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Bisq Support Assistant"

    # Security
    CORS_ORIGINS: List[str]
    
    # Web configuration (added to prevent validation errors)
    SERVER_IP: str = "127.0.0.1"
    NEXT_PUBLIC_API_URL: str = "/api"

    # OpenAI Configuration
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "o3-mini"
    MAX_TOKENS: int = 4096  # Default max tokens for LLM response length

    # xAI Configuration
    XAI_API_KEY: str = ""
    XAI_MODEL: str = "grok-1"

    # Bisq API Configuration
    BISQ_API_URL: str = "http://localhost:8082"

    # Model Configuration
    EMBEDDING_MODEL: str = "text-embedding-3-small"

    # Data paths - these will be relative to DATA_DIR
    DATA_DIR: str = "/app/api/data"  # Default for Docker, can be overridden for local dev
    VECTOR_STORE_PATH: str = "vectorstore"
    FAQ_OUTPUT_PATH: str = "extracted_faq.jsonl"
    SUPPORT_CHAT_EXPORT_PATH: str = "support_chat_export.csv"
    PROCESSED_CONVERSATIONS_PATH: str = "processed_conversations.json"

    # API settings
    API_DIR: str = str(Path(__file__).parent.parent.parent)

    # LLM Provider Selection
    # Options: "openai", "xai"
    LLM_PROVIDER: str = "openai"

    model_config = {
        "env_file": str(Path(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))) / ".env"),
        "case_sensitive": True,
        "validate_default": True,
    }

    @model_validator(mode='before')
    def set_defaults(cls, values):
        # Set default CORS_ORIGINS if not provided
        if 'CORS_ORIGINS' not in values or not values['CORS_ORIGINS']:
            values['CORS_ORIGINS'] = ["http://localhost:3000"]
        return values

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # For local development, if DATA_DIR is a relative path, make it absolute relative to API_DIR
        if not os.path.isabs(self.DATA_DIR):
            self.DATA_DIR = str(Path(self.API_DIR) / self.DATA_DIR)

        # Make data directory paths absolute
        self.VECTOR_STORE_PATH = str(Path(self.DATA_DIR) / self.VECTOR_STORE_PATH)
        self.FAQ_OUTPUT_PATH = str(Path(self.DATA_DIR) / self.FAQ_OUTPUT_PATH)
        self.SUPPORT_CHAT_EXPORT_PATH = str(Path(self.DATA_DIR) / self.SUPPORT_CHAT_EXPORT_PATH)
        self.PROCESSED_CONVERSATIONS_PATH = str(Path(self.DATA_DIR) / self.PROCESSED_CONVERSATIONS_PATH)

        # Ensure data directories exist
        os.makedirs(self.DATA_DIR, exist_ok=True)
        for path in [self.VECTOR_STORE_PATH, self.FAQ_OUTPUT_PATH,
                     self.SUPPORT_CHAT_EXPORT_PATH, self.PROCESSED_CONVERSATIONS_PATH]:
            os.makedirs(os.path.dirname(path), exist_ok=True)


@lru_cache()
def get_settings() -> Settings:
    return Settings()
