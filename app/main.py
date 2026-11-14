"""FastAPI scaffold for in-memory browser-audio validation."""

from __future__ import annotations

import io
import subprocess
import wave
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.audio_summary import generate_visit_audio_summary, build_spoken_summary_text
from app.db import Database, init_db
from app.gnani.demo import demo_offline_enabled
from app.risk import compute_risk_score
from app.schema import ANCVisitRecord
from app.session import SessionManager, SessionState
from app.whatsapp import handle_whatsapp_message, to_twiml_response, _WHATSAPP_AUDIT_LOG

TARGET_RATE = 16_000
MAX_AUDIO_BYTES = 10 * 1024 * 1024
app = FastAPI(title="Voice ANC Home-Visit Copilot")
app.state.session_manager = SessionManager()
try:
    app.state.db = init_db(seed=True)
except Exception:
    app.state.db = None


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


class VerifyVisitRequest(BaseModel):
    supervisor_notes: str | None = None


class UpdateReferralStatusRequest(BaseModel):
    referral_status: str
    supervisor_notes: str | None = None


def _session_manager() -> SessionManager:
    return app.state.session_manager


def _db() -> Database:
    if not hasattr(app.state, "db") or app.state.db is None:
        try:
            app.state.db = init_db(seed=True)
        except Exception:
            app.state.db = init_db(":memory:", seed=True)
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

    risk_score = None
    risk_tier = None
    if session.risk_assessment:
        risk_score = session.risk_assessment.get("score")
        risk_tier = session.risk_assessment.get("tier")

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
        transcript_turn1=session.transcript_turn1,
        transcript_turn2=session.transcript_turn2,
        transcripts_json=session.transcripts,
        risk_score=risk_score,
        risk_tier=risk_tier,
        referral_status="REFERRED" if session.evaluation.flag else "NOT_REQUIRED",
    )
    return {"status": "ok", "saved_visit": asdict(saved)}


@app.get("/api/supervisor/summary")
def get_supervisor_summary() -> dict[str, Any]:
    """Provide high-level village/sector metrics for PHC / ANM supervisor."""
    return _db().get_supervisor_summary()


@app.get("/api/supervisor/patients")
def get_supervisor_patients(
    query: str | None = None,
    village: str | None = None,
    risk_tier: str | None = None,
    overdue_only: bool = False,
) -> dict[str, Any]:
    """List expectant mothers ranked by risk and clinical need."""
    patients = _db().list_patients(query=query)
    results = []

    for p in patients:
        if village and p.village and p.village.lower() != village.lower():
            continue

        visits = _db().get_patient_visits(p.id)
        latest_visit = visits[-1] if visits else None

        # Build vitals & risk
        latest_vitals = None
        score = 0
        tier = "LOW"
        color = "#10b981"
        badge = "Low Risk - Routine Care"
        danger_count = 0
        is_overdue = False
        overdue_reason = None
        anc_stage = "ANC 1"
        referral_flag = None
        referral_status = "NOT_REQUIRED"

        if latest_visit:
            latest_vitals = {
                "visit_number": latest_visit.visit_number,
                "gestational_weeks": latest_visit.gestational_weeks,
                "bp_systolic": latest_visit.bp_systolic,
                "bp_diastolic": latest_visit.bp_diastolic,
                "weight_kg": latest_visit.weight_kg,
                "hemoglobin": latest_visit.hemoglobin,
                "created_at": latest_visit.created_at,
            }
            referral_flag = latest_visit.referral_flag
            referral_status = latest_visit.referral_status

            # Count danger signs
            danger_count = sum(
                1
                for k, v in latest_visit.tri_state_json.items()
                if v == "present"
            )

            # Risk computation
            score = latest_visit.risk_score or 0
            tier = latest_visit.risk_tier or ("HIGH" if score >= 60 else "MODERATE" if score >= 30 else "LOW")
            if tier == "HIGH":
                color = "#ef4444"
                badge = "High Risk — Immediate Action"
            elif tier == "MODERATE":
                color = "#f59e0b"
                badge = "Moderate Risk — ANM Review"
            else:
                color = "#10b981"
                badge = "Low Risk — Routine Care"

        # Check filter
        if risk_tier and risk_tier.upper() != "ALL" and tier != risk_tier.upper():
            continue

        if overdue_only and not is_overdue:
            continue

        results.append({
            "patient": asdict(p),
            "visits_count": len(visits),
            "latest_visit": latest_vitals,
            "risk_score": score,
            "risk_tier": tier,
            "risk_color": color,
            "risk_badge": badge,
            "danger_count": danger_count,
            "referral_flag": referral_flag,
            "referral_status": referral_status,
            "is_overdue": is_overdue,
            "overdue_reason": overdue_reason,
        })

    # Sort: HIGH risk first, then highest risk_score
    results.sort(key=lambda item: (-1 if item["risk_tier"] == "HIGH" else 0 if item["risk_tier"] == "MODERATE" else 1, -item["risk_score"]))

    return {"count": len(results), "patients": results}


@app.get("/api/supervisor/patient/{rch_id}")
def get_supervisor_patient_detail(rch_id: str) -> dict[str, Any]:
    """Return complete longitudinal clinical records, transcripts, and risk assessment."""
    patient = _db().get_patient_by_rch(rch_id)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {rch_id} not found.")

    visits = _db().get_patient_visits(patient.id)
    serialized_visits = [asdict(v) for v in visits]

    # Compute latest full risk breakdown if visits exist
    assessment_dict = None
    if visits:
        latest = visits[-1]
        rec = ANCVisitRecord(
            gestational_weeks=latest.gestational_weeks,
            bp_systolic=latest.bp_systolic,
            bp_diastolic=latest.bp_diastolic,
            weight_kg=latest.weight_kg,
            hemoglobin=latest.hemoglobin,
            evidence_spans=latest.evidence_json,
            **{
                k: v for k, v in latest.tri_state_json.items()
                if hasattr(ANCVisitRecord, k)
            }
        )
        past_list = [asdict(v) for v in visits[:-1]]
        assessment = compute_risk_score(rec, previous_visits=past_list, patient_age=patient.age)
        assessment_dict = asdict(assessment)

    return {
        "patient": asdict(patient),
        "visits": serialized_visits,
        "risk_assessment": assessment_dict,
    }


@app.post("/api/visits/{visit_id}/verify")
def verify_visit_supervisor(visit_id: str, req: VerifyVisitRequest) -> dict[str, Any]:
    """Clinician audit sign-off for a recorded ASHA home visit."""
    success = _db().verify_visit(visit_id, supervisor_notes=req.supervisor_notes)
    if not success:
        raise HTTPException(status_code=404, detail=f"Visit {visit_id} not found.")
    return {"status": "ok", "visit_id": visit_id, "verified": True}


@app.post("/api/visits/{visit_id}/referral-status")
def update_visit_referral_status(visit_id: str, req: UpdateReferralStatusRequest) -> dict[str, Any]:
    """Update hospital/PHC triage status of a referred mother."""
    success = _db().update_referral_status(
        visit_id, referral_status=req.referral_status, supervisor_notes=req.supervisor_notes
    )
    if not success:
        raise HTTPException(status_code=404, detail=f"Visit {visit_id} not found.")
    return {"status": "ok", "visit_id": visit_id, "referral_status": req.referral_status}


@app.get("/api/visits/{visit_id}/audit")
def get_visit_audit(visit_id: str) -> dict[str, Any]:
    """Get full transparent audit trail with audio transcripts and extraction mapping."""
    visit = _db().get_visit_by_id(visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail=f"Visit {visit_id} not found.")
    patient = _db().get_patient_by_id(visit.patient_id)
    return {
        "visit": asdict(visit),
        "patient": asdict(patient) if patient else None,
        "transcripts": visit.transcripts_json,
        "transcript_turn1": visit.transcript_turn1,
        "transcript_turn2": visit.transcript_turn2,
        "evidence": visit.evidence_json,
        "rule_ids": visit.rule_ids,
        "verified_by_supervisor": visit.verified_by_supervisor,
        "supervisor_notes": visit.supervisor_notes,
    }


@app.get("/dashboard")
@app.get("/supervisor")
def serve_dashboard() -> FileResponse:
    """Serve the dedicated Supervisor / ANM analytics dashboard."""
    return FileResponse("app/static/dashboard.html")


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


class WhatsAppSimulateRequest(BaseModel):
    sender: str = "+919876543210"
    message: str | None = None
    language: str = "hi-IN"
    audio_b64: str | None = None


@app.post("/api/whatsapp/simulate")
def simulate_whatsapp(req: WhatsAppSimulateRequest) -> dict[str, Any]:
    """Test endpoint for judges/developers to simulate WhatsApp bot messages."""
    audio_bytes = None
    if req.audio_b64:
        try:
            import base64
            audio_bytes = base64.b64decode(req.audio_b64)
        except Exception:
            pass
    return handle_whatsapp_message(
        sender=req.sender,
        body=req.message,
        audio_bytes=audio_bytes,
        session_manager=_session_manager(),
        db=_db(),
        language=req.language,
    )


@app.post("/api/whatsapp/webhook")
async def whatsapp_webhook(request: Request) -> Response:
    """Twilio WhatsApp Business API Webhook handler."""
    content_type = request.headers.get("content-type", "")
    body_text = None
    sender = "+919876543210"
    media_url = None

    if "application/json" in content_type:
        data = await request.json()
        sender = data.get("From") or data.get("sender") or sender
        body_text = data.get("Body") or data.get("message")
        media_url = data.get("MediaUrl0") or data.get("media_url")
    else:
        form = await request.form()
        sender = form.get("From") or sender
        body_text = form.get("Body")
        media_url = form.get("MediaUrl0")

    result = handle_whatsapp_message(
        sender=str(sender),
        body=str(body_text) if body_text else None,
        media_url=str(media_url) if media_url else None,
        session_manager=_session_manager(),
        db=_db(),
    )

    twiml = to_twiml_response(result["reply_text"])
    return Response(content=twiml, media_type="application/xml")


@app.get("/api/whatsapp/conversations")
def get_whatsapp_audit_log() -> list[dict[str, Any]]:
    """Supervisor view of recent WhatsApp bot conversations."""
    return _WHATSAPP_AUDIT_LOG[-50:]


@app.post("/api/session/{session_id}/audio-summary")
@app.get("/api/session/{session_id}/audio-summary")
def get_session_audio_summary(session_id: str, language: str | None = None) -> dict[str, Any]:
    """Generate or retrieve a spoken Indic audio summary for low-literacy ASHA workers and families."""
    manager = _session_manager()
    session = _get_session_or_404(manager, session_id)
    return generate_visit_audio_summary(session, target_language=language)


app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
