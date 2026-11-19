"""Factory function for instantiating LLM providers."""

from typing import Optional
from app.core.config import settings
from app.services.llm.base import LLMProvider
from app.services.llm.groq_provider import GroqProvider
from app.services.llm.openrouter_provider import OpenRouterProvider


def get_llm_provider(
    provider_name: Optional[str] = None,
    **kwargs
) -> LLMProvider:
    """
    Factory to retrieve an LLM provider instance based on application configuration.

    Supports:
    - 'groq': GroqProvider
    - 'openrouter': OpenRouterProvider

    Args:
        provider_name: Override configured provider name ('groq', 'openrouter').
        **kwargs: Additional parameters passed to the provider constructor.
    """
    raw_provider = provider_name or getattr(settings, "LLM_PROVIDER", None) or settings.DEFAULT_LLM_PROVIDER
    selected_provider = str(raw_provider).strip().lower()

    if selected_provider == "groq":
        return GroqProvider(**kwargs)

    if selected_provider == "openrouter":
        return OpenRouterProvider(**kwargs)

    raise ValueError(
        f"Unsupported LLM provider: '{selected_provider}'. Supported providers: 'groq', 'openrouter'."
    )
