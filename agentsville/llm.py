# Phase 0 – Step 5: the only module that talks to the OpenAI SDK; measures latency, tokens, cost.
"""Thin LLM client wrapper.

All app code calls `LLMClient.chat()` instead of the SDK directly, so retries, timeouts,
error handling and cost tracking live in one place and tests can inject a fake client.
"""

from __future__ import annotations

import time
from typing import Any

import openai
from pydantic import BaseModel

from agentsville.config import Settings

DEFAULT_TIMEOUT_S = 60.0
DEFAULT_MAX_RETRIES = 2

# Phase 0 – Step 5: OpenAI list prices, USD per 1M tokens (input, output).
# An estimate only: the OPENAI_BASE_URL proxy may bill differently.
PRICES_PER_1M_TOKENS: dict[str, tuple[float, float]] = {
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4o-mini": (0.15, 0.60),
}


# Phase 0 – Step 5: one error type for every LLM failure (auth, timeout, rate limit, network)
class LLMError(RuntimeError):
    """Raised when an LLM call fails."""


# Phase 0 – Step 5: reply text plus call metrics (copied into AgentStep by the agent)
class LLMResponse(BaseModel):
    text: str
    model: str
    latency_ms: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None


# Phase 0 – Step 5: estimated cost of one call; None for models without a known price
def estimate_cost(
    model: str, prompt_tokens: int | None, completion_tokens: int | None
) -> float | None:
    prices = PRICES_PER_1M_TOKENS.get(model)
    if prices is None or prompt_tokens is None or completion_tokens is None:
        return None
    input_price, output_price = prices
    return (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000


# Phase 0 – Step 5: wrapper around the OpenAI chat completions API
class LLMClient:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._default_model = settings.model
        # `client` lets tests inject a fake; otherwise build the real SDK client.
        self._client = client or openai.OpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            base_url=settings.openai_base_url,
            timeout=DEFAULT_TIMEOUT_S,
            max_retries=DEFAULT_MAX_RETRIES,
        )

    # Phase 6 – Step 2: the model used when chat() gets no explicit model (recorded in runs)
    @property
    def default_model(self) -> str:
        return self._default_model

    # Phase 0 – Step 5: send messages, time the call, return text + metrics
    # Phase 4 – Step 4: optional JSON mode – the reply is guaranteed to be a JSON object
    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.0,
        json_mode: bool = False,
    ) -> LLMResponse:
        model = model or self._default_model
        extra: dict[str, Any] = {}
        if json_mode:
            extra["response_format"] = {"type": "json_object"}
        start = time.perf_counter()
        try:
            response = self._client.chat.completions.create(
                model=model, messages=messages, temperature=temperature, **extra
            )
        except openai.OpenAIError as exc:
            raise LLMError(f"LLM call to '{model}' failed: {type(exc).__name__}: {exc}") from exc
        latency_ms = (time.perf_counter() - start) * 1000

        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)

        return LLMResponse(
            text=response.choices[0].message.content or "",
            model=model,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=estimate_cost(model, prompt_tokens, completion_tokens),
        )
