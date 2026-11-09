"""Timbre TTS v2.5 wrapper with deterministic disk caching."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx

from .client_base import UsageCounter, api_key, bounded_call
from .demo import DemoTimbreClient, demo_offline_enabled

TIMBRE_V25_VOICES = ("Nalini", "Kaveri", "Suhana", "Devika", "Lavanya")
TIMBRE_URL = "https://api.vachana.ai/api/v1/tts/inference"


class TimbreClient:
    def __init__(
        self,
        sdk_client: Any | None = None,
        cache_dir: Path | str = ".cache/tts",
        usage: UsageCounter | None = None,
        http_client: Any | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.usage = usage or UsageCounter()
        if sdk_client is not None:
            self.client = sdk_client
            self.http_client = None
            self._api_key = None
            self.demo_mode = False
            return
        self.demo_mode = demo_offline_enabled()
        if self.demo_mode:
            self.client = DemoTimbreClient()
            self.http_client = None
            self._api_key = None
            return
        if http_client is not None:
            self.client = None
            self.http_client = http_client
            self._api_key = api_key()
            return
        try:
            from gnani.tts import GnaniTTSClient
            self.client = GnaniTTSClient(api_key=api_key())
        except ImportError:
            self.client = None
        if self.client is None:
            self.http_client = httpx.Client(timeout=30.0)
            self._api_key = api_key()
        else:
            self.http_client = None
            self._api_key = None

    def synthesize(self, text: str, language: str, voice: str = "Nalini", model: str = "timbre-v2.5") -> bytes:
        if voice not in TIMBRE_V25_VOICES:
            raise ValueError(f"Unsupported Timbre v2.5 voice: {voice}")
        if self.demo_mode:
            return self.client.synthesize(
                text=text,
                voice=voice,
                model=model,
                language=language,
                speed=1.0,
            )
        identity = json.dumps([language, voice, model, text], ensure_ascii=False, separators=(",", ":"))
        cache_path = self.cache_dir / f"{hashlib.sha256(identity.encode('utf-8')).hexdigest()}.wav"
        if cache_path.exists():
            return cache_path.read_bytes()
        if self.client is None:
            payload = {
                "text": text,
                "voice": voice,
                "model": model,
                "language": language,
                "speed": 1.0,
                "audio_config": {
                    "sample_rate": 16000,
                    "num_channels": 1,
                    "sample_width": 2,
                    "encoding": "linear_pcm",
                    "container": "wav",
                },
            }

            def request() -> bytes:
                response = self.http_client.post(
                    TIMBRE_URL,
                    headers={
                        "X-API-Key-ID": self._api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                return response.content

            audio = bounded_call(request, "timbre", self.usage)
        else:
            audio = bounded_call(lambda: self.client.synthesize(text=text, voice=voice, model=model, language=language, speed=1.0), "timbre", self.usage)
        if not isinstance(audio, bytes):
            raise TypeError("Timbre synthesize must return bytes.")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(audio)
        return audio
