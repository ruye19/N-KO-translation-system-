"""N'Ko Translator API.

Run from the backend/ directory:
    uvicorn app.main:app --reload --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.routers import health, translate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Report provider configuration at startup. Never logs the key itself."""
    from app.dependencies import get_translation_service

    service = get_translation_service()
    if service.provider_configured():
        logger.info(
            "Translation provider '%s' configured (model: %s).",
            service.provider_name,
            service.model_name(),
        )
        provider = settings.translation_provider.strip().lower()
        if provider == "anthropic":
            from app.services.providers.anthropic_provider import looks_like_anthropic_key

            if not looks_like_anthropic_key(settings.anthropic_api_key):
                logger.warning(
                    "ANTHROPIC_API_KEY does not look like an Anthropic API key "
                    "(expected it to start with 'sk-ant-'). If translation fails "
                    "with an authentication error, create an API key at "
                    "console.anthropic.com under API keys. A Claude subscription "
                    "or CLI login is not an API key."
                )
        elif provider == "gemini":
            from app.services.providers.gemini_provider import looks_like_gemini_key

            if not looks_like_gemini_key(settings.gemini_api_key):
                logger.warning(
                    "GEMINI_API_KEY does not look like a Google AI Studio API key "
                    "(expected it to start with 'AIza'). A token starting 'AQ.' is "
                    "a short-lived ephemeral token and will expire. Create a key "
                    "at aistudio.google.com/apikey."
                )

    _report_access_settings()
    yield


def _report_access_settings() -> None:
    """Say how translation requests are protected. Never logs a key."""
    from app.security import MIN_KEY_LENGTH

    keys = settings.translator_api_key_list
    if not settings.require_api_key:
        logger.warning(
            "REQUIRE_API_KEY=false: /api/translate accepts requests without an "
            "access key. Use this only for local development."
        )
    elif not keys:
        logger.warning(
            "TRANSLATOR_API_KEY is not set, so /api/translate will refuse every "
            "request. Set it, or set REQUIRE_API_KEY=false for local development."
        )
    elif any(len(k) < MIN_KEY_LENGTH for k in keys):
        logger.warning(
            "TRANSLATOR_API_KEY is shorter than %d characters. Generate a longer "
            "random key (see docs/API_INTEGRATION.md).",
            MIN_KEY_LENGTH,
        )
    if settings.rate_limit_requests > 0:
        logger.info(
            "Rate limit: %d translation requests per %g seconds per client address.",
            settings.rate_limit_requests,
            settings.rate_limit_window_seconds,
        )
    else:
        logger.warning("RATE_LIMIT_REQUESTS=0: translation requests are not rate limited.")


app = FastAPI(
    title="N'Ko Translator API",
    version="0.1.0",
    lifespan=lifespan,
    description=(
        "AI-assisted translation between English, French and N'Ko. "
        "Results are not human-verified."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    # Authorization is deliberately not allowed: the access key must never be
    # placed in a browser, so keyed calls come from a server, where CORS does
    # not apply.
    allow_headers=["Content-Type"],
    expose_headers=["Retry-After"],
)

app.include_router(health.router, prefix="/api")
app.include_router(translate.router, prefix="/api")


_STATUS_CODES = {404: "not_found", 405: "method_not_allowed"}


# Registered for Starlette's HTTPException so that routing errors (404, 405)
# get the same envelope as the API's own errors; FastAPI's HTTPException is a
# subclass and is covered too.
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Normalise every error into {"error": {"code", "message"}}."""
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        body = {"error": {"code": detail["code"], "message": detail.get("message", "")}}
    else:
        body = {"error": {"code": _STATUS_CODES.get(exc.status_code, "http_error"), "message": str(detail)}}
    return JSONResponse(status_code=exc.status_code, content=body, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Malformed request body: same envelope, status 422. The client's input is
    never echoed back."""
    problems = []
    for err in exc.errors():
        if err.get("type") == "json_invalid":
            problems = ["the request body is not valid JSON"]
            break
        field = ".".join(str(p) for p in err.get("loc", ()) if p != "body") or "body"
        problems.append(f"{field}: {err.get('msg', 'invalid')}")
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "invalid_request", "message": "Invalid request: " + "; ".join(problems[:5]) + "."}},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Log the traceback server-side; return nothing internal to the client.
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "Something went wrong on the server.",
            }
        },
    )


@app.get("/")
def root():
    return {
        "name": "N'Ko Translator API",
        "docs": "/docs",
        "health": "/api/health",
        "translate": "POST /api/translate",
    }
