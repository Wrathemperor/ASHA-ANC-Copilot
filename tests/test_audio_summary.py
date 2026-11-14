"""Unit tests for multilingual spoken summary generation."""

from app.audio_summary import build_spoken_summary_text, generate_visit_audio_summary
from app.gnani.demo import DemoTimbreClient
from app.gnani.timbre import TimbreClient
from app.schema import ANCVisitRecord
from app.session import SessionState
from app.rules import evaluate_visit


def test_build_spoken_summary_hindi():
    session = SessionState(session_id="test-1", language="hi-IN")
    session.linked_patient = {"name": "Sunita Devi", "rch_id": "109283748291"}
    session.record = ANCVisitRecord(
        gestational_weeks=28,
        bp_systolic=140,
        bp_diastolic=95,
        hemoglobin=9.5,
        severe_headache="present",
    )
    session.evaluation = evaluate_visit(session.record)
    text = build_spoken_summary_text(session, target_language="hi-IN")

    assert "Sunita Devi" in text
    assert "109283748291" in text
    assert "28" in text
    assert "140 बटा 95" in text
    assert "तेज सिरदर्द" in text
    assert "स्वास्थ्य केंद्र" in text or "चिकित्सक" in text or "अस्पताल" in text


def test_build_spoken_summary_english():
    session = SessionState(session_id="test-2", language="en-IN")
    session.linked_patient = {"name": "Ananya Sharma", "rch_id": "998877665544"}
    session.record = ANCVisitRecord(
        gestational_weeks=32,
        bp_systolic=118,
        bp_diastolic=76,
        hemoglobin=12.2,
    )
    session.evaluation = evaluate_visit(session.record)
    text = build_spoken_summary_text(session, target_language="en-IN")

    assert "Ananya Sharma" in text
    assert "32 weeks" in text
    assert "normal" in text
    assert "routine" in text.lower() or "continue" in text.lower()


def test_generate_visit_audio_summary_demo_timbre():
    session = SessionState(session_id="test-3", language="hi-IN")
    session.record = ANCVisitRecord(gestational_weeks=24, bp_systolic=120, bp_diastolic=80)
    session.evaluation = evaluate_visit(session.record)

    client = TimbreClient(sdk_client=DemoTimbreClient())
    res = generate_visit_audio_summary(session, target_language="hi-IN", timbre_client=client)

    assert res["language"] == "hi-IN"
    assert res["text"]
    assert res["has_audio"] is True
    assert res["audio_playback_b64"] is not None
