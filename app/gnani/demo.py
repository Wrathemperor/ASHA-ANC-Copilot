"""Deterministic, explicitly enabled demo providers backed by synthetic fixtures."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import struct
import wave
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.schema import ANCVisitRecord

_SCENARIOS_PATH = Path(__file__).resolve().parents[2] / "eval" / "ground_truth" / "scenarios.json"
_FOLLOWUP_DEMO_TRANSCRIPT = "No additional details are included in this offline demo response."
_READBACK_ENDINGS = (
    "Is that correct?",
    "क्या यह सही है?",
    "हे बरोबर आहे का?",
    "இது சரியா?",
    "ఇది సరైనదేనా?",
    "അത് ശരിയാണോ?",
)


@lru_cache(maxsize=1)
def _load_scenarios() -> tuple[dict[str, Any], ...]:
    return tuple(json.loads(_SCENARIOS_PATH.read_text(encoding="utf-8")))


def demo_offline_enabled() -> bool:
    """Only enable synthetic fixtures when explicitly requested."""
    return os.getenv("DEMO_OFFLINE_MODE", "").strip() == "1"


def select_demo_scenario(audio_bytes: bytes, language: str) -> dict[str, Any]:
    """Select a reproducible synthetic transcript for the selected language."""
    candidates = [
        scenario for scenario in _load_scenarios()
        if scenario["language"] == language
    ]
    if not candidates:
        raise ValueError(f"No offline demo scenarios are available for {language}.")
    digest = hashlib.sha256(audio_bytes).digest()
    index = int.from_bytes(digest[:8], "big") % len(candidates)
    return candidates[index]


def _is_readback_prompt(text: str) -> bool:
    return any(text.rstrip().endswith(ending) for ending in _READBACK_ENDINGS)


class DemoPrismaClient:
    """Fixture-backed transcript provider; it does not perform speech recognition."""

    def transcribe_bytes(
        self,
        audio_bytes: bytes,
        *,
        language_code: str,
        previous_text: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        if previous_text and _is_readback_prompt(previous_text):
            candidates = [
                scenario for scenario in _load_scenarios()
                if scenario["language"] == language_code and scenario.get("readback")
            ]
            if candidates:
                digest = hashlib.sha256(audio_bytes).digest()
                selected = candidates[int.from_bytes(digest[:8], "big") % len(candidates)]
                transcript = selected["readback"]["transcript"]
            else:
                transcript = "yes, that is correct"
        elif previous_text:
            transcript = _FOLLOWUP_DEMO_TRANSCRIPT
        else:
            transcript = select_demo_scenario(audio_bytes, language_code)["transcript"]

        return {
            "success": True,
            "transcript": transcript,
            "model": "offline-synthetic-fixture",
            "detected_language_code": language_code,
            "truncated": False,
            "processing_time": 0.0,
            "end_to_end_latency": 0.0,
        }


class DemoEvonClient:
    """Return only exact synthetic fixture records or read-back labels."""

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        if "numeric-only read-back" in system:
            folded_user = user.casefold()
            for scenario in _load_scenarios():
                readback = scenario.get("readback")
                if readback and readback["transcript"].casefold() in folded_user:
                    updates = readback["expected_updates"]
                    return {
                        "confirmed": readback["expected_confirmed"],
                        "bp_systolic": updates.get("bp_systolic"),
                        "bp_diastolic": updates.get("bp_diastolic"),
                        "gestational_weeks": updates.get("gestational_weeks"),
                        "evidence": readback["transcript"],
                    }
            return {
                "confirmed": False,
                "bp_systolic": None,
                "bp_diastolic": None,
                "gestational_weeks": None,
                "evidence": "",
            }

        for scenario in _load_scenarios():
            if scenario["transcript"] in user:
                return asdict(ANCVisitRecord(**scenario["expected_record"]))
        return asdict(ANCVisitRecord())


class DemoTimbreClient:
    """Create a short, deterministic WAV tone; prompt text remains visible in the UI."""

    def synthesize(
        self,
        text: str,
        voice: str = "Nalini",
        model: str = "timbre-v2.5",
        language: str = "en-IN",
        speed: float = 1.0,
    ) -> bytes:
        del voice, model, speed
        sample_rate = 16_000
        sample_count = sample_rate // 3
        digest = hashlib.sha256(f"{language}\0{text}".encode("utf-8")).digest()
        frequency = 440 + int.from_bytes(digest[:2], "big") % 440
        frames = bytearray()
        fade_samples = sample_rate // 100
        for index in range(sample_count):
            envelope = min(1.0, index / fade_samples, (sample_count - index) / fade_samples)
            sample = int(0.18 * envelope * 32767 * math.sin(2 * math.pi * frequency * index / sample_rate))
            frames.extend(struct.pack("<h", sample))

        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(frames)
        return output.getvalue()
