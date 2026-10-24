"""Translation error taxonomy.

Each error carries a stable machine-readable `code` so the frontend can show a
useful message, plus an HTTP status. Provider exception details are never
forwarded verbatim to the client, because they can contain request metadata.
"""


class TranslationError(Exception):
    code = "translation_error"
    http_status = 502
    message = "Translation failed."

    def __init__(self, message: str | None = None):
        self.message = message or self.__class__.message
        super().__init__(self.message)


class ProviderNotConfiguredError(TranslationError):
    code = "provider_not_configured"
    http_status = 503
    message = (
        "The translation provider is not configured. Set ANTHROPIC_API_KEY in "
        "backend/.env and restart the server. See README.md for setup steps."
    )


class ProviderUnknownError(TranslationError):
    code = "provider_unknown"
    http_status = 500
    message = "The configured translation provider is not recognised."


class ProviderAuthError(TranslationError):
    code = "provider_auth_failed"
    http_status = 502
    message = (
        "The translation provider rejected the API key. Check ANTHROPIC_API_KEY "
        "in backend/.env: an Anthropic API key starts with 'sk-ant-'. A Claude "
        "Pro/Max subscription or a CLI login is not an API key -- create one at "
        "console.anthropic.com under API keys, then restart the server."
    )


class ProviderRateLimitError(TranslationError):
    code = "provider_rate_limited"
    http_status = 429
    message = "The translation provider is rate limiting requests. Try again shortly."


class ProviderTimeoutError(TranslationError):
    code = "provider_timeout"
    http_status = 504
    message = "The translation provider did not respond in time. Try again."


class ProviderUnavailableError(TranslationError):
    code = "provider_unavailable"
    http_status = 502
    message = "The translation provider is temporarily unavailable. Try again."


class ProviderRefusedError(TranslationError):
    code = "provider_refused"
    http_status = 422
    message = "The translation provider declined to translate this text."


class EmptyTranslationError(TranslationError):
    code = "empty_translation"
    http_status = 502
    message = "The translation provider returned no usable text."
