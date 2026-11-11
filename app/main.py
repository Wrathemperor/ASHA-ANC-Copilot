"""FastAPI scaffold for in-memory browser-audio validation."""

from __future__ import annotations

import io
import subprocess
import wave
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.db import Database, init_db
from app.gnani.demo import demo_offline_enabled
from app.session import SessionManager, SessionState

TARGET_RATE = 16_000
MAX_AUDIO_BYTES = 10 * 1024 * 1024
app = FastAPI(title="Voice ANC Home-Visit Copilot")
app.state.session_manager = SessionManager()
app.state.db = init_db(seed=True)


class SessionStartRequest(BaseModel):
    language: str = "hi-IN"


class PatientCreateRequest(BaseModel):
    rch_id: str
    name: str
    age: int | None = None
    village: str | None = None
    edd: str | None = None


class LinkPatientRequest(BaseModel):
    rch_id: str


def _session_manager() -> SessionManager:
    return app.state.session_manager


def _db() -> Database:
    if not hasattr(app.state, "db") or app.state.db is None:
        app.state.db = init_db(seed=True)
    return app.state.db


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


@app.post("/api/session/{session_id}/clarify")
def clarify_question(session_id: str) -> dict[str, object]:
    manager = _session_manager()
    _get_session_or_404(manager, session_id)
    try:
        return _session_response(manager.request_clarification(session_id))
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


@app.get("/api/patients")
def list_patients(query: str | None = None) -> list[dict[str, Any]]:
    return [asdict(p) for p in _db().list_patients(query)]


@app.post("/api/patients")
def create_patient(req: PatientCreateRequest) -> dict[str, Any]:
    patient = _db().create_patient(
        rch_id=req.rch_id,
        name=req.name,
        age=req.age,
        village=req.village,
        edd=req.edd,
    )
    return asdict(patient)


@app.get("/api/patients/{rch_id}/history")
def get_patient_history(rch_id: str) -> dict[str, Any]:
    patient = _db().get_patient_by_rch(rch_id)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {rch_id} not found.")
    visits = _db().get_patient_visits(patient.id)
    return {"patient": asdict(patient), "visits": [asdict(v) for v in visits]}


@app.post("/api/session/{session_id}/link-patient")
def link_patient(session_id: str, req: LinkPatientRequest) -> dict[str, Any]:
    manager = _session_manager()
    session = _get_session_or_404(manager, session_id)
    patient = _db().get_patient_by_rch(req.rch_id)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {req.rch_id} not found.")
    visits = _db().get_patient_visits(patient.id)
    updated = manager.link_patient(session_id, patient, visits)
    return _session_response(updated)


@app.post("/api/session/{session_id}/save-to-db")
def save_visit_to_db(session_id: str) -> dict[str, Any]:
    manager = _session_manager()
    session = _get_session_or_404(manager, session_id)
    if not session.patient_id:
        raise HTTPException(status_code=400, detail="Session has no linked patient.")

    past_visits = _db().get_patient_visits(session.patient_id)
    next_visit_number = len(past_visits) + 1

    tri_state_data = {
        field_name: getattr(session.record, field_name)
        for field_name in (
            "swelling",
            "severe_headache",
            "blurred_vision",
            "reduced_fetal_movement",
            "vaginal_bleeding",
            "convulsions",
            "severe_abdominal_pain",
            "fever",
            "leaking_fluid",
            "anemia_or_low_hb_mentioned",
            "ifa_tablets_taken",
            "calcium_tablets_taken",
        )
    }

    saved = _db().save_visit(
        patient_id=session.patient_id,
        session_id=session.session_id,
        visit_number=next_visit_number,
        gestational_weeks=int(session.record.gestational_weeks)
        if session.record.gestational_weeks is not None
        else None,
        bp_systolic=int(session.record.bp_systolic)
        if session.record.bp_systolic is not None
        else None,
        bp_diastolic=int(session.record.bp_diastolic)
        if session.record.bp_diastolic is not None
        else None,
        weight_kg=float(session.record.weight_kg)
        if session.record.weight_kg is not None
        else None,
        hemoglobin=float(session.record.hemoglobin)
        if session.record.hemoglobin is not None
        else None,
        tri_state_json=tri_state_data,
        referral_flag=session.evaluation.flag,
        rule_ids=session.evaluation.rule_ids,
        evidence_json=session.record.evidence_spans,
        status="LOCKED" if session.state == "FINAL_LOCKED" else "DRAFT",
    )
    return {"status": "ok", "saved_visit": asdict(saved)}


@app.get("/api/session/{session_id}/referral-slip")
def get_referral_slip(session_id: str) -> dict[str, Any]:
    manager = _session_manager()
    session = _get_session_or_404(manager, session_id)
    patient = None
    if session.patient_id:
        p_obj = _db().get_patient_by_id(session.patient_id)
        if p_obj:
            patient = asdict(p_obj)

    qr_payload = (
        f"RCH:{patient.get('rch_id') if patient else 'UNLINKED'}|"
        f"FLAG:{session.evaluation.flag}|"
        f"RULES:{','.join(session.evaluation.rule_ids)}|"
        f"BP:{session.record.bp_systolic}/{session.record.bp_diastolic}|"
        f"WEEKS:{session.record.gestational_weeks}"
    )

    return {
        "session_id": session.session_id,
        "patient": patient,
        "referral_flag": session.evaluation.flag,
        "emergency_bypass": session.evaluation.emergency_bypass,
        "rule_ids": session.evaluation.rule_ids,
        "citations": session.evaluation.citations,
        "vitals": {
            "gestational_weeks": session.record.gestational_weeks,
            "bp_systolic": session.record.bp_systolic,
            "bp_diastolic": session.record.bp_diastolic,
            "weight_kg": session.record.weight_kg,
            "hemoglobin": session.record.hemoglobin,
        },
        "evidence_spans": session.record.evidence_spans,
        "qr_code_data": qr_payload,
    }


app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
