"""OpenRouter LLM provider implementation adhering to the LLMProvider abstraction."""

import json
import re
import threading
import time
from contextlib import contextmanager
from copy import copy
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar
import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.logging import logger
from app.services.llm.base import LLMProvider
from app.services.llm.schema_utils import (
    build_json_instance_template,
    compact_messages_for_token_limit,
    contains_placeholder_syntax,
    extract_json_payload,
    is_json_schema_echo,
    to_compact_json_schema_str,
    to_strict_json_schema,
    validate_structured_instance,
)

T = TypeVar("T", bound=BaseModel)


class OpenRouterError(RuntimeError):
    """Base exception for OpenRouter API errors."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        error_code: Optional[str] = None,
        body: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.body = body
        self.headers = headers or {}


class OpenRouterAuthenticationError(OpenRouterError):
    """Raised on HTTP 401 authentication failure (non-retryable)."""


class OpenRouterInsufficientCreditsError(OpenRouterError):
    """Raised on HTTP 402 insufficient credits / quota failure (non-retryable)."""


class OpenRouterPayloadTooLargeError(OpenRouterError):
    """Raised on HTTP 413 oversized request / context length limit (never retried unchanged)."""


class OpenRouterRateLimitError(OpenRouterError):
    """Raised on HTTP 429 rate limit exceeded (retryable with backoff)."""


class OpenRouterServerError(OpenRouterError):
    """Raised on HTTP 5xx upstream or OpenRouter gateway error (retryable with backoff)."""


class OpenRouterConnectionError(OpenRouterError):
    """Raised on network or request timeout error (retryable with backoff)."""


class OpenRouterDecodingError(OpenRouterError):
    """Raised when HTTP response decompression/decoding fails (corrupt/truncated compressed body)."""


class OpenRouterTimeoutError(OpenRouterError):
    """Raised when the overall script run wall-clock time limit is reached (distinct from explicit cancellation)."""


class OpenRouterCancelledError(OpenRouterError):
    """Raised when a script run is explicitly cancelled (distinct from wall-clock timeout)."""


class OpenRouterPaidModelBlockedError(OpenRouterError, PermissionError):
    """
    Raised before transport when a configured OpenRouter model or endpoint cannot be
    verified as zero-cost and paid-model authorization is disabled (fail-closed policy).
    """


class OpenRouterModelCompatibilityError(OpenRouterError, ValueError):
    """
    Raised when the selected OpenRouter model (e.g., a small/free model routed via openrouter/free)
    cannot produce a valid structured JSON instance even after a bounded repair attempt
    (for example, by echoing a JSON Schema definition or placeholder ellipses `{...}`).
    """

    #: Machine-readable diagnostic classification of the failure.
    classification: str = "invalid_structured_output"


class OpenRouterReasoningOnlyError(OpenRouterModelCompatibilityError):
    """
    Raised for structured generation when `message.content` is empty but `message.reasoning` is present
    and the model finished normally. Reasoning text is never accepted as the final structured response.
    """

    classification = "reasoning_only"


class OpenRouterTokenBudgetExhaustedError(OpenRouterModelCompatibilityError):
    """
    Raised for structured generation when `finish_reason='length'` and `message.content` is empty,
    i.e. the model spent its entire output budget on reasoning tokens before producing final content.
    JSON repair is pointless here (there is no JSON to repair), so it is never attempted.
    """

    classification = "reasoning_budget_exhausted"


class OpenRouterEmptyContentError(OpenRouterModelCompatibilityError):
    """Raised for structured generation when the model returned neither content nor reasoning."""

    classification = "empty_content"


class OpenRouterNoJsonError(OpenRouterModelCompatibilityError):
    classification = "non_json_final_content"


class OpenRouterUnavailableError(OpenRouterModelCompatibilityError):
    classification = "model_unavailable"


def _validation_summary(error: ValueError) -> str:
    if isinstance(error, ValidationError):
        return ", ".join(
            f"{'.'.join(map(str, issue['loc']))} ({issue['type']})"
            for issue in error.errors(include_input=False, include_url=False)[:6]
        )
    return str(error)


def supports_strict_json_schema(model_id: str) -> bool:
    """
    Determine whether an OpenRouter model identifier is likely to support strict
    OpenAI-style `response_format: {type: 'json_schema', json_schema: {strict: True}}`.

    Not all OpenRouter upstream providers support strict JSON Schema grammar decoding.
    Models with `:free` routing, Anthropic models, and reasoning-only endpoints
    typically require `json_object` or prompt-enforced JSON mode instead.
    """
    if not model_id:
        return False
    m = model_id.strip().lower()
    if m.endswith(":free") or m == "openrouter/free":
        return False
    for unsupported_marker in ("anthropic/", "claude", "deepseek-r1", "qwq", "Perplexity".lower()):
        if unsupported_marker in m:
            return False
    for supported_prefix in ("openai/", "google/gemini"):
        if m.startswith(supported_prefix):
            return True
    return False


def supports_json_object_mode(model_id: str) -> bool:
    """
    Determine whether an OpenRouter model supports `response_format: {type: 'json_object'}`.
    """
    if not model_id:
        return False
    m = model_id.strip().lower()
    if m == "openrouter/free" or m.endswith(":free"):
        return True
    if "deepseek-r1" in m or "qwq" in m or "nemotron" in m:
        return False
    return True


def _is_free_or_reasoning_model(model_id: Optional[str]) -> bool:
    """Heuristic: free-router, ':free', or known reasoning-heavy models that spend output budget on thinking."""
    m = (model_id or "").strip().lower()
    if not m:
        return False
    if m == "openrouter/free" or m.endswith(":free"):
        return True
    return any(marker in m for marker in ("nemotron", "deepseek-r1", "qwq", "flint", "liquid/"))


def _is_unsupported_response_format_error(err: OpenRouterError) -> bool:
    """Check if an API error indicates the model/provider does not support response_format / json_schema."""
    if err.status_code not in (400, 404, 422):
        return False
    msg = str(err).lower()
    keywords = (
        "response_format",
        "json_schema",
        "json_object",
        "structured",
        "json_validate_failed",
        "no endpoints found",
        "unsupported parameter",
        "not supported by this model",
    )
    return any(k in msg for k in keywords)


class OpenRouterProvider(LLMProvider):
    """
    OpenRouter LLM provider implementation compatible with the official
    https://openrouter.ai/api/v1 chat completions API.

    Features:
    - Configuration-driven model and base URL selection.
    - Capability-aware structured output generation (strict json_schema -> json_object -> prompt JSON + repair).
    - Safe handling for HTTP 401, 402, 413, 429, 5xx, and connection timeouts.
    - Never retries an HTTP 413 oversized request unchanged; performs at most one bounded compacted retry.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        max_retries: int = 4,
        retry_backoff_factor: float = 1.5,
        client: Optional[Any] = None,
        prefer_staged_script_generation: Optional[bool] = None,
        allow_paid_models: Optional[bool] = None,
    ) -> None:
        self._api_key = api_key or settings.OPENROUTER_API_KEY
        self._model = model or settings.OPENROUTER_MODEL
        self._base_url = (base_url or settings.OPENROUTER_BASE_URL).rstrip("/")
        self._timeout = timeout_seconds if timeout_seconds is not None else settings.OPENROUTER_TIMEOUT_SECONDS
        self.max_retries = max(1, min(4, max_retries))
        self._before_request: Optional[Callable[[], Any]] = None
        self._after_request: Optional[Callable[..., None]] = None
        self._reservation_id: Optional[str] = None
        self._deadline: Optional[float] = None
        self._cancel_event: Optional[threading.Event] = None
        self._run_control: Optional[Any] = None
        self._checkpoint = None
        self._allow_paid_models_override = allow_paid_models
        self.retry_backoff_factor = retry_backoff_factor
        self._client = client
        self._prefer_staged_override = prefer_staged_script_generation
        self._last_routed_model: Optional[str] = None
        self._last_finish_reason: Optional[str] = None
        self._last_usage: Dict[str, Any] = {}
        self._last_response_classification: Optional[str] = None
        self._last_reasoning_chars: int = 0
        # Configured primary model (self._model is the *active* model during candidate iteration)
        self._primary_model: str = self._model
        # Explicit models rejected as incompatible for structured output during this provider's lifetime.
        # The 'openrouter/free' router is never cached here because each call may route to a different model.
        self._incompatible_models: Dict[str, str] = {}

        logger.info(
            "Initialized OpenRouterProvider with configured model: %s (base_url: %s, max_retries: %d)",
            self._model,
            self._base_url,
            self.max_retries,
        )

    @property
    def model_name(self) -> str:
        """Return the configured primary OpenRouter model ID."""
        return self._primary_model

    @property
    def last_routed_model(self) -> Optional[str]:
        """Return the actual upstream model ID reported by OpenRouter in the most recent completion response."""
        return self._last_routed_model

    @property
    def last_finish_reason(self) -> Optional[str]:
        """Return the finish_reason reported by OpenRouter in the most recent completion response."""
        return self._last_finish_reason

    @property
    def last_usage(self) -> Dict[str, Any]:
        """Return the token usage dictionary reported by OpenRouter in the most recent completion response."""
        return dict(self._last_usage)

    @property
    def prefers_staged_script_generation(self) -> bool:
        """
        Return True when the configured OpenRouter model is a free/reasoning/smaller model
        (such as `openrouter/free` or `:free` models) that benefits from staged script generation.
        """
        if self._prefer_staged_override is not None:
            return self._prefer_staged_override
        return _is_free_or_reasoning_model(self._primary_model)

    @property
    def last_response_classification(self) -> Optional[str]:
        """
        Diagnostic classification of the most recent completion: 'content', 'truncated_content',
        'reasoning_only', 'reasoning_budget_exhausted', or 'empty_content'.
        """
        return self._last_response_classification

    @property
    def incompatible_models(self) -> Dict[str, str]:
        """Explicit models rejected for structured output during this provider's lifetime (model -> reason)."""
        return dict(self._incompatible_models)

    def _structured_model_candidates(self) -> List[str]:
        """Use only the configured model. Changing it requires an explicit configuration change."""
        return [self._primary_model]

    def _allow_paid_models(self) -> bool:
        if self._allow_paid_models_override is not None:
            return bool(self._allow_paid_models_override)
        return bool(getattr(settings, "OPENROUTER_ALLOW_PAID_MODELS", False))

    def _verified_free_models(self) -> set[str]:
        raw = getattr(settings, "OPENROUTER_VERIFIED_FREE_MODELS", "openrouter/free") or "openrouter/free"
        verified = {item.strip().lower() for item in str(raw).split(",") if item.strip()}
        verified.add("openrouter/free")
        return verified

    def assert_model_authorized(self, model_id: Optional[str] = None) -> None:
        """
        Fail-closed authorization gate executed BEFORE budget reservation and BEFORE transport.
        Refuses paid models, unverified endpoints, and unverified ':free' suffixes unless
        paid-model authorization is explicitly enabled.
        """
        target_model = (model_id or self._model or "").strip()
        lower_model = target_model.lower()
        if not lower_model:
            raise OpenRouterPaidModelBlockedError(
                "OpenRouter model ID is empty; dispatch refused.",
                error_code="model_not_authorized",
            )
        if self._allow_paid_models():
            return

        official_base = "https://openrouter.ai/api/v1"
        if self._base_url.rstrip("/").lower() != official_base:
            raise OpenRouterPaidModelBlockedError(
                f"OpenRouter endpoint '{self._base_url}' cannot be verified as zero-cost under the free-only policy "
                f"(expected '{official_base}'). Dispatch refused.",
                error_code="endpoint_not_authorized",
            )

        if lower_model == "openrouter/free":
            return

        verified = self._verified_free_models()
        if lower_model in verified and lower_model.endswith(":free"):
            return

        raise OpenRouterPaidModelBlockedError(
            f"Model '{target_model}' is not authorized for dispatch under the free-only policy. "
            "Free billing eligibility cannot be verified safely (paid models and unverified model IDs are blocked "
            "unless OPENROUTER_ALLOW_PAID_MODELS=true or the model is in OPENROUTER_VERIFIED_FREE_MODELS).",
            error_code="paid_model_blocked",
        )

    @contextmanager
    def script_session(
        self,
        before_request: Callable[[], Any],
        after_request: Optional[Callable[..., None]] = None,
        cancel_event: Optional[threading.Event] = None,
        run_control: Optional[Any] = None,
    ):
        """Isolate candidate selection, request accounting, deadline, and cancellation for one project's run."""
        run = copy(self)
        run._model = self._primary_model
        run._incompatible_models = {}
        run._before_request = before_request
        run._after_request = after_request
        run._reservation_id = None
        run._run_control = run_control
        run._cancel_event = run_control.cancel_event if run_control is not None else cancel_event
        run._deadline = (
            run_control.deadline_monotonic
            if run_control is not None
            else time.monotonic() + settings.OPENROUTER_SCRIPT_TIMEOUT_SECONDS
        )
        try:
            yield run
        finally:
            if self._client is None and run._client is not None:
                run._client.close()

    def _is_explicitly_cancelled(self) -> bool:
        if self._run_control is not None:
            return bool(self._run_control.is_cancelled())
        return bool(self._cancel_event is not None and self._cancel_event.is_set())

    def _remaining_seconds(self) -> float:
        if self._is_explicitly_cancelled():
            raise OpenRouterCancelledError(
                "Script run was explicitly cancelled.",
                error_code="script_cancelled",
            )
        if self._run_control is not None and self._run_control.is_timed_out():
            raise OpenRouterTimeoutError(
                f"Script time limit reached ({int(self._run_control.timeout_seconds)}s). "
                "Accepted stages were saved; retry this project's script stage to resume.",
                error_code="script_timeout",
            )
        if self._deadline is None:
            return self._timeout
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise OpenRouterTimeoutError(
                "Script time limit reached. Accepted stages were saved; retry this project's script stage to resume.",
                error_code="script_timeout",
            )
        return remaining

    def _sleep_before_retry(self, delay: float) -> None:
        if self._is_explicitly_cancelled():
            raise OpenRouterCancelledError(
                "Script run was explicitly cancelled.",
                error_code="script_cancelled",
            )
        if self._deadline is not None and delay >= self._remaining_seconds():
            raise OpenRouterTimeoutError(
                "Script time limit prevents another retry. Accepted stages were saved; resume this project later.",
                error_code="script_timeout",
            )
        time.sleep(delay)

    def _effective_structured_max_tokens(self, requested: Optional[int], compacted: bool) -> Optional[int]:
        """
        Reasoning tokens count against max_tokens before any final content is emitted. For free/reasoning
        models, raise the structured-output budget to OPENROUTER_REASONING_MIN_OUTPUT_TOKENS so a short JSON
        object is not starved by chain-of-thought. Compacted (post-413) requests keep their reduced cap.
        """
        if compacted:
            return min(requested or 4096, 2048)
        if _is_free_or_reasoning_model(self._model):
            floor = int(getattr(settings, "OPENROUTER_REASONING_MIN_OUTPUT_TOKENS", 8192) or 8192)
            return max(requested or 0, floor)
        return requested

    def _apply_structured_reasoning_controls(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply OpenRouter's unified `reasoning` controls for structured calls only when explicitly configured
        and only for explicitly named models. It is never sent to the 'openrouter/free' router, because adding
        a `reasoning` parameter could bias the router toward reasoning-capable endpoints.
        Explicit free models require endpoints that support the requested parameters.
        """
        effort = (getattr(settings, "OPENROUTER_REASONING_EFFORT", None) or "").strip().lower()
        if not effort or (self._model or "").strip().lower() == "openrouter/free":
            return params
        if effort not in ("none", "minimal", "low", "medium", "high"):
            logger.warning("Ignoring unsupported OPENROUTER_REASONING_EFFORT value: %r", effort)
            return params
        params["reasoning"] = {"effort": effort, "exclude": True}
        return params

    def _get_headers(self) -> Dict[str, str]:
        """Build standard OpenRouter HTTP request headers without logging secrets."""
        if not self._api_key:
            raise ValueError(
                "Missing OPENROUTER_API_KEY. Provide it in constructor or set OPENROUTER_API_KEY in .env."
            )
        headers: Dict[str, str] = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        site_url = getattr(settings, "OPENROUTER_SITE_URL", None)
        app_name = getattr(settings, "OPENROUTER_APP_NAME", None)
        if site_url:
            headers["HTTP-Referer"] = site_url
        if app_name:
            headers["X-Title"] = app_name
        return headers

    def _get_http_client(self) -> httpx.Client:
        """Return injected httpx.Client or create a configured client."""
        if self._client is not None:
            return self._client
        self._client = httpx.Client(timeout=httpx.Timeout(self._timeout))
        return self._client

    def _classify_and_raise_http_error(self, response: httpx.Response) -> None:
        """Inspect a non-200 HTTP response or embedded OpenRouter error payload and raise a typed OpenRouterError."""
        status_code = response.status_code
        headers = {k.lower(): v for k, v in (response.headers or {}).items()}
        body: Any = None
        err_msg = f"HTTP {status_code}"
        err_code = ""

        try:
            body = response.json()
            if isinstance(body, dict) and "error" in body:
                err_obj = body["error"]
                if isinstance(err_obj, dict):
                    err_msg = str(err_obj.get("message") or err_msg)
                    err_code = str(err_obj.get("code") or "")
                else:
                    err_msg = str(err_obj)
        except Exception:
            err_msg = (response.text or err_msg)[:500]

        lower_msg = err_msg.lower()
        # Upstream messages can quote prompts, failed generations and private reasoning.
        err_msg = "Request rejected by upstream."
        if any(marker in lower_msg for marker in ("response_format", "json_schema", "json_object", "unsupported parameter", "no endpoints found")):
            err_msg = "No endpoints found that support the requested response_format."
        limits = re.search(r"limit\s+(\d+),?\s+requested\s+(\d+)", lower_msg)
        if limits:
            err_msg = f"Token limit {limits[1]}, requested {limits[2]}."
        if status_code == 404:
            raise OpenRouterUnavailableError(
                f"OpenRouter has no available endpoint for '{self._model}' with the requested parameters (HTTP 404).",
                status_code=404,
            )

        if status_code == 401:
            raise OpenRouterAuthenticationError(
                f"OpenRouter authentication failed (HTTP 401): {err_msg}",
                status_code=401,
                error_code=err_code or "unauthorized",
                body=body,
                headers=headers,
            )

        if status_code == 402:
            raise OpenRouterInsufficientCreditsError(
                f"OpenRouter insufficient credits (HTTP 402): {err_msg}",
                status_code=402,
                error_code=err_code or "insufficient_credits",
                body=body,
                headers=headers,
            )

        if status_code == 413 or "request too large" in lower_msg or "context_length_exceeded" in lower_msg or (
            status_code == 400 and ("maximum context length" in lower_msg or "too many tokens" in lower_msg)
        ):
            raise OpenRouterPayloadTooLargeError(
                f"OpenRouter request payload or token count too large (HTTP {status_code}): {err_msg}",
                status_code=413 if status_code == 413 else status_code,
                error_code=err_code or "payload_too_large",
                body=body,
                headers=headers,
            )

        if status_code == 429:
            raise OpenRouterRateLimitError(
                f"OpenRouter rate limit exceeded (HTTP 429): {err_msg}",
                status_code=429,
                error_code=err_code or "rate_limit_exceeded",
                body=body,
                headers=headers,
            )

        if status_code >= 500:
            raise OpenRouterServerError(
                f"OpenRouter upstream server error (HTTP {status_code}): {err_msg}",
                status_code=status_code,
                error_code=err_code or f"http_{status_code}",
                body=body,
                headers=headers,
            )

        raise OpenRouterError(
            f"OpenRouter API error (HTTP {status_code}): {err_msg}",
            status_code=status_code,
            error_code=err_code or f"http_{status_code}",
            body=body,
            headers=headers,
        )

    def _post_chat_completion(self, payload: Dict[str, Any], structured: bool = False) -> str:
        self._last_routed_model = None
        self._last_finish_reason = None
        self._last_usage = {}
        self._last_response_classification = None
        self._reservation_id = None
        http_status: Optional[int] = None
        completed = False
        try:
            result = self._read_chat_completion(payload, structured)
            completed = True
            http_status = 200
            return result
        except OpenRouterError as err:
            http_status = getattr(err, "status_code", None)
            raise
        finally:
            if self._after_request and self._reservation_id:
                try:
                    self._after_request(
                        self._reservation_id,
                        "completed" if completed else "failed",
                        http_status=http_status,
                        routed_model=self._last_routed_model,
                        category=self._last_response_classification,
                    )
                except Exception as ledger_err:
                    logger.warning("Failed to record request outcome in ledger: %s", ledger_err)
            if self._checkpoint and self._reservation_id is not None:
                try:
                    self._checkpoint.http_event(self)
                except Exception as cp_err:
                    logger.warning("Failed to record HTTP telemetry event in checkpoint: %s", cp_err)

    def _read_chat_completion(self, payload: Dict[str, Any], structured: bool = False) -> str:
        """
        Send a single POST request to OpenRouter /chat/completions and return the final assistant
        `message.content`. `message.reasoning` is NEVER returned as the answer. When `structured=True`,
        empty-content responses are classified and raised as non-retryable compatibility errors.
        """
        # Fail-closed authorization check BEFORE budget reservation and BEFORE transport
        self.assert_model_authorized(payload.get("model") or self._model)

        headers = self._get_headers()
        client = self._get_http_client()
        endpoint = f"{self._base_url}/chat/completions"

        timeout = min(self._timeout, self._remaining_seconds())
        if self._before_request:
            res_id = self._before_request()
            self._reservation_id = str(res_id) if isinstance(res_id, str) and res_id else "reserved"

        request_timeout = httpx.Timeout(
            connect=min(10.0, timeout),
            read=timeout,
            write=min(10.0, timeout),
            pool=min(10.0, timeout),
        )
        request_deadline = time.monotonic() + timeout

        def _perform_http() -> httpx.Response:
            if isinstance(client, httpx.Client):
                with client.stream("POST", endpoint, headers=headers, json=payload, timeout=request_timeout) as incoming:
                    active_stream[0] = incoming
                    last_status[0] = incoming.status_code
                    last_encoding[0] = incoming.headers.get("content-encoding")
                    chunks = []
                    for chunk in incoming.iter_bytes():
                        if request_deadline - time.monotonic() <= 0:
                            raise httpx.ReadTimeout("Request wall-clock deadline reached.")
                        chunks.append(chunk)
                    # `incoming.iter_bytes()` already applied HTTPX's automatic Content-Encoding decoder.
                    # Strip encoding/length framing headers so constructing httpx.Response from already-decoded
                    # bytes does NOT trigger a second decompression pass (double decompression).
                    decoded_headers = httpx.Headers(
                        [
                            (k, v)
                            for k, v in incoming.headers.multi_items()
                            if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")
                        ]
                    )
                    return httpx.Response(
                        incoming.status_code,
                        headers=decoded_headers,
                        content=b"".join(chunks),
                        request=incoming.request,
                    )
            return client.post(endpoint, headers=headers, json=payload, timeout=timeout)

        # Enforce a real wall-clock watchdog so blocked transports cannot overrun `timeout`
        result_box: List[Optional[httpx.Response]] = [None]
        error_box: List[Optional[BaseException]] = [None]
        active_stream: List[Any] = [None]
        last_status: List[Optional[int]] = [None]
        last_encoding: List[Optional[str]] = [None]
        done = threading.Event()

        def _worker() -> None:
            try:
                result_box[0] = _perform_http()
            except BaseException as exc:  # noqa: BLE001
                error_box[0] = exc
            finally:
                done.set()

        try:
            worker = threading.Thread(target=_worker, name="openrouter-http-worker", daemon=True)
            worker.start()
            wait_deadline = time.monotonic() + max(0.001, timeout)
            while not done.is_set():
                if self._is_explicitly_cancelled():
                    stream_ref = active_stream[0]
                    if stream_ref is not None:
                        try:
                            stream_ref.close()
                        except Exception:
                            pass
                    raise OpenRouterCancelledError(
                        "Script run was explicitly cancelled during active HTTP request.",
                        error_code="script_cancelled",
                    )
                slice_wait = min(0.05, max(0.0, wait_deadline - time.monotonic()))
                if slice_wait <= 0:
                    break
                done.wait(timeout=slice_wait)
            if not done.is_set():
                # Immediately abort active stream best-effort and fail at the wall-clock boundary
                stream_ref = active_stream[0]
                if stream_ref is not None:
                    try:
                        stream_ref.close()
                    except Exception:
                        pass
                raise httpx.ReadTimeout(f"Request exceeded wall-clock deadline ({timeout:.3f}s).")
            if error_box[0] is not None:
                raise error_box[0]
            response = result_box[0]
            assert response is not None
            # Only reject an already-received response if explicitly cancelled (never discard a completed
            # HTTP 200 response solely because the run's wall-clock deadline expired milliseconds after arrival).
            if self._is_explicitly_cancelled():
                raise OpenRouterCancelledError(
                    "Script run was explicitly cancelled.",
                    error_code="script_cancelled",
                )
        except httpx.TimeoutException as exc:
            raise OpenRouterConnectionError(
                f"OpenRouter request timed out after {self._timeout}s: {exc}",
                error_code="timeout",
            ) from exc
        except httpx.DecodingError as exc:
            enc_info = f" (Content-Encoding={last_encoding[0]})" if last_encoding[0] else ""
            raise OpenRouterDecodingError(
                f"OpenRouter response decompression failed{enc_info}: {exc}",
                status_code=last_status[0],
                error_code="decoding_error",
            ) from exc
        except httpx.RequestError as exc:
            raise OpenRouterConnectionError(
                f"OpenRouter network connection error: {exc}",
                error_code="connection_error",
            ) from exc

        if response.status_code >= 400:
            self._classify_and_raise_http_error(response)

        try:
            data = response.json()
        except Exception as exc:
            raise OpenRouterServerError(
                f"OpenRouter returned malformed JSON response (HTTP {response.status_code}): {exc}",
                status_code=response.status_code,
            ) from exc

        # OpenRouter may occasionally embed an upstream error object inside a 200 payload
        if isinstance(data, dict) and "error" in data and "choices" not in data:
            err_obj = data["error"]
            code = int(err_obj.get("code", 500)) if isinstance(err_obj, dict) and str(err_obj.get("code", "")).isdigit() else 502
            msg = err_obj.get("message", str(err_obj)) if isinstance(err_obj, dict) else str(err_obj)
            synth_resp = httpx.Response(
                status_code=code if code >= 400 else 502,
                json={"error": {"code": code, "message": msg}},
                request=httpx.Request("POST", endpoint),
            )
            self._classify_and_raise_http_error(synth_resp)

        choices = data.get("choices") if isinstance(data, dict) else None
        if not choices or not isinstance(choices, list):
            raise OpenRouterServerError(
                f"OpenRouter response missing 'choices' array for model '{self._model}'.",
                status_code=502,
                body=data,
            )

        routed_model = (data.get("model") if isinstance(data, dict) else None) or self._model
        self._last_routed_model = str(routed_model)
        usage = data.get("usage") if isinstance(data, dict) and isinstance(data.get("usage"), dict) else {}
        self._last_usage = {key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                            if isinstance(usage.get(key), int)}
        details = usage.get("completion_tokens_details")
        if isinstance(details, dict) and isinstance(details.get("reasoning_tokens"), int):
            self._last_usage["completion_tokens_details"] = {"reasoning_tokens": details["reasoning_tokens"]}

        first_choice = choices[0]
        if not isinstance(first_choice, dict) or not isinstance(first_choice.get("message"), dict):
            raise OpenRouterEmptyContentError("OpenRouter returned a choice without an assistant message.")
        finish_reason = first_choice.get("finish_reason") or first_choice.get("native_finish_reason")
        self._last_finish_reason = str(finish_reason) if finish_reason is not None else None

        if self._last_routed_model != self._model:
            logger.info(
                "OpenRouter routed request from '%s' to upstream model '%s' (finish_reason=%s, usage=%s).",
                self._model,
                self._last_routed_model,
                self._last_finish_reason,
                self._last_usage or "n/a",
            )
        if finish_reason == "length":
            logger.warning(
                "OpenRouter response was truncated by max_tokens limit (model: %s, routed: %s, usage: %s).",
                self._model,
                self._last_routed_model,
                self._last_usage or "n/a",
            )

        message = first_choice.get("message") or {}
        content = message.get("content")
        reasoning = message.get("reasoning") or ""
        if not reasoning and isinstance(message.get("reasoning_details"), list):
            reasoning = " ".join(
                str(d.get("text") or d.get("summary") or "")
                for d in message["reasoning_details"]
                if isinstance(d, dict)
            )
        reasoning = str(reasoning)
        self._last_reasoning_chars = len(reasoning.strip())
        details = usage.get("completion_tokens_details") if isinstance(usage, dict) else None
        reasoning_tokens = details.get("reasoning_tokens") if isinstance(details, dict) else None
        completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None

        if isinstance(content, list):
            content = "".join(part["text"] for part in content if isinstance(part, dict)
                              and part.get("type") == "text" and isinstance(part.get("text"), str))
        if not isinstance(content, str):
            content = ""
        if structured:
            content = content.strip()
            thought = re.match(r"^[^{}`\[\]]*?<think>", content, re.IGNORECASE)
            if thought:
                # Only the suffix after the last tagged thought can be a final response.
                start = thought.end() - len("<think>")
                end = content.lower().find("</think>", start)
                self._last_reasoning_chars += len(content[start:end if end >= 0 else None])
                content = content[end + len("</think>"):].strip() if end >= 0 else ""
        has_content = bool(content.strip())
        if has_content:
            # Final answer is ONLY ever taken from message.content; reasoning is never merged in.
            self._last_response_classification = "truncated_content" if finish_reason == "length" else "content"
            candidate = extract_json_payload(content) if structured else ""
            if structured and (not candidate.startswith("{") or (
                not content.startswith("{") and not re.match(r'\{\s*["}]', candidate)
            )):
                self._last_response_classification = "non_json_final_content"
                raise OpenRouterNoJsonError(
                    f"OpenRouter returned final text without a JSON object "
                    f"(routed='{self._last_routed_model}', finish_reason={finish_reason})."
                )
            return content

        diag = (
            f"model='{self._model}', routed='{self._last_routed_model}', finish_reason={finish_reason}, "
            f"completion_tokens={completion_tokens}, reasoning_tokens={reasoning_tokens}, "
            f"reasoning_chars={self._last_reasoning_chars}"
        )

        if finish_reason == "length":
            self._last_response_classification = "reasoning_budget_exhausted"
            logger.warning("OpenRouter output budget exhausted before final content was produced (%s).", diag)
            if structured:
                raise OpenRouterTokenBudgetExhaustedError(
                    "OpenRouter model reached its output token limit before producing any final "
                    f"content ({diag}). Reasoning text is not accepted as structured output and JSON repair was skipped."
                )
        elif self._last_reasoning_chars or reasoning_tokens or message.get("reasoning_details"):
            self._last_response_classification = "reasoning_only"
            logger.warning("OpenRouter returned reasoning only with empty message.content (%s).", diag)
            if structured:
                raise OpenRouterReasoningOnlyError(
                    "OpenRouter model returned reasoning text but empty final message.content "
                    f"({diag}). Reasoning text is never accepted as structured output."
                )
        else:
            self._last_response_classification = "empty_content"
            if structured:
                raise OpenRouterEmptyContentError(
                    f"OpenRouter model returned neither final content nor reasoning ({diag})."
                )

        # Unstructured text mode: empty final content is a transient upstream failure (bounded retry).
        raise OpenRouterServerError(
            f"OpenRouter returned empty message content ({diag}).",
            status_code=502,
            body=data,
        )

    def _execute_with_retry(
        self,
        payload_builder: Callable[[bool], Dict[str, Any]],
        structured: bool = False,
    ) -> str:
        """
        Execute an OpenRouter request with bounded retries for transient errors (429, 5xx, timeout).

        CRITICAL:
        - HTTP 401 (Authentication) and HTTP 402 (Insufficient Credits) NEVER retry.
        - HTTP 413 (Oversized Request) NEVER retries unchanged; performs at most 1 compacted retry
          (`compacted=True`) and raises immediately if still oversized.
        """
        last_exception: Optional[Exception] = None
        compacted_mode = False
        decoding_failures = 0

        for attempt in range(1, self.max_retries + 1):
            try:
                payload = payload_builder(compacted_mode)
                return self._post_chat_completion(payload, structured=structured)
            except OpenRouterPaidModelBlockedError as e:
                logger.error("OpenRouter PaidModelBlockedError. Non-retryable: %s", e)
                raise
            except OpenRouterModelCompatibilityError as e:
                logger.error("OpenRouter structured-output incompatibility (%s). Non-retryable: %s", e.classification, e)
                raise
            except OpenRouterAuthenticationError as e:
                logger.error("OpenRouter AuthenticationError (HTTP 401). Non-retryable: %s", e)
                raise
            except OpenRouterInsufficientCreditsError as e:
                logger.error("OpenRouter InsufficientCreditsError (HTTP 402). Non-retryable: %s", e)
                raise
            except OpenRouterPayloadTooLargeError as e:
                if not compacted_mode:
                    compacted_mode = True
                    logger.warning(
                        "OpenRouter HTTP 413 oversized request on attempt %d (model: %s). "
                        "Executing single bounded retry with compacted prompt and reduced max_tokens.",
                        attempt,
                        self._model,
                    )
                    try:
                        compacted_payload = payload_builder(True)
                        if compacted_payload == payload:
                            raise e
                        return self._post_chat_completion(compacted_payload, structured=structured)
                    except OpenRouterError as compact_err:
                        logger.error(
                            "OpenRouter compacted retry also failed for model '%s': %s",
                            self._model,
                            compact_err,
                        )
                        raise
                logger.error("OpenRouter HTTP 413 oversized request cannot be retried unchanged: %s", e)
                raise
            except OpenRouterRateLimitError as e:
                last_exception = e
                delay = max(3.0, (self.retry_backoff_factor ** attempt) * 2.0)
                retry_after = e.headers.get("retry-after")
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after) + 0.5)
                    except (ValueError, TypeError):
                        try:
                            delay = max(delay, parsedate_to_datetime(retry_after).timestamp() - time.time())
                        except (TypeError, ValueError, OverflowError):
                            pass
                logger.warning(
                    "OpenRouter RateLimitError (HTTP 429) on attempt %d/%d (model: %s). Backing off for %.2fs: %s",
                    attempt,
                    self.max_retries,
                    self._model,
                    delay,
                    e,
                )
                if attempt < self.max_retries:
                    if delay > min(30.0, self._remaining_seconds()):
                        raise OpenRouterRateLimitError(
                            "OpenRouter rate limit exceeds the retry window. Retry the script stage later.",
                            status_code=429,
                        ) from e
                    self._sleep_before_retry(delay)
            except OpenRouterDecodingError as e:
                last_exception = e
                decoding_failures += 1
                # Bounded retry for transient upstream compressed-stream corruption: at most 1 retry (2 total attempts)
                if decoding_failures >= 2 or attempt >= self.max_retries:
                    logger.error(
                        "OpenRouter DecodingError on attempt %d/%d (model: %s). Aborting retries: %s",
                        attempt,
                        self.max_retries,
                        self._model,
                        e,
                    )
                    raise
                delay = max(1.0, self.retry_backoff_factor)
                logger.warning(
                    "OpenRouter DecodingError on attempt %d/%d (model: %s). Executing single bounded retry after %.2fs: %s",
                    attempt,
                    self.max_retries,
                    self._model,
                    delay,
                    e,
                )
                self._sleep_before_retry(delay)
            except OpenRouterConnectionError as e:
                last_exception = e
                delay = max(2.0, (self.retry_backoff_factor ** attempt))
                logger.warning(
                    "OpenRouter connection/timeout error on attempt %d/%d (model: %s). Backing off for %.2fs: %s",
                    attempt,
                    self.max_retries,
                    self._model,
                    delay,
                    e,
                )
                if attempt < self.max_retries:
                    self._sleep_before_retry(delay)
            except OpenRouterServerError as e:
                last_exception = e
                delay = max(3.0, (self.retry_backoff_factor ** attempt) * 1.5)
                logger.warning(
                    "OpenRouter transient 5xx error (%s) on attempt %d/%d. Backing off for %.2fs: %s",
                    e.status_code,
                    attempt,
                    self.max_retries,
                    delay,
                    e,
                )
                if attempt < self.max_retries:
                    self._sleep_before_retry(delay)
            except OpenRouterError as e:
                logger.error("OpenRouter non-retryable API error (HTTP %s): %s", e.status_code, e)
                raise
            except Exception as e:
                logger.error("Unexpected error during OpenRouter API execution: %s", e)
                raise

        raise RuntimeError(
            f"OpenRouter API call failed after {self.max_retries} attempts with model '{self._model}': {last_exception}"
        ) from last_exception

    def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate unstructured text using the configured OpenRouter model."""
        base_messages: List[Dict[str, str]] = []
        if system_prompt:
            base_messages.append({"role": "system", "content": system_prompt})
        base_messages.append({"role": "user", "content": prompt})

        def _build_payload(compacted: bool) -> Dict[str, Any]:
            msgs = compact_messages_for_token_limit(base_messages) if compacted else base_messages
            params: Dict[str, Any] = {
                "model": self._model,
                "messages": msgs,
                "temperature": temperature,
            }
            if max_tokens:
                params["max_tokens"] = min(max_tokens, 2048) if compacted else max_tokens
            elif compacted:
                params["max_tokens"] = 2048
            return params

        return self._execute_with_retry(_build_payload)

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
        Generate a validated Pydantic model using a deterministic model-candidate strategy:
        the configured OPENROUTER_MODEL first, then OPENROUTER_FALLBACK_MODELS in order.

        Each candidate is tried at most once per call. A candidate that fails with a structured-output
        incompatibility (reasoning-only, reasoning budget exhausted, empty content, or invalid JSON after
        one bounded repair) is never retried for the same request, and explicit (non-router) models are
        cached as incompatible for this provider's lifetime so later scenes skip them immediately.
        """
        candidates = self._structured_model_candidates()
        failures: List[str] = []
        last_error: Optional[OpenRouterModelCompatibilityError] = None

        for candidate in candidates:
            if candidate in self._incompatible_models:
                failures.append(f"{candidate}: skipped (previously rejected: {self._incompatible_models[candidate]})")
                continue
            self._model = candidate
            self._last_routed_model = None
            try:
                return self._generate_structured_for_active_model(
                    prompt=prompt,
                    schema=schema,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except OpenRouterModelCompatibilityError as compat_err:
                last_error = compat_err
                routed = self._last_routed_model
                routed_note = f" (routed to '{routed}')" if routed and routed != candidate else ""
                failures.append(f"{candidate}{routed_note}: [{compat_err.classification}] {compat_err}")
                if candidate.strip().lower() != "openrouter/free":
                    self._incompatible_models[candidate] = compat_err.classification
                logger.warning(
                    "OpenRouter candidate '%s'%s rejected for %s (%s).",
                    candidate,
                    routed_note,
                    schema.__name__,
                    compat_err.classification,
                )
            finally:
                self._model = self._primary_model

        summary = "; ".join(failures) or "no candidate models available"
        final_err = (type(last_error) if last_error is not None else OpenRouterModelCompatibilityError)(
            f"OpenRouter could not produce a valid {schema.__name__} with any configured candidate model "
            f"({len(candidates)} candidate(s); no paid fallback is used). Details: {summary}",
            status_code=last_error.status_code if last_error else None,
            error_code="model_compatibility_error",
        )
        raise final_err from last_error

    def _generate_structured_for_active_model(
        self,
        prompt: str,
        schema: Type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = 4096,
    ) -> T:
        """
        Generate a validated Pydantic model response with the currently active model (`self._model`):
        - Stage 1: Strict `json_schema` mode if supported by the active OpenRouter model.
        - Stage 2: `json_object` / prompt-enforced JSON mode with concrete instance template.
        - Stage 3: Single bounded JSON repair pass, only when real (non-reasoning) content failed validation.
        """
        if supports_strict_json_schema(self._model):
            strict_schema = to_strict_json_schema(schema)
            base_messages = [
                {"role": "system", "content": system_prompt or "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ]

            def _build_strict_payload(compacted: bool) -> Dict[str, Any]:
                msgs = compact_messages_for_token_limit(base_messages) if compacted else base_messages
                eff_tokens = self._effective_structured_max_tokens(max_tokens, compacted)
                params: Dict[str, Any] = {
                    "model": self._model,
                    "messages": msgs,
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
                if eff_tokens:
                    params["max_tokens"] = eff_tokens
                return self._apply_structured_reasoning_controls(params)

            try:
                raw_str = self._execute_with_retry(_build_strict_payload, structured=True)
                return validate_structured_instance(raw_str, schema)  # type: ignore[return-value]
            except OpenRouterError as api_err:
                if _is_unsupported_response_format_error(api_err):
                    logger.warning(
                        "OpenRouter model '%s' rejected strict json_schema (%s). Falling back to json_object/prompt mode.",
                        self._model,
                        api_err,
                    )
                else:
                    raise
            except (json.JSONDecodeError, ValidationError, ValueError) as parse_err:
                logger.warning(
                    "Local validation failed on strict output for '%s' (model: %s): %s. Falling back to json_object mode.",
                    schema.__name__,
                    self._model,
                    _validation_summary(parse_err),
                )

        return self._generate_with_schema_prompt(
            prompt=prompt,
            schema=schema,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _generate_with_schema_prompt(
        self,
        prompt: str,
        schema: Type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = 4096,
    ) -> T:
        """
        Stage 2: Generate structured JSON using a concrete JSON instance example template
        (avoiding raw `$defs` / `properties` JSON Schema definitions that cause smaller/free models to echo the schema).
        """
        instance_template_str = build_json_instance_template(schema)
        augmented_system_prompt = (
            f"{system_prompt or 'You are a helpful assistant.'}\n\n"
            "CRITICAL JSON OUTPUT RULES:\n"
            f"1. You MUST output ONLY a single valid JSON object instance for `{schema.__name__}` following this example structure:\n"
            f"{instance_template_str}\n\n"
            "2. Populate every field with real, complete content generated from the user request.\n"
            "3. Do NOT output a JSON Schema definition (NEVER include keys such as '$defs', 'properties', 'additionalProperties', or '$schema').\n"
            "4. NEVER use placeholder ellipses such as '{...}', '[...]', or '...' anywhere in the JSON.\n"
            "5. Output raw JSON only with no markdown fences or conversational text."
        )

        base_messages = [
            {"role": "system", "content": augmented_system_prompt},
            {"role": "user", "content": prompt},
        ]
        use_json_object = supports_json_object_mode(self._model)

        def _build_json_obj_payload(compacted: bool) -> Dict[str, Any]:
            msgs = compact_messages_for_token_limit(base_messages, max_chars_per_message=3600) if compacted else base_messages
            eff_tokens = self._effective_structured_max_tokens(max_tokens, compacted)
            params: Dict[str, Any] = {
                "model": self._model,
                "messages": msgs,
                "temperature": temperature,
            }
            if use_json_object:
                params["response_format"] = {"type": "json_object"}
                if self._model == "openrouter/free" or self._model.endswith(":free"):
                    params["provider"] = {"require_parameters": True}
            if eff_tokens:
                params["max_tokens"] = eff_tokens
            return self._apply_structured_reasoning_controls(params)

        try:
            raw_json_str = self._execute_with_retry(_build_json_obj_payload, structured=True)
        except OpenRouterModelCompatibilityError:
            # Reasoning-only / budget-exhausted / empty content: there is no JSON to repair.
            raise
        except OpenRouterError as err:
            if use_json_object and _is_unsupported_response_format_error(err):
                if self._model == "openrouter/free" or self._model.endswith(":free"):
                    raise OpenRouterUnavailableError(
                        f"Free model '{self._model}' cannot serve the requested JSON format."
                    ) from err
                logger.warning(
                    "OpenRouter model '%s' does not support response_format=json_object. Retrying with prompt-only JSON mode.",
                    self._model,
                )
                use_json_object = False
                raw_json_str = self._execute_with_retry(_build_json_obj_payload, structured=True)
            else:
                raise

        try:
            return validate_structured_instance(raw_json_str, schema)  # type: ignore[return-value]
        except (json.JSONDecodeError, ValidationError, ValueError) as val_err:
            logger.warning(
                "Local validation failed on structured output for '%s' (model: %s, routed: %s): %s. "
                "Executing single bounded repair attempt.",
                schema.__name__,
                self._model,
                self._last_routed_model or self._model,
                _validation_summary(val_err),
            )
            return self._repair_json_output(
                prompt=prompt,
                schema=schema,
                validation_error=_validation_summary(val_err),
                system_prompt=augmented_system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                use_json_object=use_json_object,
            )

    def _repair_json_output(
        self,
        prompt: str,
        schema: Type[T],
        validation_error: str,
        system_prompt: str,
        temperature: float = 0.2,
        max_tokens: Optional[int] = 4096,
        use_json_object: bool = True,
    ) -> T:
        """
        Regenerate once from the task and validation summary without replaying upstream text.
        """
        is_length_truncated = self._last_finish_reason == "length"

        instance_template_str = build_json_instance_template(schema)
        truncation_hint = (
            "5. Your previous response was cut off by the token limit (finish_reason=length). "
            "Keep your reasoning brief and output the complete, valid JSON object directly without verbose preamble.\n"
            if is_length_truncated
            else ""
        )
        repair_user_prompt = (
            f"The previous JSON output for `{schema.__name__}` failed validation with the following error:\n"
            f"{validation_error}\n\n"
            "CORRECTION INSTRUCTIONS:\n"
            f"1. Output ONLY a single corrected JSON object instance for `{schema.__name__}` containing real content.\n"
            "2. Do NOT output a JSON Schema definition (NEVER include '$defs', 'properties', or 'additionalProperties').\n"
            "3. NEVER use placeholder ellipses such as '{...}', '[...]', or '...'.\n"
            "4. Ensure all required fields are present and all JSON braces and quotes are balanced.\n"
            f"{truncation_hint}\n"
            f"EXPECTED JSON INSTANCE STRUCTURE:\n{instance_template_str}"
        )

        repair_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
            {"role": "user", "content": repair_user_prompt},
        ]

        def _build_repair_payload(compacted: bool) -> Dict[str, Any]:
            msgs = compact_messages_for_token_limit(repair_messages, max_chars_per_message=2400) if compacted else repair_messages
            eff_tokens = self._effective_structured_max_tokens(max_tokens, compacted)
            params: Dict[str, Any] = {
                "model": self._model,
                "messages": msgs,
                "temperature": temperature,
            }
            if use_json_object:
                params["response_format"] = {"type": "json_object"}
                if self._model == "openrouter/free" or self._model.endswith(":free"):
                    params["provider"] = {"require_parameters": True}
            if eff_tokens:
                params["max_tokens"] = eff_tokens
            return self._apply_structured_reasoning_controls(params)

        if self._checkpoint:
            active = self._checkpoint.data.get("active", {})
            self._checkpoint.event(active.get("key", schema.__name__), "json_repair", "running")
        repaired_raw = self._execute_with_retry(_build_repair_payload, structured=True)
        try:
            return validate_structured_instance(repaired_raw, schema)  # type: ignore[return-value]
        except (json.JSONDecodeError, ValidationError, ValueError) as final_err:
            routed_info = (
                f" (routed to '{self._last_routed_model}')"
                if self._last_routed_model and self._last_routed_model != self._model
                else ""
            )
            logger.error(
                "Repaired JSON output from OpenRouter model '%s'%s still failed validation for '%s': %s",
                self._model,
                routed_info,
                schema.__name__,
                _validation_summary(final_err),
            )
            raise OpenRouterModelCompatibilityError(
                f"OpenRouter output validation failed for {schema.__name__} after repair attempt "
                f"(model='{self._model}'{routed_info}): {_validation_summary(final_err)}. "
                "Check the configured model's structured-output support.",
                status_code=422,
                error_code="model_compatibility_error",
            ) from final_err
