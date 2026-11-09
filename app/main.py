"""FastAPI scaffold for in-memory browser-audio validation."""

from __future__ import annotations

import io
import subprocess
import wave

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.gnani.demo import demo_offline_enabled
from app.session import SessionManager, SessionState

TARGET_RATE = 16_000
MAX_AUDIO_BYTES = 10 * 1024 * 1024
app = FastAPI(title="Voice ANC Home-Visit Copilot")
app.state.session_manager = SessionManager()


class SessionStartRequest(BaseModel):
    language: str = "hi-IN"


def _session_manager() -> SessionManager:
    return app.state.session_manager


def _session_response(session: SessionState) -> dict[str, object]:
    return jsonable_encoder(session)


async def _read_session_audio(audio: UploadFile) -> bytes:
    try:
        audio_bytes = await audio.read(MAX_AUDIO_BYTES + 1)
    finally:
        await audio.close()
    if not audio_bytes:
        raise HTTPException(status_code=422, detail="Audio upload is empty.")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio upload exceeds the 10 MiB limit.")
    return audio_bytes


def _get_session_or_404(session_manager: SessionManager, session_id: str) -> SessionState:
    try:
        return session_manager.get_session(session_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


def is_target_wav(audio_bytes: bytes) -> bool:
    """Check for 16 kHz mono 16-bit PCM WAV bytes."""
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
            return (
                wav_file.getframerate() == TARGET_RATE
                and wav_file.getnchannels() == 1
                and wav_file.getsampwidth() == 2
                and wav_file.getcomptype() == "NONE"
            )
    except (EOFError, wave.Error):
        return False


def normalize_audio(audio_bytes: bytes) -> bytes:
    """Return 16 kHz mono PCM WAV audio without temporary files."""
    if not audio_bytes:
        raise ValueError("Audio upload is empty.")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise ValueError("Audio upload exceeds the 10 MiB limit.")
    if is_target_wav(audio_bytes):
        return audio_bytes
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", "-f", "wav", "pipe:1"]
    try:
        result = subprocess.run(command, input=audio_bytes, capture_output=True, check=False, timeout=20)
    except FileNotFoundError as error:
        raise ValueError("ffmpeg is required to normalize non-WAV browser audio.") from error
    except subprocess.TimeoutExpired as error:
        raise ValueError("Audio normalization timed out.") from error
    if result.returncode or not is_target_wav(result.stdout):
        raise ValueError("Audio is unsupported or could not be normalized.")
    return result.stdout


@app.get("/health")
def health() -> dict[str, str | bool]:
    return {"status": "ok", "demo_offline": demo_offline_enabled()}


@app.post("/api/audio-check")
async def audio_check(audio: UploadFile = File(...)) -> Response:
    audio_bytes = await audio.read(MAX_AUDIO_BYTES + 1)
    try:
        normalized = normalize_audio(audio_bytes)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        await audio.close()
    return Response(normalized, media_type="audio/wav", headers={"X-Audio-Format": "pcm_s16le; rate=16000; channels=1"})


@app.post("/api/session/start")
def start_session(request: SessionStartRequest) -> dict[str, str]:
    try:
        session = _session_manager().create_session(request.language)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"session_id": session.session_id}


@app.post("/api/session/{session_id}/turn1")
async def process_turn1(session_id: str, audio: UploadFile = File(...)) -> dict[str, object]:
    manager = _session_manager()
    _get_session_or_404(manager, session_id)
    audio_bytes = await _read_session_audio(audio)
    try:
        return _session_response(manager.process_turn1(session_id, audio_bytes))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/session/{session_id}/followup")
async def process_followup(session_id: str, audio: UploadFile = File(...)) -> dict[str, object]:
    manager = _session_manager()
    _get_session_or_404(manager, session_id)
    audio_bytes = await _read_session_audio(audio)
    try:
        return _session_response(manager.process_followup(session_id, audio_bytes))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/session/{session_id}/readback")
async def process_readback(session_id: str, audio: UploadFile = File(...)) -> dict[str, object]:
    manager = _session_manager()
    _get_session_or_404(manager, session_id)
    audio_bytes = await _read_session_audio(audio)
    try:
        return _session_response(manager.process_readback(session_id, audio_bytes))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/session/{session_id}/manual-edit")
def manual_edit(session_id: str, updates: dict[str, object]) -> dict[str, object]:
    manager = _session_manager()
    _get_session_or_404(manager, session_id)
    try:
        return _session_response(manager.manual_confirm(session_id, updates))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/session/{session_id}")
def get_session(session_id: str) -> dict[str, object]:
    return _session_response(_get_session_or_404(_session_manager(), session_id))


app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
