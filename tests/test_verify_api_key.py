from __future__ import annotations

import io
from pathlib import Path
import wave

import httpx

from app.gnani.client_base import UsageCounter
from scripts.verify_api_key import (
    check_evon,
    check_prisma,
    check_timbre,
    is_wav,
    tts_cache_path,
    validate_stt_audio,
)


def make_wav(path: Path, duration_seconds: int = 1) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\0\0" * 16000 * duration_seconds)


def test_validate_stt_audio_rejects_over_30_seconds(tmp_path: Path) -> None:
    audio_path = tmp_path / "long.wav"
    make_wav(audio_path, duration_seconds=31)

    try:
        validate_stt_audio(audio_path)
    except ValueError as error:
        assert "30 seconds" in str(error)
    else:
        raise AssertionError("Long WAV should be rejected.")


def test_check_evon_makes_one_authenticated_request() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        assert request.headers["Authorization"] == "Bearer test-key"
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"pong":true}'}}]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = check_evon(
            client,
            "test-key",
            "https://api.vachana.ai",
            "test-model",
            UsageCounter(Path(".cache/test_verify_usage.json")),
        )

    assert result[0]
    assert requests == 1


def test_check_evon_does_not_retry_timeout() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        raise httpx.ReadTimeout("simulated timeout", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = check_evon(
            client,
            "test-key",
            "https://api.vachana.ai",
            "test-model",
            UsageCounter(Path(".cache/test_verify_timeout_usage.json")),
        )

    assert not result[0]
    assert requests == 1


def test_check_timbre_makes_one_request_and_caches_valid_wav(tmp_path: Path) -> None:
    requests = 0
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\0\0" * 160)
    wav_bytes = wav_buffer.getvalue()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        assert request.headers["X-API-Key-ID"] == "test-key"
        return httpx.Response(200, content=wav_bytes)

    cache_dir = tmp_path / "tts-cache"
    usage = UsageCounter(tmp_path / "usage.json")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = check_timbre(client, "test-key", cache_dir, usage)
        second = check_timbre(client, "test-key", cache_dir, usage)

    assert first[0] and second[0]
    assert "cached" in second[1]
    assert requests == 1
    assert is_wav(tts_cache_path(cache_dir).read_bytes())


def test_check_prisma_is_opt_in_helper_and_uses_keyterms(tmp_path: Path) -> None:
    audio_path = tmp_path / "sample.wav"
    make_wav(audio_path)
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        body = request.read().decode("latin-1")
        assert request.headers["X-API-Key-ID"] == "test-key"
        assert "name=\"keyterms\"" in body
        assert "name=\"keywords\"" not in body
        assert "prisma-v3.0" in body
        return httpx.Response(
            200,
            json={"success": True, "transcript": "sample transcript"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = check_prisma(
            client,
            "test-key",
            audio_path,
            UsageCounter(tmp_path / "usage.json"),
        )

    assert result[0]
    assert requests == 1
