"""Prisma STT v3 wrapper."""

from __future__ import annotations

from typing import Any

import httpx

from .client_base import UsageCounter, api_key, bounded_call
from .demo import DemoPrismaClient, demo_offline_enabled

ANC_KEYWORDS = ["ANC", "BP", "systolic", "diastolic", "IFA", "calcium", "hemoglobin", "Hb", "sujan", "swelling", "bleeding", "fits", "convulsions", "dhundhla", "headache", "fetal movement", "halchal"]
ANC_TOPIC = "ASHA worker recording an Antenatal Care (ANC) pregnancy home visit with gestational weeks, blood pressure (BP), and maternal danger signs."
PRISMA_URL = "https://api.vachana.ai/stt/v3"


class PrismaClient:
    def __init__(
        self,
        sdk_client: Any | None = None,
        usage: UsageCounter | None = None,
        http_client: Any | None = None,
    ) -> None:
        self.usage = usage or UsageCounter()
        if sdk_client is not None:
            self.client = sdk_client
            self.http_client = None
            self._api_key = None
            self.demo_mode = False
            return
        self.demo_mode = demo_offline_enabled()
        if self.demo_mode:
            self.client = DemoPrismaClient()
            self.http_client = None
            self._api_key = None
            return
        if http_client is not None:
            self.client = None
            self.http_client = http_client
            self._api_key = api_key()
            return
        try:
            from gnani.stt import GnaniSTTClient
            self.client = GnaniSTTClient(api_key=api_key())
        except ImportError:
            self.client = None
        if self.client is None:
            self.http_client = httpx.Client(timeout=30.0)
            self._api_key = api_key()
        else:
            self.http_client = None
            self._api_key = None

    def transcribe(self, audio_bytes: bytes, language_code: str, previous_text: str | None = None) -> dict[str, Any]:
        if self.demo_mode:
            return self.client.transcribe_bytes(
                audio_bytes,
                filename="audio.wav",
                language_code=language_code,
                model="prisma-v3.0",
                format="transcribe",
                keywords=ANC_KEYWORDS,
                topic=ANC_TOPIC,
                previous_text=previous_text,
            )
        if self.client is None:
            data = {
                "language_code": language_code,
                "model": "prisma-v3.0",
                "format": "transcribe",
                "keyterms": ",".join(ANC_KEYWORDS),
                "topic": ANC_TOPIC,
            }
            if previous_text:
                data["previous_text"] = previous_text

            def request() -> dict[str, Any]:
                response = self.http_client.post(
                    PRISMA_URL,
                    headers={"X-API-Key-ID": self._api_key},
                    files={"audio_file": ("audio.wav", audio_bytes, "audio/wav")},
                    data=data,
                )
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    raise TypeError("Prisma REST response must be a JSON object.")
                return body

            return bounded_call(request, "prisma", self.usage)
        return bounded_call(
            lambda: self.client.transcribe_bytes(audio_bytes, filename="audio.wav", language_code=language_code, model="prisma-v3.0", format="transcribe", keywords=ANC_KEYWORDS, topic=ANC_TOPIC, previous_text=previous_text),
            "prisma",
            self.usage,
        )