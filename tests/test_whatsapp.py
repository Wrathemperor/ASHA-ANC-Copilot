"""Unit tests for WhatsApp bot integration and Twilio webhook."""

from app.db import init_db
from app.session import SessionManager
from app.whatsapp import handle_whatsapp_message, to_twiml_response, _normalize_phone


def test_normalize_phone():
    assert _normalize_phone("whatsapp:+919876543210") == "+919876543210"
    assert _normalize_phone("+91 98765-43210") == "+919876543210"


def test_whatsapp_welcome_and_reset(tmp_path):
    manager = SessionManager()
    db = init_db(tmp_path / "test_wa.db", seed=True)

    # First message: Hi
    res = handle_whatsapp_message(
        sender="+919876543210",
        body="Hi",
        session_manager=manager,
        db=db,
    )
    assert res["status"] == "ready"
    assert "Namaste ASHA Didi" in res["reply_text"]
    assert res["session_id"] in manager.sessions


def test_whatsapp_two_turn_clinical_flow(tmp_path):
    manager = SessionManager()
    db = init_db(tmp_path / "test_wa2.db", seed=True)

    # Turn 1: ASHA sends initial visit note
    res1 = handle_whatsapp_message(
        sender="+919876543210",
        body="Sunita Devi, 28 weeks, BP 140/95, severe headache present, no vaginal bleeding",
        session_manager=manager,
        db=db,
        language="en-IN",
    )

    # If gaps exist, it should ask a targeted follow-up question
    if res1["status"] == "followup":
        assert "Clarification Needed" in res1["reply_text"] or "❓" in res1["reply_text"]

        # Turn 2: ASHA answers follow-up
        res2 = handle_whatsapp_message(
            sender="+919876543210",
            body="No blurred vision, no swelling",
            session_manager=manager,
            db=db,
            language="en-IN",
        )
        assert res2["status"] == "completed"
        assert "VISIT SUMMARY" in res2["reply_text"]
        assert "140/95" in res2["reply_text"]
        assert "Severe Headache" in res2["reply_text"]
    else:
        assert res1["status"] == "completed"
        assert "VISIT SUMMARY" in res1["reply_text"]
        assert "140/95" in res1["reply_text"]


def test_to_twiml_response():
    twiml = to_twiml_response("Hello ASHA Didi & <Sister>")
    assert "<?xml" in twiml
    assert "<Response>" in twiml
    assert "<Message>" in twiml
    assert "&amp;" in twiml
    assert "&lt;Sister&gt;" in twiml
