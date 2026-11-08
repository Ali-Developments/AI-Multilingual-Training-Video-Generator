"""Groq LLM provider implementation adhering to vendor abstraction."""

import json
import re
import time
from typing import Type, TypeVar, Optional, Any, Dict
from groq import Groq, APIError, RateLimitError, APIConnectionError, AuthenticationError
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.logging import logger
from app.services.llm.base import LLMProvider
from app.services.llm.schema_utils import to_strict_json_schema

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
        """Execute a Groq API call with exponential backoff on retryable errors and rate limits."""
        last_exception = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return api_call_fn()
            except RateLimitError as e:
                last_exception = e
                delay = max(4.0, (self.retry_backoff_factor ** attempt) * 2.0)

                # Inspect provider response headers if available
                resp = getattr(e, "response", None)
                headers = getattr(resp, "headers", {}) or {}
                retry_after = headers.get("retry-after") or headers.get("Retry-After")
                reset_tokens = headers.get("x-ratelimit-reset-tokens") or headers.get("X-RateLimit-Reset-Tokens")
                rem_tokens = headers.get("x-ratelimit-remaining-tokens") or headers.get("X-RateLimit-Remaining-Tokens")

                if retry_after:
                    try:
                        delay = max(delay, float(retry_after) + 1.0)
                    except (ValueError, TypeError):
                        pass
                elif reset_tokens:
                    try:
                        val_str = str(reset_tokens).strip().lower()
                        if val_str.endswith("ms"):
                            delay = max(delay, (float(val_str[:-2]) / 1000.0) + 1.0)
                        elif val_str.endswith("s"):
                            delay = max(delay, float(val_str[:-1]) + 1.0)
                        elif val_str.endswith("m"):
                            delay = max(delay, (float(val_str[:-1]) * 60.0) + 1.0)
                        else:
                            delay = max(delay, float(val_str) + 1.0)
                    except (ValueError, TypeError):
                        pass

                # Check regex in error message as secondary source
                match = re.search(r"try again in ([\d\.]+)s", str(e))
                if match:
                    try:
                        delay = max(delay, float(match.group(1)) + 1.5)
                    except ValueError:
                        pass

                logger.warning(
                    "Groq RateLimitError on attempt %d/%d (model: %s, remaining_tokens: %s). Backing off for %.2fs: %s",
                    attempt, self.max_retries, self._model, rem_tokens or "unknown", delay, str(e)
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
                
                # json_validate_failed is non-retryable by identical payload; propagate to let caller fallback
                if err_code == "json_validate_failed" or "json_validate_failed" in str(e):
                    logger.warning("Groq json_validate_failed received; letting caller execute controlled fallback.")
                    raise

                if getattr(e, "status_code", 0) >= 500:
                    last_exception = e
                    delay = max(3.5, (self.retry_backoff_factor ** attempt) * 2.0)
                    logger.warning(
                        "Groq transient 5xx error (%s) on attempt %d/%d. Backing off for %.2fs: %s",
                        getattr(e, "status_code", "5xx"), attempt, self.max_retries, delay, str(e)
                    )
                    time.sleep(delay)
                else:
                    logger.error("Groq non-retryable APIError (%s): %s", err_code or getattr(e, "status_code", "unknown"), str(e))
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
        reasoning_effort: Optional[str] = None,
        **kwargs: Any,
    ) -> T:
        """
        Generate structured output adhering to a Pydantic schema using strict json_schema,
        with bounded fallback to json_object mode on json_validate_failed.
        """
        client = self._get_client()

        # Attempt 1: Strict JSON Schema mode
        strict_schema = to_strict_json_schema(schema)
        messages = [
            {"role": "system", "content": system_prompt or "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ]

        def _call_strict():
            params: Dict[str, Any] = {
                "model": self._model,
                "messages": messages,
                "temperature": temperature,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema.__name__,
                        "strict": True,
                        "schema": strict_schema,
                    },
                },
            }
            if max_tokens:
                params["max_tokens"] = max_tokens
            if reasoning_effort:
                params["reasoning_effort"] = reasoning_effort
            response = client.chat.completions.create(**params)
            choice = response.choices[0]
            if choice.finish_reason == "length":
                logger.warning(
                    "Groq structured response was truncated by max_tokens limit (model: %s).",
                    self._model
                )
            return choice.message.content

        try:
            raw_json_str = self._execute_with_retry(_call_strict)
            parsed_data = json.loads(raw_json_str)
            return schema.model_validate(parsed_data)
        except APIError as api_err:
            err_dict = getattr(api_err, "body", {}) or {}
            err_code = err_dict.get("error", {}).get("code", "") if isinstance(err_dict, dict) else ""
            if err_code == "json_validate_failed" or "json_validate_failed" in str(api_err):
                logger.warning(
                    "Groq strict mode returned json_validate_failed for '%s'. Executing Attempt 2 (json_object fallback).",
                    schema.__name__
                )
                return self._fallback_json_object(
                    prompt=prompt,
                    schema=schema,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    reasoning_effort=reasoning_effort,
                )
            # Unrelated 400 or other API errors must NOT trigger fallback
            logger.error("Groq APIError in strict mode (%s): %s", err_code or getattr(api_err, "status_code", "unknown"), api_err)
            raise
        except (json.JSONDecodeError, ValidationError) as parse_err:
            logger.warning(
                "Local validation failed on strict output for '%s': %s. Executing Attempt 2 (json_object fallback).",
                schema.__name__, parse_err
            )
            return self._fallback_json_object(
                prompt=prompt,
                schema=schema,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
            )

    def _fallback_json_object(
        self,
        prompt: str,
        schema: Type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = 4096,
        reasoning_effort: Optional[str] = None,
    ) -> T:
        """Attempt 2: Fallback to json_object mode with explicit JSON prompt and local validation."""
        client = self._get_client()
        schema_json = json.dumps(schema.model_json_schema(), indent=2)
        augmented_system_prompt = (
            f"{system_prompt or 'You are a helpful assistant.'}\n\n"
            f"You MUST output ONLY a valid JSON object matching this JSON Schema:\n{schema_json}\n\n"
            "Ensure the JSON object includes all required fields. Output raw JSON only with no conversational text or markdown formatting."
        )

        messages = [
            {"role": "system", "content": augmented_system_prompt},
            {"role": "user", "content": prompt}
        ]

        def _call_json_obj():
            params: Dict[str, Any] = {
                "model": self._model,
                "messages": messages,
                "temperature": temperature,
                "response_format": {"type": "json_object"},
            }
            if max_tokens:
                params["max_tokens"] = max_tokens
            if reasoning_effort:
                params["reasoning_effort"] = reasoning_effort
            response = client.chat.completions.create(**params)
            return response.choices[0].message.content

        raw_json_str = self._execute_with_retry(_call_json_obj)

        try:
            parsed_data = json.loads(raw_json_str)
            return schema.model_validate(parsed_data)
        except (json.JSONDecodeError, ValidationError) as val_err:
            logger.warning(
                "Local validation failed on json_object fallback for '%s': %s. Executing bounded repair attempt.",
                schema.__name__, val_err
            )
            return self._repair_json_output(
                prompt=prompt,
                schema=schema,
                previous_output=raw_json_str,
                validation_error=str(val_err),
                system_prompt=augmented_system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
            )

    def _repair_json_output(
        self,
        prompt: str,
        schema: Type[T],
        previous_output: str,
        validation_error: str,
        system_prompt: str,
        temperature: float = 0.2,
        max_tokens: Optional[int] = 4096,
        reasoning_effort: Optional[str] = None,
    ) -> T:
        """One single repair attempt using validation error feedback."""
        client = self._get_client()
        repair_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": previous_output},
            {
                "role": "user",
                "content": (
                    f"The previous JSON output failed validation with the following error:\n{validation_error}\n\n"
                    "Please output the corrected JSON object strictly conforming to the required schema."
                ),
            },
        ]

        def _call_repair():
            params: Dict[str, Any] = {
                "model": self._model,
                "messages": repair_messages,
                "temperature": temperature,
                "response_format": {"type": "json_object"},
            }
            if max_tokens:
                params["max_tokens"] = max_tokens
            if reasoning_effort:
                params["reasoning_effort"] = reasoning_effort
            response = client.chat.completions.create(**params)
            return response.choices[0].message.content

        repaired_str = self._execute_with_retry(_call_repair)
        try:
            parsed = json.loads(repaired_str)
            return schema.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError) as final_err:
            logger.error("Repaired JSON output still failed validation for '%s': %s", schema.__name__, final_err)
            raise ValueError(
                f"Groq output validation failed for {schema.__name__} after repair attempt: {final_err}\nRaw: {repaired_str}"
            ) from final_err
