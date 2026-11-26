
"""Amazon Bedrock Converse wrapper with jittered retries and exact USD cost.

Only the standard library and the ``boto3`` that ships with the Lambda
``python3.13`` runtime are used, which is what allows the v2 stack to build for
``arm64`` without Docker or native wheels.
"""

from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

LOGGER = logging.getLogger(__name__)

NOVA_PRO = "apac.amazon.nova-pro-v1:0"
NOVA_LITE = "apac.amazon.nova-lite-v1:0"

# ap-southeast-2 on-demand token pricing, USD per single token.
PRICING: Dict[str, Dict[str, float]] = {
    NOVA_PRO: {"input": 0.80 / 1_000_000, "output": 3.20 / 1_000_000},
    NOVA_LITE: {"input": 0.06 / 1_000_000, "output": 0.24 / 1_000_000},
}

RETRYABLE_ERROR_CODES = frozenset(
    {
        "ThrottlingException",
        "TooManyRequestsException",
        "ServiceUnavailableException",
        "InternalServerException",
        "ModelNotReadyException",
        "ModelTimeoutException",
        "RequestTimeout",
        "RequestTimeoutException",
    }
)

# SDK-level retries are disabled so the bounded jittered retry policy here is the
# single source of truth for both timing and telemetry.
_BOTO_CONFIG = Config(
    connect_timeout=1,
    read_timeout=8,
    retries={"max_attempts": 0, "mode": "standard"},
)


class BedrockInvocationError(RuntimeError):
    """Raised when Bedrock cannot produce a response after all retries."""


@dataclass(frozen=True)
class Invocation:
    """One successful Converse call and its measured economics."""

    text: str
    model_id: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    estimated_cost_usd: float
    stop_reason: str

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def calculate_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """Exact USD cost from measured token counts (no rounding at this layer)."""

    try:
        rates = PRICING[model_id]
    except KeyError as exc:
        raise ValueError(f"no pricing configured for model '{model_id}'") from exc
    return (input_tokens * rates["input"]) + (output_tokens * rates["output"])


def _content_text(response: Dict[str, Any]) -> str:
    message = response.get("output", {}).get("message", {})
    parts = message.get("content", []) or []
    return "".join(part.get("text", "") for part in parts if isinstance(part, dict))


class BedrockClient:
    """Thin, testable wrapper around ``bedrock-runtime`` Converse."""

    def __init__(
        self,
        model_id: str = NOVA_PRO,
        runtime_client: Optional[Any] = None,
        max_attempts: int = 2,
        base_backoff_seconds: float = 0.25,
        sleep: Any = time.sleep,
        client_config: Optional[Config] = None,
    ) -> None:
        self.model_id = model_id
        self.max_attempts = max(1, max_attempts)
        self.base_backoff_seconds = base_backoff_seconds
        self._sleep = sleep
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        client_kwargs: Dict[str, Any] = {"config": client_config or _BOTO_CONFIG}
        if region:
            client_kwargs["region_name"] = region
        self._client = runtime_client or boto3.client("bedrock-runtime", **client_kwargs)

    def _invoke(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return self._client.converse(**request)

    def converse(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 400,
        temperature: float = 0.0,
        top_p: float = 0.9,
    ) -> Invocation:
        """Call Converse with bounded exponential backoff and full jitter."""

        request: Dict[str, Any] = {
            "modelId": self.model_id,
            "messages": [{"role": "user", "content": [{"text": user_prompt}]}],
            "system": [{"text": system_prompt}],
            "inferenceConfig": {
                "maxTokens": max_tokens,
                "temperature": temperature,
                "topP": top_p,
            },
        }

        last_error: Optional[BaseException] = None
        for attempt in range(1, self.max_attempts + 1):
            started = time.perf_counter()
            try:
                response = self._invoke(request)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                last_error = exc
                if code not in RETRYABLE_ERROR_CODES or attempt == self.max_attempts:
                    raise BedrockInvocationError(
                        f"Bedrock rejected the request ({code or 'unknown error'})"
                    ) from exc
            except (BotoCoreError, OSError) as exc:
                last_error = exc
                if attempt == self.max_attempts:
                    raise BedrockInvocationError(
                        f"Bedrock connection failed after {attempt} attempts"
                    ) from exc
            else:
                latency_ms = max(1, int(round((time.perf_counter() - started) * 1000)))
                usage = response.get("usage", {}) or {}
                input_tokens = int(usage.get("inputTokens", 0) or 0)
                output_tokens = int(usage.get("outputTokens", 0) or 0)
                return Invocation(
                    text=_content_text(response),
                    model_id=self.model_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    estimated_cost_usd=calculate_cost(
                        self.model_id, input_tokens, output_tokens
                    ),
                    stop_reason=str(response.get("stopReason", "")),
                )

            delay = min(
                0.5,
                (self.base_backoff_seconds * (2 ** (attempt - 1)))
                # Non-cryptographic retry backoff jitter only.
                + random.uniform(0, self.base_backoff_seconds),  # nosec B311
            )
            LOGGER.warning(
                "bedrock_retry model=%s attempt=%s delay_ms=%s error=%s",
                self.model_id,
                attempt,
                int(delay * 1000),
                type(last_error).__name__,
            )
            self._sleep(delay)

        raise BedrockInvocationError("Bedrock invocation exhausted all retries")
