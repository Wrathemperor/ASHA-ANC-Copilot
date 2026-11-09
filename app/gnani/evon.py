"""OpenAI-compatible Evon v3.3 client."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from .client_base import UsageCounter, api_key, bounded_call
from .demo import DemoEvonClient, demo_offline_enabled

DEFAULT_BASE_URL = "https://api.vachana.ai"
DEFAULT_MODEL = "gnani/gnani-evon-v3.3-30B-A3B"


class EvonClient:
    def __init__(self, http_client: Any | None = None, usage: UsageCounter | None = None) -> None:
        self.base_url = os.getenv("EVON_BASE_URL", "").strip().rstrip("/") or DEFAULT_BASE_URL
        self.model = os.getenv("EVON_MODEL", "").strip() or DEFAULT_MODEL
        self.usage = usage or UsageCounter()
        self.demo_mode = http_client is None and demo_offline_enabled()
        if self.demo_mode:
            self.api_key = ""
            self.client = DemoEvonClient()
        else:
            self.api_key = os.getenv("EVON_API_KEY", "").strip() or api_key()
            self.client = http_client or httpx.Client(timeout=30.0)

    @staticmethod
    def _strip_think(text: str) -> str:
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        if self.demo_mode:
            return self.client.complete_json(system, user)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "chat_template_kwargs": {"enable_thinking": False},
        }

        def request() -> str:
            auth_value = "{} {}".format("Bearer", self.api_key)
            response = self.client.post(
                f"{self.base_url}/v1/chat/completions",
                headers={
                    "Authorization": auth_value,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
            return body["choices"][0]["message"]["content"]

        content = bounded_call(request, "evon", self.usage)
        return json.loads(self._strip_think(content))
