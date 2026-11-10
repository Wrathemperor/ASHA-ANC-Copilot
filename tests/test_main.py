import io
import wave
from typing import Any
import base64

from fastapi.testclient import TestClient

from app.main import TARGET_RATE, app, normalize_audio
from app.gnani.demo import select_demo_scenario
from app.session import FINAL_LOCKED, SessionManager


def make_target_wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(TARGET_RATE)
        wav_file.writeframes(b"\x00\x00" * 160)
    return buffer.getvalue()


def test_health(monkeypatch: Any) -> None:
    monkeypatch.delenv("DEMO_OFFLINE_MODE", raising=False)
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "demo_offline": False}


def test_target_wav_is_validated_without_ffmpeg() -> None:
    audio = make_target_wav()
    assert normalize_audio(audio) == audio


def test_audio_check_returns_wav() -> None:
    response = TestClient(app).post("/api/audio-check", files={"audio": ("recording.wav", make_target_wav(), "audio/wav")})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["x-audio-format"] == "pcm_s16le; rate=16000; channels=1"


def test_static_root_serves_register_and_local_assets() -> None:
    client = TestClient(app)

    root = client.get("/")
    script = client.get("/app.js")
    styles = client.get("/styles.css")

    assert root.status_code == 200
    assert "ASHA ANC Home-Visit Copilot" in root.text
    assert script.status_code == 200
    assert "getUserMedia" in script.text
    assert "decodeAudioData" in script.text
    assert "routeRecording(wav)" in script.text
    assert styles.status_code == 200
    assert "48px" in styles.text
    assert "Upload Audio Clip (.mp3 / .wav)" in root.text


def test_pwa_assets_served() -> None:
    client = TestClient(app)
    manifest = client.get("/manifest.json")
    assert manifest.status_code == 200
    assert "ASHA ANC Home-Visit Copilot" in manifest.text

    sw = client.get("/service-worker.js")
    assert sw.status_code == 200
    assert "asha-anc-copilot" in sw.text

    icon192 = client.get("/icons/icon-192.svg")
    assert icon192.status_code == 200


class _RoutePrisma:
    def __init__(self) -> None:
        self.transcripts = [
            "Pregnant for fourteen weeks, blood pressure one twenty by eighty.",
            "No severe headache.",
            "yes correct",
        ]
        self.contexts: list[str | None] = []

    def transcribe(
        self,
        audio: bytes,
        language: str,
        previous_text: str | None = None,
    ) -> dict[str, Any]:
        self.contexts.append(previous_text)
        return {
            "success": True,
            "transcript": self.transcripts.pop(0),
            "truncated": False,
        }


class _RouteEvon:
    def __init__(self) -> None:
        self.responses = [
            self.record(severe_headache="not_mentioned"),
            self.record(severe_headache="denied"),
            {
                "confirmed": True,
                "bp_systolic": None,
                "bp_diastolic": None,
                "gestational_weeks": None,
                "evidence": "yes correct",
            },
        ]

    @staticmethod
    def record(**overrides: Any) -> dict[str, Any]:
        result: dict[str, Any] = {
            "gestational_weeks": 14,
            "bp_systolic": 120,
            "bp_diastolic": 80,
            "swelling": "denied",
            "severe_headache": "denied",
            "blurred_vision": "denied",
            "reduced_fetal_movement": "denied",
            "vaginal_bleeding": "denied",
            "convulsions": "denied",
            "severe_abdominal_pain": "denied",
            "fever": "denied",
            "leaking_fluid": "denied",
            "anemia_or_low_hb_mentioned": "denied",
            "ifa_tablets_taken": "not_mentioned",
            "calcium_tablets_taken": "not_mentioned",
            "last_anc_visit": None,
            "evidence_spans": {},
            "conflicts": [],
        }
        result.update(overrides)
        return result

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        return self.responses.pop(0)


class _RouteTimbre:
    def synthesize(self, text: str, language: str) -> bytes:
        return b"RIFF-mock"


def test_session_api_full_start_followup_readback_sequence() -> None:
    original_manager = app.state.session_manager
    app.state.session_manager = SessionManager(
        prisma_client=_RoutePrisma(),
        evon_client=_RouteEvon(),
        timbre_client=_RouteTimbre(),
    )
    client = TestClient(app)
    try:
        started = client.post("/api/session/start", json={"language": "en-IN"})
        assert started.status_code == 200
        session_id = started.json()["session_id"]

        turn1 = client.post(
            f"/api/session/{session_id}/turn1",
            files={"audio": ("visit.wav", b"wav-one", "audio/wav")},
        )
        assert turn1.status_code == 200
        assert turn1.json()["state"] == "FOLLOWUP_ACTIVE"

        followup = client.post(
            f"/api/session/{session_id}/followup",
            files={"audio": ("answer.wav", b"wav-two", "audio/wav")},
        )
        assert followup.status_code == 200
        assert followup.json()["state"] == "READBACK_ACTIVE"

        readback = client.post(
            f"/api/session/{session_id}/readback",
            files={"audio": ("confirm.wav", b"wav-three", "audio/wav")},
        )
        assert readback.status_code == 200
        assert readback.json()["state"] == FINAL_LOCKED
        assert readback.json()["record"]["severe_headache"] == "denied"
    finally:
        app.state.session_manager = original_manager


def test_offline_demo_api_runs_fixture_through_rules_and_readback(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("DEMO_OFFLINE_MODE", "1")
    original_manager = app.state.session_manager
    app.state.session_manager = SessionManager()
    client = TestClient(app)
    try:
        health = client.get("/health")
        assert health.json()["demo_offline"] is True
        started = client.post("/api/session/start", json={"language": "hi-IN"})
        session_id = started.json()["session_id"]

        first_audio = next(
            candidate
            for index in range(100)
            if (candidate := f"fixture-clip-{index}".encode())
            and select_demo_scenario(candidate, "hi-IN")["id"] == "normal-hi"
        )
        turn1 = client.post(
            f"/api/session/{session_id}/turn1",
            files={"audio": ("visit.wav", first_audio, "audio/wav")},
        )
        assert turn1.status_code == 200
        assert turn1.json()["state"] == "READBACK_ACTIVE"
        assert turn1.json()["evaluation"]["flag"] is None
        prompt_tone = base64.b64decode(turn1.json()["audio_playback_b64"])
        with wave.open(io.BytesIO(prompt_tone), "rb") as wav:
            assert wav.getframerate() == 16_000

        readback = client.post(
            f"/api/session/{session_id}/readback",
            files={"audio": ("response.wav", b"fixture-readback", "audio/wav")},
        )
        assert readback.status_code == 200
        assert readback.json()["state"] == "MANUAL_EDIT_REQUIRED"
        assert readback.json()["record"]["bp_systolic"] == 130
        assert readback.json()["record"]["bp_diastolic"] == 80

        final = client.post(f"/api/session/{session_id}/manual-edit", json={})
        assert final.status_code == 200
        assert final.json()["state"] == FINAL_LOCKED
    finally:
        app.state.session_manager = original_manager
