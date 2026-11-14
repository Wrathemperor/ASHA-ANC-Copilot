"""WhatsApp Bot Interface for ASHA Field Workers.

Supports:
1. Twilio WhatsApp Business API Webhook (x-www-form-urlencoded & TwiML response)
2. Live Interactive Simulator Webhook (JSON payload & response)
3. Voice note (audio) and text-based visit logging
4. Automated Indic follow-up prompts and referral dispatch
"""

from __future__ import annotations

import base64
import html
import re
from dataclasses import asdict
from typing import Any

from app.audio_summary import build_spoken_summary_text
from app.db import Database
from app.extraction import extract_visit_record
from app.risk import compute_risk_score
from app.rules import evaluate_visit
from app.schema import ANCVisitRecord, merge_turn2_update
from app.session import FINAL_LOCKED, FOLLOWUP_ACTIVE, IDLE, SessionManager, SessionState

# In-memory mapping of phone numbers to active session IDs
_WHATSAPP_SESSIONS: dict[str, str] = {}
# Recent message logs for supervisor and demo auditing
_WHATSAPP_AUDIT_LOG: list[dict[str, Any]] = []


def _normalize_phone(phone: str) -> str:
    cleaned = phone.strip()
    if cleaned.startswith("whatsapp:"):
        cleaned = cleaned[len("whatsapp:"):]
    return re.sub(r"[^\d+]", "", cleaned)


def _parse_text_vitals(text: str, current: ANCVisitRecord) -> ANCVisitRecord:
    lower = text.lower()
    
    # Blood Pressure: 140/95 or 140 by 95 or 140 over 95
    bp_match = re.search(r'\b(\d{2,3})\s*(?:/|by|over)\s*(\d{2,3})\b', lower)
    if bp_match:
        current.bp_systolic = int(bp_match.group(1))
        current.bp_diastolic = int(bp_match.group(2))
        current.evidence_spans["bp_systolic"] = bp_match.group(0)
        current.evidence_spans["bp_diastolic"] = bp_match.group(0)

    # Gestational Weeks: 28 weeks, 32 wks, 28 hafta
    wk_match = re.search(r'\b(\d{1,2})\s*(?:weeks?|wks?|hafta|hafte)\b', lower)
    if wk_match:
        current.gestational_weeks = int(wk_match.group(1))
        current.evidence_spans["gestational_weeks"] = wk_match.group(0)

    # Weight: 58 kg
    wt_match = re.search(r'\b(\d{2}(?:\.\d)?)\s*(?:kg|kilos?)\b', lower)
    if wt_match:
        current.weight_kg = float(wt_match.group(1))
        current.evidence_spans["weight_kg"] = wt_match.group(0)

    # Hemoglobin: Hb 9.5 or 9.5 hb
    hb_match = re.search(r'(?:hb|hemoglobin)\s*[:=]?\s*(\d{1,2}(?:\.\d)?)|(\d{1,2}(?:\.\d)?)\s*(?:gm|g/dl|hb)', lower)
    if hb_match:
        hb_val = hb_match.group(1) or hb_match.group(2)
        if hb_val:
            current.hemoglobin = float(hb_val)
            current.evidence_spans["hemoglobin"] = hb_match.group(0)

    # Symptoms check with denial detection
    symptom_patterns = [
        ("severe_headache", r"headache|sir\s*dard|sar\s*dard"),
        ("blurred_vision", r"blurred\s*vision|dhundla"),
        ("swelling", r"swelling|sujan"),
        ("vaginal_bleeding", r"bleeding|blood|raktsrav"),
        ("reduced_fetal_movement", r"movement|halchal"),
        ("severe_abdominal_pain", r"abdominal\s*pain|pet\s*dard"),
        ("fever", r"fever|bukhar"),
    ]
    for field_name, pattern in symptom_patterns:
        match = re.search(pattern, lower)
        if match:
            start = max(0, match.start() - 25)
            end = min(len(lower), match.end() + 25)
            context = lower[start:end]
            if re.search(r'\b(no|not|denied|nahi|nhi|none|without)\b', context):
                setattr(current, field_name, "denied")
            elif re.search(r'\b(normal|theek|accha)\b', context) and field_name == "reduced_fetal_movement":
                setattr(current, field_name, "denied")
            else:
                setattr(current, field_name, "present")
            current.evidence_spans[field_name] = match.group(0)

    return current


def _format_whatsapp_summary(session: SessionState) -> str:
    """Format rich clinical visit summary for WhatsApp with Markdown."""
    rec = session.record
    patient = session.linked_patient or {}
    name = patient.get("name") or "Expectant Mother"
    rch_id = patient.get("rch_id") or "Not registered"
    village = patient.get("village") or "Field Area"
    weeks = f"{rec.gestational_weeks} wks" if rec.gestational_weeks is not None else "Not specified"

    # Vitals
    bp_str = "Not recorded"
    if rec.bp_systolic is not None and rec.bp_diastolic is not None:
        bp_alert = "⚠️ (High)" if (rec.bp_systolic >= 140 or rec.bp_diastolic >= 90) else "✅ (Normal)"
        bp_str = f"{rec.bp_systolic}/{rec.bp_diastolic} mmHg {bp_alert}"

    hb_str = "Not recorded"
    if rec.hemoglobin is not None:
        hb_alert = "⚠️ (Low)" if rec.hemoglobin < 11.0 else "✅ (Normal)"
        hb_str = f"{rec.hemoglobin} g/dL {hb_alert}"

    wt_str = f"{rec.weight_kg} kg" if rec.weight_kg is not None else "Not recorded"

    # Danger signs
    symptoms = []
    for symptom, label in [
        ("severe_headache", "Severe Headache"),
        ("blurred_vision", "Blurred Vision"),
        ("swelling", "Swelling"),
        ("reduced_fetal_movement", "Reduced Fetal Movement"),
        ("vaginal_bleeding", "Vaginal Bleeding"),
        ("convulsions", "Convulsions"),
        ("severe_abdominal_pain", "Abdominal Pain"),
    ]:
        val = getattr(rec, symptom, None)
        if val == "present":
            symptoms.append(f"• {label}: 🔴 Present")
        elif val == "denied":
            symptoms.append(f"• {label}: 🟢 Denied")

    if not symptoms:
        symptoms.append("• No acute danger signs reported")

    danger_text = "\n".join(symptoms)

    # Referral & Risk
    flag = session.evaluation.flag if session.evaluation else "ROUTINE_CARE"
    flag_emoji = "🚨" if flag == "URGENT_REFERRAL" else ("⚠️" if flag == "CLINICIAN_REFERRAL" else "✅")
    risk_tier = session.risk_assessment.get("tier", "LOW") if session.risk_assessment else "LOW"
    risk_score = session.risk_assessment.get("score", 0) if session.risk_assessment else 0
    tier_emoji = "🔴" if risk_tier == "HIGH" else ("🟡" if risk_tier == "MODERATE" else "🟢")

    actions = []
    if flag == "URGENT_REFERRAL":
        actions.append("Immediate PHC/District Hospital transport via 108 Ambulance.")
    elif flag == "CLINICIAN_REFERRAL":
        actions.append("Medical Officer evaluation at PHC within 48 hours.")
    else:
        actions.append("Routine ANC care. Continue IFA & Calcium daily.")

    action_text = " ".join(actions)

    return (
        f"*{flag_emoji} ASHA ANC COPILOT — VISIT SUMMARY*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"*Mother:* {name}\n"
        f"*RCH ID:* `{rch_id}` | *Village:* {village}\n"
        f"*Gestation:* {weeks}\n\n"
        f"*🩺 Vitals:*\n"
        f"• Blood Pressure: {bp_str}\n"
        f"• Hemoglobin: {hb_str}\n"
        f"• Weight: {wt_str}\n\n"
        f"*⚠️ Danger Signs:*\n"
        f"{danger_text}\n\n"
        f"*📋 Referral Decision:* *{flag}*\n"
        f"*Risk Assessment:* {tier_emoji} *{risk_tier}* (Score: {risk_score}/100)\n"
        f"*Clinical Action:* {action_text}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"_Reply *NEW* to start another visit._"
    )


def handle_whatsapp_message(
    sender: str,
    body: str | None = None,
    media_url: str | None = None,
    audio_bytes: bytes | None = None,
    session_manager: SessionManager | None = None,
    db: Database | None = None,
    language: str = "hi-IN",
) -> dict[str, Any]:
    """Process an incoming WhatsApp interaction for an ASHA worker."""
    if session_manager is None:
        from app.main import _session_manager
        session_manager = _session_manager()

    sender_clean = _normalize_phone(sender)
    body_text = (body or "").strip()

    # Log interaction
    _WHATSAPP_AUDIT_LOG.append({
        "sender": sender_clean,
        "body": body_text,
        "has_media": bool(media_url or audio_bytes),
        "timestamp": None,
    })

    # Command: Reset / New Visit
    if body_text.lower() in {"new", "reset", "start", "shuru", "hi", "hello"}:
        session = session_manager.create_session(language=language)
        _WHATSAPP_SESSIONS[sender_clean] = session.session_id
        
        # Link a default demo patient if DB available
        if db:
            patients = db.list_patients()
            if patients:
                first_p = patients[0]
                visits = db.get_patient_visits(first_p.id)
                session_manager.link_patient(session.session_id, first_p, visits)

        welcome_msg = (
            "👋 *Namaste ASHA Didi! Welcome to ASHA ANC Copilot.*\n\n"
            "You can record an ANC visit right here on WhatsApp:\n"
            "1. 🎙️ *Send a voice note* describing mother's vitals & symptoms in your language.\n"
            "2. ✍️ *Or type the notes* (e.g., _Sunita Devi, 28 weeks, BP 140/90, severe headache_)\n\n"
            "_I will extract vitals, check MoHFW high-risk danger signs, and generate a referral slip instantly._"
        )
        return {
            "session_id": session.session_id,
            "reply_text": welcome_msg,
            "status": "ready",
            "audio_url": None,
        }

    # Retrieve or create session for this phone number
    session_id = _WHATSAPP_SESSIONS.get(sender_clean)
    if not session_id or session_id not in session_manager.sessions:
        session = session_manager.create_session(language=language)
        session_id = session.session_id
        _WHATSAPP_SESSIONS[sender_clean] = session_id
        if db:
            patients = db.list_patients()
            if patients:
                first_p = patients[0]
                visits = db.get_patient_visits(first_p.id)
                session_manager.link_patient(session.session_id, first_p, visits)
    else:
        session = session_manager.get_session(session_id)

    # 1. Processing Voice Note (if provided)
    if audio_bytes:
        if session.state in {IDLE, "HALT_REPEAT"}:
            session = session_manager.process_turn1(session_id, audio_bytes)
        elif session.state == FOLLOWUP_ACTIVE:
            session = session_manager.process_followup(session_id, audio_bytes)

    # 2. Processing Text Message (if text was sent)
    elif body_text:
        # Check if user mentioned an RCH ID to link
        rch_match = re.search(r"\b\d{12}\b", body_text)
        if rch_match and db:
            rch_found = db.get_patient_by_rch(rch_match.group(0))
            if rch_found:
                visits = db.get_patient_visits(rch_found.id)
                session = session_manager.link_patient(session_id, rch_found, visits)

        if session.state in {IDLE, "HALT_REPEAT"}:
            # Extract from text via LLM or rule fallback
            try:
                record = extract_visit_record(body_text, language=session.language)
            except Exception:
                record = ANCVisitRecord()
            record = _parse_text_vitals(body_text, record)
            session.record = record
            session.transcript_turn1 = body_text
            session.transcripts.append({"turn": 1, "text": body_text, "source": "whatsapp_text"})
            session.evaluation = evaluate_visit(session.record, previous_visits=session.previous_visits)
            session_manager._update_risk(session)

            # Check for critical voice followup gaps
            if session.evaluation.voice_followup_gaps and session.followup_turn_count < 2:
                session = session_manager._ask_followup(session)
            else:
                session.state = FINAL_LOCKED
        elif session.state == FOLLOWUP_ACTIVE:
            # Extract turn 2 response
            try:
                turn2_record = extract_visit_record(body_text, language=session.language)
            except Exception:
                turn2_record = ANCVisitRecord()
            turn2_record = _parse_text_vitals(body_text, turn2_record)
            session.record = merge_turn2_update(session.record, turn2_record)
            session.transcript_turn2 = body_text
            session.transcripts.append({"turn": 2, "text": body_text, "source": "whatsapp_text"})
            session.followup_turn_count += 1
            session.evaluation = evaluate_visit(session.record, previous_visits=session.previous_visits)
            session_manager._update_risk(session)
            session.state = FINAL_LOCKED

    # Check session state for reply
    if session.state == FOLLOWUP_ACTIVE and session.original_question:
        reply = (
            f"🩺 *ASHA ANC Copilot — Clarification Needed*\n\n"
            f"Vitals extracted. To complete the safety assessment:\n\n"
            f"❓ *{session.original_question}*\n\n"
            f"_Please reply with a short voice note or text message._"
        )
        return {
            "session_id": session_id,
            "reply_text": reply,
            "status": "followup",
            "audio_b64": session.audio_playback_b64,
        }

    # Final summary response
    summary_text = _format_whatsapp_summary(session)
    spoken_summary = build_spoken_summary_text(session, target_language=session.language)

    return {
        "session_id": session_id,
        "reply_text": summary_text,
        "spoken_text": spoken_summary,
        "status": "completed",
        "evaluation": asdict(session.evaluation) if session.evaluation else None,
        "risk": session.risk_assessment,
    }


def to_twiml_response(reply_text: str) -> str:
    """Format string into valid Twilio TwiML XML."""
    escaped = html.escape(reply_text)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        f"    <Message>{escaped}</Message>\n"
        "</Response>"
    )
