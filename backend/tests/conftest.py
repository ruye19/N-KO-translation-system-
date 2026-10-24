import os
import sys
from pathlib import Path

import pytest

# Make `app` importable when pytest runs from the repo root or backend/.
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# Isolate the suite from the developer's backend/.env.
#
# Environment variables take precedence over .env in pydantic-settings, so
# setting these to empty neutralises whatever the developer has configured
# locally. Without this the tests would read a real key and make live,
# billable API calls -- which a test suite must never do.
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["TRANSLATION_PROVIDER"] = "anthropic"

from app.config import Settings  # noqa: E402
from app.dependencies import get_translation_service  # noqa: E402
from app.main import app  # noqa: E402
from app.services.providers.base import ProviderResult, TranslationProvider  # noqa: E402
from app.services.translation import TranslationService  # noqa: E402


class FakeProvider(TranslationProvider):
    """Stand-in provider. Returns canned text or raises a chosen error."""

    name = "fake"

    def __init__(self, *, configured=True, result=None, error=None, model="fake-model-1"):
        self._configured = configured
        self._result = result
        self._error = error
        self._model = model
        self.calls = []

    def is_configured(self):
        return self._configured

    def model_name(self):
        return self._model

    def complete(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        if self._error is not None:
            raise self._error
        return ProviderResult(text=self._result, model=self._model)


def build_service(provider) -> TranslationService:
    settings = Settings(_env_file=None, ANTHROPIC_API_KEY=None)
    service = TranslationService(settings)
    service._provider = provider
    return service


@pytest.fixture
def client():
    """TestClient with no dependency overrides (provider unconfigured)."""
    from fastapi.testclient import TestClient

    app.dependency_overrides.clear()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def client_with_provider():
    """Factory: give it a FakeProvider, get a TestClient wired to it."""
    from fastapi.testclient import TestClient

    created = []

    def _make(provider):
        service = build_service(provider)
        app.dependency_overrides[get_translation_service] = lambda: service
        c = TestClient(app)
        created.append(c)
        return c

    yield _make
    app.dependency_overrides.clear()
    for c in created:
        c.close()


def test_suite_is_isolated_from_local_env_file():
    """Guard: the suite must never pick up a real key from backend/.env."""
    from app.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    assert not settings.anthropic_api_key, (
        "Tests are reading a real ANTHROPIC_API_KEY. They must stay offline."
    )
    assert not settings.gemini_api_key, (
        "Tests are reading a real GEMINI_API_KEY. They must stay offline."
    )
