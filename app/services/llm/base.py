"""Abstract base class defining the LLM provider interface."""

from abc import ABC, abstractmethod
from typing import Type, TypeVar, Optional, List
from pydantic import BaseModel
from app.models.schemas import ScriptDraft
from app.services.llm.prompts import (
    SYSTEM_PROMPT_EDUCATIONAL_SCRIPT,
    build_script_generation_prompt,
)

T = TypeVar("T", bound=BaseModel)


class LLMProvider(ABC):
    """Abstract interface for LLM services ensuring vendor-agnostic architecture."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the name or identifier of the active underlying model."""
        pass

    @abstractmethod
    def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> str:
        """Generate unstructured text from a prompt."""
        pass

    @abstractmethod
    def generate_structured(
        self,
        prompt: str,
        schema: Type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2
    ) -> T:
        """Generate a validated Pydantic model response from an LLM prompt."""
        pass

    def generate_script_draft(
        self,
        topic: str,
        target_audience: str = "General Professional / Adult Learner",
        duration_minutes: int = 2,
        learning_objectives: Optional[List[str]] = None,
        language: str = "en-US",
        temperature: float = 0.2
    ) -> ScriptDraft:
        """Generate a structured educational script draft using the provider."""
        prompt = build_script_generation_prompt(
            topic=topic,
            target_audience=target_audience,
            duration_minutes=duration_minutes,
            learning_objectives=learning_objectives,
            language=language
        )
        return self.generate_structured(
            prompt=prompt,
            schema=ScriptDraft,
            system_prompt=SYSTEM_PROMPT_EDUCATIONAL_SCRIPT,
            temperature=temperature
        )
