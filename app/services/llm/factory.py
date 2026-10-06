"""Factory function for instantiating LLM providers."""

from typing import Optional
from app.core.config import settings
from app.services.llm.base import LLMProvider
from app.services.llm.groq_provider import GroqProvider


def get_llm_provider(
    provider_name: Optional[str] = None,
    **kwargs
) -> LLMProvider:
    """
    Factory to retrieve an LLM provider instance based on application configuration.
    
    Args:
        provider_name: Override default provider name ('groq', etc.).
        **kwargs: Additional parameters passed to the provider constructor.
    """
    selected_provider = (provider_name or settings.DEFAULT_LLM_PROVIDER).lower()

    if selected_provider == "groq":
        return GroqProvider(**kwargs)
    
    raise ValueError(f"Unsupported LLM provider: '{selected_provider}'")
