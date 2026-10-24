"""N'Ko Translator API.

Run from the backend/ directory:
    uvicorn app.main:app --reload --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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

    yield


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
    allow_headers=["Content-Type"],
)

app.include_router(health.router, prefix="/api")
app.include_router(translate.router, prefix="/api")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Normalise every error into {"error": {"code", "message"}}."""
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        body = {"error": {"code": detail["code"], "message": detail.get("message", "")}}
    else:
        body = {"error": {"code": "http_error", "message": str(detail)}}
    return JSONResponse(status_code=exc.status_code, content=body)


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
