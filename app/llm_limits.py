"""Model-aware Ollama context and answer-output token limits."""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx


@dataclass(frozen=True)
class ModelTokenLimits:
    model: str
    context_tokens: int
    configured_output_tokens: int
    effective_output_tokens: int
    estimated_prompt_tokens: int
    context_source: str


_PROFILE_FIELDS = {
    "gemma4:e2b": ("llm_e2b_context_tokens", "llm_e2b_max_output_tokens"),
    "gemma4:e4b": ("llm_e4b_context_tokens", "llm_e4b_max_output_tokens"),
    "gemma4:31b-cloud": (
        "llm_31b_cloud_context_tokens",
        "llm_31b_cloud_max_output_tokens",
    ),
}


def estimate_prompt_tokens(text: str) -> int:
    """Conservatively estimate mixed CJK/Latin prompt tokens without a tokenizer."""
    return max(1, len(text), math.ceil(len(text.encode("utf-8")) / 3))


def _context_from_show_payload(payload: dict[str, Any]) -> int | None:
    values = [
        int(value)
        for key, value in payload.get("model_info", {}).items()
        if key.endswith("context_length") and isinstance(value, (int, float))
    ]
    return max(values) if values else None


@lru_cache(maxsize=16)
def discover_local_model_context(
    base_url: str, model: str, timeout_seconds: float
) -> int | None:
    """Read a local model's architecture context limit; failure is non-fatal."""
    try:
        response = httpx.post(
            f"{base_url.rstrip('/')}/api/show",
            json={"model": model, "verbose": False},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        return _context_from_show_payload(response.json())
    except (httpx.HTTPError, TypeError, ValueError):
        return None


def resolve_model_token_limits(
    settings: Any,
    model: str,
    prompt: str,
    base_url: str,
    api_key: str = "",
) -> ModelTokenLimits:
    """Resolve the selected model's configured cap within its usable context."""
    context_field, output_field = _PROFILE_FIELDS.get(
        model,
        ("llm_unknown_context_tokens", "llm_max_output_tokens"),
    )
    configured_context = int(getattr(settings, context_field, 4096))
    configured_output = int(getattr(settings, output_field, settings.llm_max_output_tokens))
    context_tokens = configured_context
    context_source = "configured"

    # Local /api/show needs no secret and exposes the architecture context limit.
    # Cloud deployments keep an explicit versioned configuration fallback.
    if not api_key and bool(
        getattr(settings, "llm_capability_discovery_enabled", False)
    ):
        discovered = discover_local_model_context(
            base_url,
            model,
            float(getattr(settings, "llm_capability_timeout_seconds", 5.0)),
        )
        if discovered:
            context_tokens = min(configured_context, discovered)
            context_source = "api_show+configured"

    prompt_tokens = estimate_prompt_tokens(prompt)
    safety_tokens = int(getattr(settings, "llm_context_safety_tokens", 512))
    remaining = max(64, context_tokens - prompt_tokens - safety_tokens)
    effective_output = max(64, min(configured_output, remaining))
    return ModelTokenLimits(
        model=model,
        context_tokens=context_tokens,
        configured_output_tokens=configured_output,
        effective_output_tokens=effective_output,
        estimated_prompt_tokens=prompt_tokens,
        context_source=context_source,
    )
