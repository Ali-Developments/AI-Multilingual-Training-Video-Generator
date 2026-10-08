"""Groq LLM provider implementation adhering to vendor abstraction."""

import json
import time
from typing import Type, TypeVar, Optional, Any
from groq import Groq, APIError, RateLimitError, APIConnectionError, AuthenticationError
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.logging import logger
from app.services.llm.base import LLMProvider

T = TypeVar("T", bound=BaseModel)


class GroqProvider(LLMProvider):
    """
    Groq LLM provider implementation.
    
    CRITICAL: The underlying model is strictly configuration-driven.
    No model ID is hardcoded in this implementation.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_retries: int = 5,
        retry_backoff_factor: float = 1.5,
        client: Optional[Any] = None
    ) -> None:
        """
        Initialize GroqProvider.
        
        Args:
            api_key: Groq API key (defaults to settings.GROQ_API_KEY).
            model: Active Groq model ID (defaults to settings.GROQ_MODEL).
                   MUST NOT be hardcoded here.
            max_retries: Maximum number of retry attempts for transient errors.
            retry_backoff_factor: Multiplier for exponential backoff delay.
            client: Optional pre-configured Groq client (useful for dependency injection/testing).
        """
        self._api_key = api_key or settings.GROQ_API_KEY
        self._model = model or settings.GROQ_MODEL
        self.max_retries = max_retries
        self.retry_backoff_factor = retry_backoff_factor

        if client is not None:
            self._client = client
        elif self._api_key:
            self._client = Groq(api_key=self._api_key)
        else:
            self._client = None

        logger.info(
            "Initialized GroqProvider with configured model: %s (Max retries: %d)",
            self._model,
            self.max_retries
        )

    @property
    def model_name(self) -> str:
        """Return the actively configured model ID."""
        return self._model

    def _get_client(self) -> Groq:
        """Retrieve or lazily initialize the Groq client."""
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ValueError(
                "Missing GROQ_API_KEY. Provide it in constructor or set GROQ_API_KEY in .env."
            )
        self._client = Groq(api_key=self._api_key)
        return self._client

    def _execute_with_retry(self, api_call_fn):
        """Execute a Groq API call with exponential backoff on retryable errors."""
        import re
        last_exception = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return api_call_fn()
            except RateLimitError as e:
                last_exception = e
                # Check if Groq suggested a specific wait time (e.g. 'try again in 8.28s')
                delay = max(4.0, (self.retry_backoff_factor ** attempt) * 2.0)
                match = re.search(r"try again in ([\d\.]+)s", str(e))
                if match:
                    try:
                        delay = max(delay, float(match.group(1)) + 2.0)
                    except ValueError:
                        pass
                logger.warning(
                    "Groq RateLimitError on attempt %d/%d (model: %s). Backing off for %.2fs: %s",
                    attempt, self.max_retries, self._model, delay, str(e)
                )
                time.sleep(delay)
            except APIConnectionError as e:
                last_exception = e
                delay = max(2.0, (self.retry_backoff_factor ** attempt))
                logger.warning(
                    "Groq APIConnectionError on attempt %d/%d. Backing off for %.2fs: %s",
                    attempt, self.max_retries, delay, str(e)
                )
                time.sleep(delay)
            except AuthenticationError as e:
                logger.error("Groq AuthenticationError: Invalid API key. Non-retryable: %s", str(e))
                raise
            except APIError as e:
                err_dict = getattr(e, "body", {}) or {}
                err_code = err_dict.get("error", {}).get("code", "") if isinstance(err_dict, dict) else ""
                # json_validate_failed with empty generation is a known transient Groq rate/queue artifact
                is_transient_json_fail = (
                    err_code == "json_validate_failed"
                    and not err_dict.get("error", {}).get("failed_generation")
                )
                if getattr(e, "status_code", 0) >= 500 or is_transient_json_fail:
                    last_exception = e
                    delay = max(3.5, (self.retry_backoff_factor ** attempt) * 2.0)
                    logger.warning(
                        "Groq transient error (%s / %s) on attempt %d/%d. Backing off for %.2fs: %s",
                        getattr(e, "status_code", "unknown"), err_code or "transient", attempt, self.max_retries, delay, str(e)
                    )
                    time.sleep(delay)
                else:
                    logger.error("Groq non-retryable APIError: %s", str(e))
                    raise
            except Exception as e:
                logger.error("Unexpected error during Groq API execution: %s", str(e))
                raise

        raise RuntimeError(
            f"Groq API call failed after {self.max_retries} attempts with model '{self._model}'."
        ) from last_exception

    def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> str:
        """Generate unstructured text using the configured Groq model."""
        client = self._get_client()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        def _call():
            params = {
                "model": self._model,
                "messages": messages,
                "temperature": temperature,
            }
            if max_tokens:
                params["max_tokens"] = max_tokens
            response = client.chat.completions.create(**params)
            return response.choices[0].message.content

        return self._execute_with_retry(_call)

    def generate_structured(
        self,
        prompt: str,
        schema: Type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = 4096,
    ) -> T:
        """
        Generate structured output adhering to a Pydantic schema using JSON mode.
        """
        client = self._get_client()

        schema_json = json.dumps(schema.model_json_schema(), indent=2)
        augmented_system_prompt = (
            f"{system_prompt or 'You are a helpful assistant.'}\n\n"
            f"You MUST output ONLY a valid JSON object matching this JSON Schema:\n{schema_json}\n\n"
            "Ensure the JSON object includes all required fields and complete scenes. Do not omit or truncate any arrays."
        )

        messages = [
            {"role": "system", "content": augmented_system_prompt},
            {"role": "user", "content": prompt}
        ]

        def _call():
            params = {
                "model": self._model,
                "messages": messages,
                "temperature": temperature,
                "response_format": {"type": "json_object"},
            }
            if max_tokens:
                params["max_tokens"] = max_tokens
            response = client.chat.completions.create(**params)
            choice = response.choices[0]
            if choice.finish_reason == "length":
                logger.warning(
                    "Groq structured response was truncated by max_tokens limit (model: %s).",
                    self._model
                )
            raw_content = choice.message.content
            return raw_content

        raw_json_str = self._execute_with_retry(_call)

        try:
            parsed_data = json.loads(raw_json_str)
            return schema.model_validate(parsed_data)
        except (json.JSONDecodeError, ValidationError) as err:
            logger.error("Failed to parse structured response from Groq (model: %s): %s", self._model, err)
            raise ValueError(
                f"Groq output could not be validated against {schema.__name__}: {err}\nRaw output: {raw_json_str}"
            ) from err
