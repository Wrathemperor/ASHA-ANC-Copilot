"""Google Gemini Flash client — drop-in replacement for EvonClient.

Uses the Gemini REST API with JSON mode. Requires GEMINI_API_KEY in the environment.
Falls back to demo mode when DEMO_OFFLINE_MODE=1.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from .client_base import (
    GnaniConfigurationError,
    GnaniRequestError,
    UsageCounter,
    bounded_call,
)
from .demo import DemoEvonClient, demo_offline_enabled

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
_GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _gemini_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise GnaniConfigurationError(
            "GEMINI_API_KEY is required when using Gemini as the LLM backend."
        )
    return key


class GeminiClient:
    """OpenAI-role-style wrapper around the Gemini REST generateContent endpoint."""

    def __init__(
        self,
        http_client: Any | None = None,
        usage: UsageCounter | None = None,
    ) -> None:
        self.model = os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL
        self.usage = usage or UsageCounter()
        self.demo_mode = http_client is None and demo_offline_enabled()
        if self.demo_mode:
            self._demo = DemoEvonClient()
            self._client: httpx.Client | None = None
            self._api_key = ""
        else:
            self._demo = None  # type: ignore[assignment]
            self._api_key = _gemini_api_key()
            self._client = http_client or httpx.Client(timeout=30.0)

    @staticmethod
    def _strip_fences(text: str) -> str:
        """Remove ```json … ``` wrappers and <think> tags."""
        text = re.sub(
            r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE
        ).strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        return text.strip()

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        """Send a system+user prompt pair and return parsed JSON."""
        if self.demo_mode:
            return self._demo.complete_json(system, user)

        url = f"{_GEMINI_API_BASE}/{self.model}:generateContent?key={self._api_key}"
        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": f"{system}\n\n{user}"}]},
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.1,
            },
        }

        def request() -> str:
            assert self._client is not None
            response = self._client.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
            # Gemini returns candidates[0].content.parts[0].text
            return body["candidates"][0]["content"]["parts"][0]["text"]

        content = bounded_call(request, "gemini", self.usage)
        return json.loads(self._strip_fences(content))
