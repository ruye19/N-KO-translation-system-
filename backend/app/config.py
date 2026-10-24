"""Application configuration, loaded from environment variables / .env.

No secret ever has a default value here. A missing API key is a valid state:
the app must still start, and only fail when a translation is actually requested.
"""

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Provider selection -------------------------------------------------
    translation_provider: str = Field(default="anthropic", alias="TRANSLATION_PROVIDER")

    # --- Anthropic ----------------------------------------------------------
    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-opus-5", alias="ANTHROPIC_MODEL")
    anthropic_max_tokens: int = Field(default=4096, alias="ANTHROPIC_MAX_TOKENS")
    # "low" | "medium" | "high" | "xhigh" | "max" -- controls how much the model
    # deliberates. "medium" keeps a translation endpoint responsive and cheap.
    anthropic_effort: str = Field(default="medium", alias="ANTHROPIC_EFFORT")
    request_timeout_seconds: float = Field(default=60.0, alias="REQUEST_TIMEOUT_SECONDS")

    # --- Google Gemini ------------------------------------------------------
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-pro", alias="GEMINI_MODEL")
    gemini_max_tokens: int = Field(default=4096, alias="GEMINI_MAX_TOKENS")
    # Translation wants fidelity, not invention, so keep sampling low.
    gemini_temperature: float = Field(default=0.2, alias="GEMINI_TEMPERATURE")

    # --- Input limits -------------------------------------------------------
    max_input_chars: int = Field(default=5000, alias="MAX_INPUT_CHARS")

    # --- Dictionary ---------------------------------------------------------
    # Disabled by default. When DICTIONARY_ENABLED=true and data/dictionary.sqlite
    # exists, French headwords are retrieved as unverified reference context.
    # N'Ko equivalents remain unverified pending legacy font encoding resolution.
    dictionary_enabled: bool = Field(default=False, alias="DICTIONARY_ENABLED")
    dictionary_db_path: Optional[str] = Field(default=None, alias="DICTIONARY_DB_PATH")

    # --- CORS ---------------------------------------------------------------
    # Comma-separated list of origins allowed to call this API.
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="CORS_ORIGINS",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
