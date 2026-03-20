"""NVIDIA NIM LLM integration via OpenAI-compatible API."""

from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class NvidiaNIMClient:
    """Client for NVIDIA NIM inference API.

    Uses the OpenAI SDK since NIM exposes an OpenAI-compatible API.
    Requires an API key from https://build.nvidia.com.
    """

    def __init__(self) -> None:
        if not settings.has_nvidia:
            logger.warning("NVIDIA_API_KEY not set — NIM client will not be available.")
            self._client = None
            return

        self._client = AsyncOpenAI(
            base_url=settings.nvidia_base_url,
            api_key=settings.nvidia_api_key,
            timeout=60.0,  # 60s timeout — free tier can be slow
            max_retries=1,  # Fail fast, fall back to Gemini
        )

    @property
    def available(self) -> bool:
        return self._client is not None

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a chat completion request to NVIDIA NIM.

        Args:
            messages: List of chat messages [{"role": "...", "content": "..."}]
            model: NIM model ID. Defaults to settings.nvidia_default_model.
            temperature: Sampling temperature (0-1).
            max_tokens: Maximum output tokens.
            tools: Optional tool definitions for function calling.

        Returns:
            The full response dict from the API.
        """
        if not self._client:
            raise RuntimeError("NVIDIA NIM client is not configured. Set NVIDIA_API_KEY.")

        model = model or settings.nvidia_default_model

        request_kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs,
        }

        if tools:
            request_kwargs["tools"] = tools
            request_kwargs["tool_choice"] = "auto"

        logger.info(f"NIM request → model={model}, messages={len(messages)}")

        response = await self._client.chat.completions.create(**request_kwargs)
        return response

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        **kwargs: Any,
    ):
        """Stream a chat completion response from NVIDIA NIM.

        Yields delta content chunks as they arrive.
        """
        if not self._client:
            raise RuntimeError("NVIDIA NIM client is not configured. Set NVIDIA_API_KEY.")

        model = model or settings.nvidia_default_model

        stream = await self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        """Generate embeddings using NVIDIA NIM embedding model.

        Args:
            texts: List of text strings to embed.
            model: Embedding model ID. Defaults to settings.nvidia_embed_model.

        Returns:
            List of embedding vectors.
        """
        if not self._client:
            raise RuntimeError("NVIDIA NIM client is not configured. Set NVIDIA_API_KEY.")

        model = model or settings.nvidia_embed_model

        # NIM embedding API uses the same input format as OpenAI
        response = await self._client.embeddings.create(
            model=model,
            input=texts,
            encoding_format="float",
            extra_body={"input_type": "query", "truncate": "END"},
        )

        return [item.embedding for item in response.data]


# Module-level singleton
nvidia_client = NvidiaNIMClient()
