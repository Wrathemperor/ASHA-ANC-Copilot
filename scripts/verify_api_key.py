"""[LIVE] User-run, credit-guarded checks for hosted Gnani services.

This script makes billable requests only after interactive confirmation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import wave

import httpx
from dotenv import load_dotenv

# Support both `python -m scripts.verify_api_key` and direct script execution.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.gnani.client_base import GnaniConfigurationError, UsageCounter, api_key
from app.gnani.evon import DEFAULT_BASE_URL, DEFAULT_MODEL
from app.gnani.prisma import ANC_KEYWORDS, ANC_TOPIC, PRISMA_URL
from app.gnani.timbre import TIMBRE_URL

TTS_TEXT = "नमस्ते"
TTS_LANGUAGE = "hi-IN"
TTS_VOICE = "Nalini"
TTS_MODEL = "timbre-v2.5"


def tts_cache_path(
    cache_dir: Path,
    text: str = TTS_TEXT,
    language: str = TTS_LANGUAGE,
    voice: str = TTS_VOICE,
    model: str = TTS_MODEL,
) -> Path:
    identity = json.dumps(
        [language, voice, model, text],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.wav"


def is_wav(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def validate_stt_audio(path: Path) -> bytes:
    audio = path.read_bytes()
    try:
        with path.open("rb") as audio_file:
            with wave.open(audio_file, "rb") as wav_file:
                duration_seconds = wav_file.getnframes() / wav_file.getframerate()
    except (wave.Error, EOFError, ZeroDivisionError) as error:
        raise ValueError("Prisma verification requires a valid WAV file.") from error
    if not audio:
        raise ValueError("Prisma verification WAV is empty.")
    if duration_seconds > 30:
        raise ValueError("Prisma verification WAV must be 30 seconds or shorter.")
    return audio


def check_evon(
    client: httpx.Client,
    key: str,
    base_url: str,
    model: str,
    usage: UsageCounter,
) -> tuple[bool, str, float]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": 'Reply with exactly {"pong":true}.'},
            {"role": "user", "content": "ping"},
        ],
        "temperature": 0.1,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    started = time.perf_counter()
    usage.record("evon")
    try:
        response = client.post(
            f"{base_url.rstrip('/')}/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            return False, "HTTP response contained no completion text.", time.perf_counter() - started
        return True, "HTTP response contained completion text.", time.perf_counter() - started
    except httpx.HTTPStatusError as error:
        return False, f"HTTP {error.response.status_code}; response body withheld.", time.perf_counter() - started
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        return False, "Request or response validation failed; response details withheld.", time.perf_counter() - started


def check_timbre(
    client: httpx.Client,
    key: str,
    cache_dir: Path,
    usage: UsageCounter,
) -> tuple[bool, str, float]:
    cache_path = tts_cache_path(cache_dir)
    if cache_path.is_file():
        cached_audio = cache_path.read_bytes()
        if is_wav(cached_audio):
            return True, "Valid WAV already cached; no API request made.", 0.0

    payload = {
        "text": TTS_TEXT,
        "voice": TTS_VOICE,
        "model": TTS_MODEL,
        "language": TTS_LANGUAGE,
        "speed": 1.0,
        "audio_config": {
            "sample_rate": 16000,
            "num_channels": 1,
            "sample_width": 2,
            "encoding": "linear_pcm",
            "container": "wav",
        },
    }
    started = time.perf_counter()
    usage.record("timbre")
    try:
        response = client.post(
            TIMBRE_URL,
            headers={"X-API-Key-ID": key, "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        audio = response.content
        if not is_wav(audio):
            return False, "Response was not a WAV file.", time.perf_counter() - started
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(audio)
        return True, "Valid WAV received and cached.", time.perf_counter() - started
    except httpx.HTTPStatusError as error:
        return False, f"HTTP {error.response.status_code}; response body withheld.", time.perf_counter() - started
    except httpx.HTTPError:
        return False, "Request failed; response details withheld.", time.perf_counter() - started


def check_prisma(
    client: httpx.Client,
    key: str,
    audio_path: Path,
    usage: UsageCounter,
) -> tuple[bool, str, float]:
    try:
        audio = validate_stt_audio(audio_path)
    except (OSError, ValueError) as error:
        return False, str(error), 0.0

    started = time.perf_counter()
    usage.record("prisma")
    try:
        response = client.post(
            PRISMA_URL,
            headers={"X-API-Key-ID": key},
            files={"audio_file": (audio_path.name, audio, "audio/wav")},
            data={
                "language_code": "hi-IN",
                "model": "prisma-v3.0",
                "format": "transcribe",
                "keyterms": ",".join(ANC_KEYWORDS),
                "topic": ANC_TOPIC,
            },
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("success") is not True:
            return False, "Response did not report successful transcription.", time.perf_counter() - started
        transcript = body.get("transcript")
        if not isinstance(transcript, str):
            return False, "Response contained no transcript field.", time.perf_counter() - started
        message = "Transcription succeeded." if transcript.strip() else "Request succeeded; transcript was empty."
        return True, message, time.perf_counter() - started
    except httpx.HTTPStatusError as error:
        return False, f"HTTP {error.response.status_code}; response body withheld.", time.perf_counter() - started
    except (httpx.HTTPError, ValueError):
        return False, "Request or response validation failed; response details withheld.", time.perf_counter() - started


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--test-stt",
        type=Path,
        metavar="WAV",
        help="also send this local WAV clip to Prisma (may incur API credits)",
    )
    args = parser.parse_args(argv)
    load_dotenv()

    try:
        key = api_key()
    except GnaniConfigurationError as error:
        print(f"Configuration error: {error}")
        return 2

    try:
        if args.test_stt:
            validate_stt_audio(args.test_stt)
    except (OSError, ValueError) as error:
        print(f"Prisma sample error: {error}")
        return 2

    base_url = os.getenv("EVON_BASE_URL", "").strip().rstrip("/") or DEFAULT_BASE_URL
    model = os.getenv("EVON_MODEL", "").strip() or DEFAULT_MODEL
    cache_path = tts_cache_path(Path(".cache/tts"))
    cached_timbre = cache_path.is_file() and is_wav(cache_path.read_bytes())
    request_count = 1 + (0 if cached_timbre else 1) + (1 if args.test_stt else 0)
    print("GNANI_API_KEY is configured (value masked).")
    print(f"This diagnostic will make up to {request_count} request(s); requests may consume API credits.")
    print("Each service check is attempted once. Prisma is included only with --test-stt.")
    try:
        confirmation = input("Continue? Type 'yes' to proceed: ").strip().lower()
    except EOFError:
        confirmation = ""
    if confirmation != "yes":
        print("Cancelled; no API requests were made.")
        return 1

    usage = UsageCounter()
    all_passed = True
    with httpx.Client(timeout=30.0) as client:
        checks = [
            ("Evon", check_evon(client, key, base_url, model, usage)),
            ("Timbre", check_timbre(client, key, Path(".cache/tts"), usage)),
        ]
        if args.test_stt:
            checks.append(("Prisma", check_prisma(client, key, args.test_stt, usage)))
    for service, (passed, message, elapsed) in checks:
        print(f'{"OK" if passed else "FAILED"} {service}: {message} ({elapsed:.2f}s)')
        all_passed = all_passed and passed
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
