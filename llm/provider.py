"""Unified LLM provider — routes requests to NVIDIA NIM or Gemini based on availability."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from llm.nvidia_nim import nvidia_client
from llm.gemini import gemini_client

logger = logging.getLogger(__name__)


class ModelTier(str, Enum):
    """Model selection tiers based on task complexity."""

    FAST = "fast"          # Quick tasks: routing, classification, simple edits
    STANDARD = "standard"  # Most tasks: code generation, planning
    HEAVY = "heavy"        # Complex tasks: multi-file reasoning, architecture


class LLMProvider:
    """Unified LLM provider that transparently routes to available backends.

    Priority order:
    1. NVIDIA NIM (primary — free credits on signup)
    2. Google Gemini (fallback — free tier)

    The provider automatically falls back if the primary is unavailable.
    """

    def __init__(self) -> None:
        self._check_availability()

    def _check_availability(self) -> None:
        providers = []
        if nvidia_client.available:
            providers.append("NVIDIA NIM")
        if gemini_client.available:
            providers.append("Google Gemini")

        if not providers:
            logger.error(
                "No LLM providers configured! Set NVIDIA_API_KEY or GEMINI_API_KEY in .env"
            )
        else:
            logger.info(f"LLM providers available: {', '.join(providers)}")

    def _get_nvidia_model(self, tier: ModelTier) -> str:
        """Get NVIDIA NIM model ID for a given tier."""
        from app.config import settings

        tier_map = {
            ModelTier.FAST: settings.nvidia_fast_model,
            ModelTier.STANDARD: settings.nvidia_default_model,
            ModelTier.HEAVY: settings.nvidia_default_model,  # 122B — 397B times out on free tier
        }
        return tier_map[tier]

    def _get_gemini_model(self, tier: ModelTier) -> str:
        """Get Gemini model ID for a given tier."""
        from app.config import settings

        tier_map = {
            ModelTier.FAST: settings.gemini_default_model,
            ModelTier.STANDARD: settings.gemini_default_model,
            ModelTier.HEAVY: settings.gemini_pro_model,
        }
        return tier_map[tier]

    async def chat(
        self,
        messages: list[dict[str, str]],
        tier: ModelTier = ModelTier.STANDARD,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> str:
        """Send a chat completion, routing to the best available provider.

        Args:
            messages: Chat messages in OpenAI format.
            tier: Complexity tier for model selection.
            temperature: Sampling temperature.
            max_tokens: Max output tokens.
            tools: Optional tool definitions for function calling.

        Returns:
            The text content of the LLM response.
        """
        # Try NVIDIA NIM first
        if nvidia_client.available:
            try:
                model = self._get_nvidia_model(tier)
                response = await nvidia_client.chat(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=tools,
                    **kwargs,
                )
                # Extract text from OpenAI response object
                return response.choices[0].message.content or ""
            except Exception as e:
                logger.warning(f"NVIDIA NIM failed, falling back to Gemini: {e}")

        # Fallback to Gemini
        if gemini_client.available:
            try:
                model = self._get_gemini_model(tier)
                return await gemini_client.chat(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
            except Exception as e:
                logger.error(f"Gemini also failed: {e}")
                raise

        raise RuntimeError(
            "No LLM provider available. Set NVIDIA_API_KEY or GEMINI_API_KEY in your .env file."
        )

    async def chat_with_tools(
        self,
        messages: list[dict[str, str]],
        tools: list[dict],
        tier: ModelTier = ModelTier.STANDARD,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> Any:
        """Chat with tool/function calling support.

        Returns the full response object so callers can inspect tool_calls.
        Only available with NVIDIA NIM (OpenAI-compatible API).
        """
        if nvidia_client.available:
            model = self._get_nvidia_model(tier)
            return await nvidia_client.chat(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
                **kwargs,
            )

        # Gemini tool calling requires different format — degrade gracefully
        logger.warning("Tool calling requested but only Gemini available — using plain chat.")
        text = await self.chat(
            messages=messages, tier=tier, temperature=temperature, max_tokens=max_tokens
        )
        return text

    async def stream(
        self,
        messages: list[dict[str, str]],
        tier: ModelTier = ModelTier.STANDARD,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        **kwargs: Any,
    ):
        """Stream a chat response, yielding text chunks.

        Routes to the best available provider.
        """
        if nvidia_client.available:
            try:
                model = self._get_nvidia_model(tier)
                async for chunk in nvidia_client.chat_stream(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                ):
                    yield chunk
                return
            except Exception as e:
                logger.warning(f"NIM stream failed, falling back to Gemini: {e}")

        if gemini_client.available:
            model = self._get_gemini_model(tier)
            async for chunk in gemini_client.chat_stream(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            ):
                yield chunk
            return

        raise RuntimeError("No LLM provider available for streaming.")


# Module-level singleton
llm = LLMProvider()
