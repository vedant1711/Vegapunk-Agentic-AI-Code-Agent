"""Google Gemini LLM integration — free tier fallback."""

from __future__ import annotations

import logging
from typing import Any

import google.generativeai as genai

from app.config import settings

logger = logging.getLogger(__name__)


class GeminiClient:
    """Client for Google Gemini API.

    Used as a free-tier fallback when NVIDIA NIM credits are exhausted.
    Requires an API key from https://aistudio.google.com/apikey.
    """

    def __init__(self) -> None:
        if not settings.has_gemini:
            logger.warning("GEMINI_API_KEY not set — Gemini client will not be available.")
            self._configured = False
            return

        genai.configure(api_key=settings.gemini_api_key)
        self._configured = True

    @property
    def available(self) -> bool:
        return self._configured

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> str:
        """Send a chat completion request to Gemini.

        Args:
            messages: List of chat messages [{"role": "...", "content": "..."}].
            model: Gemini model ID. Defaults to settings.gemini_default_model.
            temperature: Sampling temperature.
            max_tokens: Maximum output tokens.
            tools: Optional tool definitions (will be converted to Gemini format).

        Returns:
            The text content of the response.
        """
        if not self._configured:
            raise RuntimeError("Gemini client is not configured. Set GEMINI_API_KEY.")

        model_name = model or settings.gemini_default_model
        gemini_model = genai.GenerativeModel(model_name)

        # Convert OpenAI-style messages to Gemini format
        gemini_history = []
        system_instruction = None

        for msg in messages:
            role = msg["role"]
            content = msg["content"]

            if role == "system":
                system_instruction = content
            elif role == "user":
                gemini_history.append({"role": "user", "parts": [content]})
            elif role == "assistant":
                gemini_history.append({"role": "model", "parts": [content]})

        if system_instruction:
            gemini_model = genai.GenerativeModel(
                model_name, system_instruction=system_instruction
            )

        generation_config = genai.types.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        logger.info(f"Gemini request → model={model_name}, messages={len(messages)}")

        response = await gemini_model.generate_content_async(
            gemini_history,
            generation_config=generation_config,
        )

        return response.text

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        **kwargs: Any,
    ):
        """Stream a chat response from Gemini.

        Yields text chunks as they arrive.
        """
        if not self._configured:
            raise RuntimeError("Gemini client is not configured. Set GEMINI_API_KEY.")

        model_name = model or settings.gemini_default_model
        gemini_model = genai.GenerativeModel(model_name)

        gemini_history = []
        system_instruction = None

        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                system_instruction = content
            elif role == "user":
                gemini_history.append({"role": "user", "parts": [content]})
            elif role == "assistant":
                gemini_history.append({"role": "model", "parts": [content]})

        if system_instruction:
            gemini_model = genai.GenerativeModel(
                model_name, system_instruction=system_instruction
            )

        generation_config = genai.types.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        response = await gemini_model.generate_content_async(
            gemini_history,
            generation_config=generation_config,
            stream=True,
        )

        async for chunk in response:
            if chunk.text:
                yield chunk.text


# Module-level singleton
gemini_client = GeminiClient()
