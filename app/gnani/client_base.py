"""Shared configuration, bounded retries, and API usage accounting."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, TypeVar

from dotenv import load_dotenv

load_dotenv()

T = TypeVar("T")


class GnaniError(Exception):
    """Base error for local Gnani wrappers."""


class GnaniConfigurationError(GnaniError):
    """Required configuration is missing or invalid."""


class GnaniRequestError(GnaniError):
    """A bounded request failed."""


class GnaniDependencyError(GnaniError):
    """Optional SDK dependency is unavailable."""


class UsageCounter:
    """Track calls in memory and in the project cache."""

    def __init__(self, path: Path | str = ".cache/api_usage.json") -> None:
        self.path = Path(path)
        self.calls: dict[str, int] = {}

    def record(self, service: str) -> None:
        self.calls[service] = self.calls.get(service, 0) + 1
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            existing: dict[str, object] = {}
            if self.path.exists():
                try:
                    existing = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    existing = {}
            file_calls = existing.get("calls", {})
            if not isinstance(file_calls, dict):
                file_calls = {}
            file_calls[service] = int(file_calls.get(service, 0)) + 1
            existing["calls"] = file_calls
            existing["total"] = sum(int(value) for value in file_calls.values())
            self.path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass


def api_key() -> str:
    key = os.getenv("GNANI_API_KEY", "").strip()
    if not key:
        raise GnaniConfigurationError("GNANI_API_KEY is required.")
    return key


def bounded_call(call: Callable[[], T], service: str, usage: UsageCounter, retries: int = 1) -> T:
    """Call once, then retry at most once. Never loop indefinitely."""
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        usage.record(service)
        try:
            return call()
        except Exception as error:  # SDK and transport errors have varied types.
            last_error = error
            if attempt >= retries:
                break
    raise GnaniRequestError(f"{service} request failed after {retries + 1} attempt(s).") from last_error
