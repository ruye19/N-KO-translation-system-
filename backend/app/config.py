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
    gemini_model: str = Field(default="gemini-3.8-flash", alias="GEMINI_MODEL")
    gemini_max_tokens: int = Field(default=4096, alias="GEMINI_MAX_TOKENS")
    # Translation wants fidelity, not invention, so keep sampling low.
    gemini_temperature: float = Field(default=0.2, alias="GEMINI_TEMPERATURE")

    # At most one retry of a temporary Gemini failure (429, 500, 502, 503 or a
    # failed connection). 0 disables it; larger values are capped at 1.
    provider_max_retries: int = Field(default=1, alias="PROVIDER_MAX_RETRIES")
    provider_retry_delay_seconds: float = Field(default=1.0, alias="PROVIDER_RETRY_DELAY_SECONDS")
    # If the provider asks for a longer wait (Retry-After), do not retry at all.
    provider_retry_max_delay_seconds: float = Field(default=5.0, alias="PROVIDER_RETRY_MAX_DELAY_SECONDS")

    # --- Access control -----------------------------------------------------
    # Shared secret(s) callers send as "Authorization: Bearer <key>". Several
    # keys may be given, comma-separated, to rotate without downtime.
    translator_api_key: Optional[str] = Field(default=None, alias="TRANSLATOR_API_KEY")
    # Fail closed: with no key configured, translation requests are refused.
    # Set to false only for local development.
    require_api_key: bool = Field(default=True, alias="REQUIRE_API_KEY")

    # --- Rate limiting ------------------------------------------------------
    # Per client address, per worker process. 0 disables the limit.
    rate_limit_requests: int = Field(default=30, alias="RATE_LIMIT_REQUESTS")
    rate_limit_window_seconds: float = Field(default=60.0, alias="RATE_LIMIT_WINDOW_SECONDS")

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

    @property
    def translator_api_key_list(self) -> list[str]:
        return [k.strip() for k in (self.translator_api_key or "").split(",") if k.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
