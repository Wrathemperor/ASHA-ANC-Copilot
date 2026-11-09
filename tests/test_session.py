from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.session import (
    EMERGENCY_HALT,
    FINAL_LOCKED,
    FOLLOWUP_ACTIVE,
    HALT_REPEAT,
    MANUAL_EDIT_REQUIRED,
    READBACK_ACTIVE,
    SessionManager,
)


class MockPrismaClient:
    def __init__(self, *transcripts: str | Exception) -> None:
        self.transcripts = list(transcripts)
        self.calls: list[dict[str, Any]] = []

    def transcribe(
        self,
        audio: bytes,
        language: str,
        previous_text: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {"audio": audio, "language": language, "previous_text": previous_text}
        )
        response = self.transcripts.pop(0)
        if isinstance(response, Exception):
            raise response
        return {"success": True, "transcript": response, "truncated": False}


class MockEvonClient:
    def __init__(self, *responses: dict[str, Any]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        self.calls.append((system, user))
        return self.responses.pop(0)


class MockTimbreClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def synthesize(self, text: str, language: str) -> bytes:
        self.calls.append((text, language))
        return b"RIFF-test-audio"


class FailingTimbreClient:
    def synthesize(self, text: str, language: str) -> bytes:
        raise RuntimeError("offline")


@pytest.fixture
def extracted_record() -> dict[str, Any]:
    return {
        "gestational_weeks": 14,
        "bp_systolic": 120,
        "bp_diastolic": 80,
        "swelling": "denied",
        "severe_headache": "not_mentioned",
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


def build_manager(
    prisma: MockPrismaClient,
    evon: MockEvonClient,
    timbre: MockTimbreClient | None = None,
) -> SessionManager:
    return SessionManager(
        prisma_client=prisma,
        evon_client=evon,
        timbre_client=timbre or MockTimbreClient(),
    )


def test_complete_happy_path_turn1_followup_readback_and_lock(
    extracted_record: dict[str, Any],
) -> None:
    turn2 = dict(extracted_record, severe_headache="denied")
    correction = {
        "confirmed": True,
        "bp_systolic": None,
        "bp_diastolic": None,
        "gestational_weeks": None,
        "evidence": "haan sahi hai",
    }
    prisma = MockPrismaClient(
        "Pregnant for fourteen weeks, blood pressure one twenty by eighty.",
        "sir dard nahi hai",
        "haan sahi hai",
    )
    evon = MockEvonClient(extracted_record, turn2, correction)
    manager = build_manager(prisma, evon)
    session = manager.create_session("hi-IN")

    first = manager.process_turn1(session.session_id, b"turn one")
    assert first.state == FOLLOWUP_ACTIVE
    assert first.current_gap_field == "severe_headache"
    assert first.prompt_text
    assert first.audio_playback_b64
    first_question = first.prompt_text

    second = manager.process_followup(session.session_id, b"turn two")
    assert second.state == READBACK_ACTIVE
    assert second.followup_turn_count == 1
    assert second.record.severe_headache == "denied"
    assert prisma.calls[1]["previous_text"] == first_question

    final = manager.process_readback(session.session_id, b"confirmation")
    assert final.state == FINAL_LOCKED
    assert final.record.gestational_weeks == 14
    assert prisma.calls[2]["previous_text"] == second.prompt_text


def test_turn1_emergency_bypasses_followups(extracted_record: dict[str, Any]) -> None:
    emergency = dict(extracted_record, vaginal_bleeding="present")
    prisma = MockPrismaClient("She is pregnant and has vaginal bleeding.")
    timbre = MockTimbreClient()
    manager = build_manager(prisma, MockEvonClient(emergency), timbre)
    session = manager.create_session()

    result = manager.process_turn1(session.session_id, b"audio")

    assert result.state == EMERGENCY_HALT
    assert result.evaluation.emergency_bypass is True
    assert result.followup_turn_count == 0
    assert timbre.calls == []


def test_unsolicited_turn2_emergency_immediately_bypasses_followups(
    extracted_record: dict[str, Any],
) -> None:
    first_record = dict(
        extracted_record,
        vaginal_bleeding="not_mentioned",
        convulsions="not_mentioned",
    )
    followup_record = dict(
        extracted_record,
        vaginal_bleeding="denied",
        convulsions="present",
    )
    manager = build_manager(
        MockPrismaClient(
            "Pregnant for fourteen weeks, feeling well today.",
            "No headache and she had convulsions.",
        ),
        MockEvonClient(first_record, followup_record),
    )
    session = manager.create_session()

    assert manager.process_turn1(session.session_id, b"one").state == FOLLOWUP_ACTIVE
    result = manager.process_followup(session.session_id, b"two")

    assert result.state == EMERGENCY_HALT
    assert result.evaluation.emergency_bypass is True
    assert result.record.convulsions == "present"
    assert result.followup_turn_count == 1


@pytest.mark.parametrize("transcript", ("", "yes ok"))
def test_turn1_empty_or_short_transcript_halts_and_plays_repeat_prompt(
    transcript: str,
) -> None:
    manager = build_manager(
        MockPrismaClient(transcript),
        MockEvonClient(),
    )
    session = manager.create_session("en-IN")

    result = manager.process_turn1(session.session_id, b"audio")

    assert result.state == HALT_REPEAT
    assert result.halt_reason
    assert result.prompt_text == "I could not hear that clearly. Please say it again."
    assert result.audio_playback_b64


def test_halt_repeat_session_can_submit_a_repeated_turn1(
    extracted_record: dict[str, Any],
) -> None:
    manager = build_manager(
        MockPrismaClient("ok", "Pregnant for fourteen weeks, feeling well today."),
        MockEvonClient(dict(extracted_record, severe_headache="denied")),
    )
    session = manager.create_session("en-IN")
    assert manager.process_turn1(session.session_id, b"unclear").state == HALT_REPEAT

    retried = manager.process_turn1(session.session_id, b"clear-repeat")

    assert retried.state == READBACK_ACTIVE


def test_turn2_conflict_never_overwrites_turn1_value(
    extracted_record: dict[str, Any],
) -> None:
    first_record = dict(extracted_record, vaginal_bleeding="denied")
    second_record = dict(
        extracted_record,
        severe_headache="denied",
        vaginal_bleeding="present",
    )
    manager = build_manager(
        MockPrismaClient(
            "Pregnant for fourteen weeks, has severe headache.",
            "No headache, but bleeding is present.",
        ),
        MockEvonClient(first_record, second_record),
    )
    session = manager.create_session()

    manager.process_turn1(session.session_id, b"one")
    result = manager.process_followup(session.session_id, b"two")

    assert result.record.vaginal_bleeding == "denied"
    assert result.state == READBACK_ACTIVE
    assert result.conflicts == [
        {
            "field": "vaginal_bleeding",
            "turn1_value": "denied",
            "turn2_value": "present",
            "turn2_evidence": None,
        }
    ]

    correction = {
        "confirmed": True,
        "bp_systolic": None,
        "bp_diastolic": None,
        "gestational_weeks": None,
        "evidence": "yes correct",
    }
    manager.evon_client.responses.append(correction)
    manager.prisma_client.transcripts.append("yes correct")
    confirmed = manager.process_readback(session.session_id, b"confirm")
    assert confirmed.state == MANUAL_EDIT_REQUIRED


def test_readback_correction_is_applied_then_requires_manual_confirmation(
    extracted_record: dict[str, Any],
) -> None:
    correction = {
        "confirmed": False,
        "bp_systolic": 130,
        "bp_diastolic": 80,
        "gestational_weeks": None,
        "evidence": "BP 130 over 80",
    }
    readback_record = dict(extracted_record, severe_headache="denied")
    manager = build_manager(
        MockPrismaClient(
            "Pregnant for fourteen weeks, blood pressure one twenty by eighty.",
            "BP 130 over 80",
        ),
        MockEvonClient(readback_record, correction),
    )
    session = manager.create_session()
    assert manager.process_turn1(session.session_id, b"one").state == READBACK_ACTIVE

    result = manager.process_readback(session.session_id, b"correction")

    assert result.state == MANUAL_EDIT_REQUIRED
    assert result.record.bp_systolic == 130
    assert result.record.bp_diastolic == 80
    assert result.readback_attempts == 1
    with pytest.raises(ValueError, match="not waiting"):
        manager.process_readback(session.session_id, b"second correction")

    final = manager.manual_confirm(session.session_id, {})
    assert final.state == FINAL_LOCKED


def test_maximum_two_followup_turns_is_respected(
    extracted_record: dict[str, Any],
) -> None:
    first_record = dict(
        extracted_record,
        severe_headache="not_mentioned",
        blurred_vision="not_mentioned",
    )
    first_answer = dict(
        extracted_record,
        severe_headache="denied",
        blurred_vision="not_mentioned",
    )
    second_answer = dict(extracted_record, blurred_vision="denied")
    manager = build_manager(
        MockPrismaClient(
            "Pregnant for fourteen weeks, no other concerns today.",
            "No severe headache.",
            "No blurred vision.",
        ),
        MockEvonClient(first_record, first_answer, second_answer),
    )
    session = manager.create_session()

    assert manager.process_turn1(session.session_id, b"one").state == FOLLOWUP_ACTIVE
    assert manager.process_followup(session.session_id, b"two").state == FOLLOWUP_ACTIVE
    final_turn = manager.process_followup(session.session_id, b"three")

    assert final_turn.state == READBACK_ACTIVE
    assert final_turn.followup_turn_count == 2
    assert len(manager.prisma_client.calls) == 3


def test_gaps_without_reviewed_template_require_manual_edit(
    extracted_record: dict[str, Any],
) -> None:
    record = dict(extracted_record, severe_headache="denied", convulsions="not_mentioned")
    manager = build_manager(
        MockPrismaClient("Pregnant for fourteen weeks, feels fine today."),
        MockEvonClient(record),
    )
    session = manager.create_session()

    result = manager.process_turn1(session.session_id, b"audio")

    assert result.state == MANUAL_EDIT_REQUIRED
    assert result.halt_reason == (
        "No approved question template exists for required field: convulsions."
    )
    assert result.current_gap_field is None


def test_timbre_failure_keeps_question_text_as_fallback(
    extracted_record: dict[str, Any],
) -> None:
    record = dict(extracted_record, severe_headache="not_mentioned")
    manager = SessionManager(
        prisma_client=MockPrismaClient(
            "Pregnant for fourteen weeks, feeling okay today."
        ),
        evon_client=MockEvonClient(record),
        timbre_client=FailingTimbreClient(),
    )
    session = manager.create_session("en-IN")

    result = manager.process_turn1(session.session_id, b"audio")

    assert result.state == FOLLOWUP_ACTIVE
    assert result.prompt_text == "Do you have a severe headache?"
    assert result.audio_playback_b64 is None
    assert "Timbre audio unavailable" in (result.halt_reason or "")


def test_manual_confirm_validates_updates_and_locks_record(
    extracted_record: dict[str, Any],
) -> None:
    manager = build_manager(
        MockPrismaClient(),
        MockEvonClient(),
    )
    session = manager.create_session()

    with pytest.raises(ValueError, match="Unsupported"):
        manager.manual_confirm(session.session_id, {"not_a_field": "present"})
    with pytest.raises(ValueError, match="Invalid"):
        manager.manual_confirm(session.session_id, {"vaginal_bleeding": "unknown"})

    result = manager.manual_confirm(
        session.session_id,
        {"vaginal_bleeding": "denied", "gestational_weeks": 14},
    )
    assert result.state == FINAL_LOCKED
    assert result.record.vaginal_bleeding == "denied"
    assert result.record.gestational_weeks == 14


def test_session_api_start_get_and_manual_edit_routes() -> None:
    original_manager = app.state.session_manager
    app.state.session_manager = SessionManager(
        prisma_client=MockPrismaClient(),
        evon_client=MockEvonClient(),
        timbre_client=MockTimbreClient(),
    )
    try:
        client = TestClient(app)
        created = client.post("/api/session/start", json={"language": "en-IN"})
        assert created.status_code == 200
        session_id = created.json()["session_id"]

        current = client.get(f"/api/session/{session_id}")
        assert current.status_code == 200
        assert current.json()["state"] == "IDLE"

        edited = client.post(
            f"/api/session/{session_id}/manual-edit",
            json={"gestational_weeks": 14, "vaginal_bleeding": "denied"},
        )
        assert edited.status_code == 200
        assert edited.json()["state"] == FINAL_LOCKED

        missing = client.get("/api/session/missing")
        assert missing.status_code == 404
    finally:
        app.state.session_manager = original_manager


def test_session_audio_routes_run_complete_happy_path(
    extracted_record: dict[str, Any],
) -> None:
    turn2 = dict(extracted_record, severe_headache="denied")
    confirmed = {
        "confirmed": True,
        "bp_systolic": None,
        "bp_diastolic": None,
        "gestational_weeks": None,
        "evidence": "yes correct",
    }
    original_manager = app.state.session_manager
    app.state.session_manager = build_manager(
        MockPrismaClient(
            "Pregnant for fourteen weeks, blood pressure one twenty by eighty.",
            "No headache.",
            "yes correct",
        ),
        MockEvonClient(extracted_record, turn2, confirmed),
    )
    try:
        client = TestClient(app)
        session_id = client.post(
            "/api/session/start", json={"language": "en-IN"}
        ).json()["session_id"]

        first = client.post(
            f"/api/session/{session_id}/turn1",
            files={"audio": ("turn1.wav", b"first", "audio/wav")},
        )
        assert first.status_code == 200
        assert first.json()["state"] == FOLLOWUP_ACTIVE

        second = client.post(
            f"/api/session/{session_id}/followup",
            files={"audio": ("followup.wav", b"second", "audio/wav")},
        )
        assert second.status_code == 200
        assert second.json()["state"] == READBACK_ACTIVE

        final = client.post(
            f"/api/session/{session_id}/readback",
            files={"audio": ("readback.wav", b"third", "audio/wav")},
        )
        assert final.status_code == 200
        assert final.json()["state"] == FINAL_LOCKED
    finally:
        app.state.session_manager = original_manager
