import json
import os
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

from app.gnani.client_base import GnaniRequestError, UsageCounter
from app.gnani.evon import EvonClient
from app.gnani.prisma import PrismaClient
from app.gnani.timbre import TimbreClient


@pytest.fixture
def usage(tmp_path: Path) -> UsageCounter:
    return UsageCounter(tmp_path / "test_api_usage.json")


def test_prisma_passes_fixed_options(usage: UsageCounter) -> None:
    class SDK:
        def transcribe_bytes(self, *args, **kwargs):
            assert kwargs["model"] == "prisma-v3.0"
            assert kwargs["format"] == "transcribe"
            assert kwargs["filename"] == "audio.wav"
            return {"success": True, "transcript": "ok"}
    assert PrismaClient(SDK(), usage).transcribe(b"wav", "hi-IN")["success"]
    assert usage.calls == {"prisma": 1}


def test_prisma_direct_rest_uses_keyterms_and_previous_text(
    usage: UsageCounter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GNANI_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8")
        assert request.url == "https://api.vachana.ai/stt/v3"
        assert request.headers["X-API-Key-ID"] == "test-key"
        assert "name=\"language_code\"" in body and "hi-IN" in body
        assert "name=\"model\"" in body and "prisma-v3.0" in body
        assert "name=\"format\"" in body and "transcribe" in body
        assert "name=\"keyterms\"" in body and "ANC,BP" in body
        assert "name=\"keywords\"" not in body
        assert "name=\"previous_text\"" in body and "What is your BP?" in body
        assert "name=\"audio_file\"" in body and "audio.wav" in body
        return httpx.Response(
            200,
            json={"success": True, "transcript": "BP is normal."},
        )

    client = PrismaClient(
        usage=usage,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = client.transcribe(b"wave-bytes", "hi-IN", "What is your BP?")

    assert result["transcript"] == "BP is normal."
    assert usage.calls == {"prisma": 1}


def test_timbre_cache_calls_sdk_once(usage: UsageCounter, tmp_path: Path) -> None:
    class SDK:
        calls = 0
        def synthesize(self, **kwargs):
            self.calls += 1
            return b"RIFF-audio"
    sdk = SDK()
    cache_dir = tmp_path / "test_tts"
    cache_dir.mkdir(parents=True, exist_ok=True)
    for cached in cache_dir.glob("*.wav"):
        cached.unlink()
    client = TimbreClient(sdk, cache_dir, usage)
    assert client.synthesize("Question", "hi-IN") == b"RIFF-audio"
    assert client.synthesize("Question", "hi-IN") == b"RIFF-audio"
    assert sdk.calls == 1
    assert usage.calls == {"timbre": 1}


def test_timbre_direct_rest_sends_key_and_caches_wav(
    usage: UsageCounter,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GNANI_API_KEY", "test-key")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = json.loads(request.content)
        assert request.url == "https://api.vachana.ai/api/v1/tts/inference"
        assert request.headers["X-API-Key-ID"] == "test-key"
        assert body["text"] == "नमस्ते"
        assert body["voice"] == "Nalini"
        assert body["model"] == "timbre-v2.5"
        assert body["language"] == "hi-IN"
        assert body["audio_config"]["container"] == "wav"
        assert body["audio_config"]["sample_rate"] == 16000
        return httpx.Response(200, content=b"RIFF" + b"\0" * 40 + b"WAVE")

    client = TimbreClient(
        cache_dir=tmp_path / "tts-cache",
        usage=usage,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    first = client.synthesize("नमस्ते", "hi-IN")
    second = client.synthesize("नमस्ते", "hi-IN")

    assert first.startswith(b"RIFF") and first == second
    assert calls == 1
    assert usage.calls == {"timbre": 1}


def test_evon_strips_think_and_sends_payload(usage: UsageCounter, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GNANI_API_KEY", "test-key")
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.headers["Authorization"] == "Bearer test-key"
        assert body["temperature"] == 0.1
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        return httpx.Response(200, json={"choices": [{"message": {"content": "<think>hidden</think>{\"ok\": true}"}}]})
    client = EvonClient(httpx.Client(transport=httpx.MockTransport(handler)), usage)
    assert client.complete_json("system", "user") == {"ok": True}
    assert usage.calls == {"evon": 1}


def test_evon_invalid_json_is_left_for_extraction_repair(
    usage: UsageCounter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GNANI_API_KEY", "test-key")
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not valid json"}}]},
        )

    client = EvonClient(httpx.Client(transport=httpx.MockTransport(handler)), usage)
    with pytest.raises(json.JSONDecodeError):
        client.complete_json("system", "user")

    assert requests == 1
    assert usage.calls == {"evon": 1}


def test_retry_is_bounded(usage: UsageCounter) -> None:
    class SDK:
        calls = 0
        def transcribe_bytes(self, *args, **kwargs):
            self.calls += 1
            raise RuntimeError("down")
    sdk = SDK()
    with pytest.raises(GnaniRequestError):
        PrismaClient(sdk, usage).transcribe(b"wav", "en-IN")
    assert sdk.calls == 2
    assert usage.calls == {"prisma": 2}


def test_offline_demo_providers_use_fixtures_without_api_usage(
    usage: UsageCounter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.gnani.demo import select_demo_scenario
    import wave
    import io

    monkeypatch.setenv("DEMO_OFFLINE_MODE", "1")
    monkeypatch.delenv("GNANI_API_KEY", raising=False)
    sample_audio = b"offline-demo-clip"
    expected = select_demo_scenario(sample_audio, "hi-IN")

    transcription = PrismaClient(usage=usage).transcribe(sample_audio, "hi-IN")
    extracted = EvonClient(usage=usage).complete_json("extract", transcription["transcript"])
    tone = TimbreClient(usage=usage).synthesize("Question", "hi-IN")

    assert transcription["transcript"] == expected["transcript"]
    assert extracted["gestational_weeks"] == expected["expected_record"].get("gestational_weeks")
    with wave.open(io.BytesIO(tone), "rb") as wav:
        assert wav.getframerate() == 16_000
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getnframes() > 0
    assert usage.calls == {}


def test_live_spike_runs_offline_with_fixture_and_local_tone(
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "synthetic-clip.wav"
    audio_path.write_bytes(b"synthetic demo bytes")
    environment = os.environ.copy()
    environment["DEMO_OFFLINE_MODE"] = "1"
    environment.pop("GNANI_API_KEY", None)
    environment.pop("EVON_API_KEY", None)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.live_spike",
            str(audio_path),
            "--language",
            "hi-IN",
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout.splitlines()[-1])
    assert result["transcript"]
    assert result["record"]
    assert "evaluation" in result
    assert result["timbre_audio_bytes"] > 44


def test_offline_mode_can_be_enabled_from_dotenv_file(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    (tmp_path / ".env").write_text("DEMO_OFFLINE_MODE=1\n", encoding="utf-8")
    environment = os.environ.copy()
    environment.pop("DEMO_OFFLINE_MODE", None)
    environment.pop("GNANI_API_KEY", None)
    environment.pop("EVON_API_KEY", None)
    environment["PYTHONPATH"] = str(project_root)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.gnani.prisma import PrismaClient; "
            "print(PrismaClient().demo_mode)",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=environment,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip() == "True"
