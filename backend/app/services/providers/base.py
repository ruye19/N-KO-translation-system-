"""Provider abstraction.

Adding a provider means implementing this interface and registering it in
registry.py. Nothing outside the providers package should import a vendor SDK.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ProviderResult:
    text: str
    model: str
    warnings: list[str] = field(default_factory=list)


class TranslationProvider(ABC):
    #: Short stable identifier, e.g. "anthropic".
    name: str = "base"

    @abstractmethod
    def is_configured(self) -> bool:
        """True when credentials/config are present, without making a network call."""

    @abstractmethod
    def model_name(self) -> str:
        """The model this provider would use, for reporting."""

    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str) -> ProviderResult:
        """Run one completion.

        Implementations must raise a subclass of
        app.errors.TranslationError on any failure, never a raw SDK exception.
        """
