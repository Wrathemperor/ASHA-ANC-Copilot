"""In-memory two-turn ANC visit session state machine."""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from app.extraction import (
    extract_numeric_correction,
    extract_visit_record,
)
from app.gnani.prisma import PrismaClient
from app.gnani.timbre import TimbreClient
from app.rules import EvaluationResult, evaluate_visit
from app.schema import ANCVisitRecord, merge_turn2_update

IDLE = "IDLE"
PROCESSING_TURN1 = "PROCESSING_TURN1"
TURN1_EXTRACTED = "TURN1_EXTRACTED"
FOLLOWUP_ACTIVE = "FOLLOWUP_ACTIVE"
EMERGENCY_HALT = "EMERGENCY_HALT"
READBACK_ACTIVE = "READBACK_ACTIVE"
MANUAL_EDIT_REQUIRED = "MANUAL_EDIT_REQUIRED"
FINAL_LOCKED = "FINAL_LOCKED"
HALT_REPEAT = "HALT_REPEAT"

MAX_FOLLOWUP_TURNS = 2
MAX_READBACK_ATTEMPTS = 1
SUPPORTED_LANGUAGES = {"en-IN", "hi-IN", "mr-IN", "ta-IN", "te-IN", "ml-IN"}
_LANGUAGE_KEYS = {
    "en-IN": "en",
    "hi-IN": "hi",
    "mr-IN": "mr",
    "ta-IN": "ta",
    "te-IN": "te",
    "ml-IN": "ml",
}
_RECORD_ADAPTER = TypeAdapter(ANCVisitRecord)
_RECORD_FIELDS = {item.name for item in fields(ANCVisitRecord)}
_NON_EDITABLE_FIELDS = {"evidence_spans", "conflicts"}


@dataclass
class SessionState:
    session_id: str
    language: str = "hi-IN"
    state: str = IDLE
    record: ANCVisitRecord = field(default_factory=ANCVisitRecord)
    evaluation: EvaluationResult = field(default_factory=lambda: evaluate_visit(ANCVisitRecord()))
    followup_turn_count: int = 0
    current_gap_field: str | None = None
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    readback_attempts: int = 0
    halt_reason: str | None = None
    audio_playback_b64: str | None = None
    prompt_text: str | None = None
    original_question: str | None = None
    clarification_text: str | None = None
    asked_gap_fields: list[str] = field(default_factory=list)
    interaction_history: list[dict[str, Any]] = field(default_factory=list)
    patient_id: str | None = None
    linked_patient: dict[str, Any] | None = None
    previous_visits: list[dict[str, Any]] = field(default_factory=list)


class SessionManager:
    """Own session state and orchestrate speech, extraction, and rules."""

    def __init__(
        self,
        prisma_client: Any | None = None,
        evon_client: Any | None = None,
        timbre_client: Any | None = None,
        questions_path: Path | str | None = None,
    ) -> None:
        self.sessions: dict[str, SessionState] = {}
        self.prisma_client = prisma_client
        self.evon_client = evon_client
        self.timbre_client = timbre_client
        self.questions_path = (
            Path(questions_path)
            if questions_path is not None
            else Path(__file__).parent / "templates" / "questions.json"
        )
        self._questions: dict[str, Any] | None = None

    def create_session(self, language: str = "hi-IN") -> SessionState:
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported language: {language}")
        session_id = str(uuid.uuid4())
        session = SessionState(session_id=session_id, language=language)
        self.sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> SessionState:
        try:
            return self.sessions[session_id]
        except KeyError as error:
            raise KeyError(f"Session not found: {session_id}") from error

    def _prisma(self) -> Any:
        if self.prisma_client is None:
            self.prisma_client = PrismaClient()
        return self.prisma_client

    def _evon(self) -> Any | None:
        return self.evon_client

    def _timbre(self) -> Any:
        if self.timbre_client is None:
            self.timbre_client = TimbreClient()
        return self.timbre_client

    def _questions_for_language(self, session: SessionState) -> dict[str, str]:
        if self._questions is None:
            self._questions = json.loads(self.questions_path.read_text(encoding="utf-8"))
        language_key = _LANGUAGE_KEYS[session.language]
        return {
            key: values[language_key]
            for key, values in self._questions.items()
            if language_key in values
        }

    def _speak(self, session: SessionState, prompt_text: str) -> None:
        session.prompt_text = prompt_text
        session.audio_playback_b64 = None
        try:
            audio = self._timbre().synthesize(prompt_text, session.language)
        except Exception as error:
            # FR-11 requires a text fallback when TTS is unavailable.
            session.halt_reason = f"Timbre audio unavailable; use the displayed text prompt: {error}"
            return
        session.audio_playback_b64 = base64.b64encode(audio).decode("ascii")

    def _question_for(self, session: SessionState, field_name: str) -> str | None:
        return self._questions_for_language(session).get(field_name)

    def _ask_followup(self, session: SessionState) -> SessionState:
        if session.followup_turn_count >= MAX_FOLLOWUP_TURNS:
            return self._start_readback(session)

        next_gap = next(
            (
                gap
                for gap in session.evaluation.top_gaps
                if gap not in session.asked_gap_fields
            ),
            None,
        )
        if next_gap is None:
            return self._start_readback(session)

        question = self._question_for(session, next_gap)
        if question is None:
            session.current_gap_field = None
            session.state = MANUAL_EDIT_REQUIRED
            session.prompt_text = None
            session.audio_playback_b64 = None
            session.halt_reason = (
                f"No approved question template exists for required field: {next_gap}."
            )
            return session

        session.current_gap_field = next_gap
        session.asked_gap_fields.append(next_gap)
        session.state = FOLLOWUP_ACTIVE
        session.halt_reason = None
        session.original_question = question
        session.clarification_text = None
        session.interaction_history.append({
            "type": "followup",
            "field": next_gap,
            "title": "Follow-up Question",
            "text": question,
            "turn": session.followup_turn_count + 1,
        })
        self._speak(session, question)
        return session

    def _start_readback(self, session: SessionState) -> SessionState:
        session.current_gap_field = None
        template = self._question_for(session, "readback_confirm")
        if template is None:
            session.state = MANUAL_EDIT_REQUIRED
            session.halt_reason = "No approved read-back template exists for this language."
            session.prompt_text = None
            session.audio_playback_b64 = None
            return session

        session.state = READBACK_ACTIVE
        session.halt_reason = None
        session.clarification_text = None
        readback_prompt = template.format(
            bp_sys=session.record.bp_systolic if session.record.bp_systolic is not None else "",
            bp_dia=session.record.bp_diastolic if session.record.bp_diastolic is not None else "",
            weeks=session.record.gestational_weeks if session.record.gestational_weeks is not None else "",
        )
        session.original_question = readback_prompt
        session.interaction_history.append({
            "type": "readback",
            "field": None,
            "title": "Visit Confirmation / Read-back",
            "text": readback_prompt,
            "turn": session.followup_turn_count + 1,
        })
        self._speak(session, readback_prompt)
        return session

    def _ask_clarification(self, session: SessionState, reason: str) -> SessionState:
        session.state = FOLLOWUP_ACTIVE
        session.halt_reason = reason
        try:
            prompt = self._question_for(session, "clarify_repeat") or self._question_for(session, "halt_repeat")
        except (OSError, json.JSONDecodeError, KeyError) as error:
            prompt = "Please repeat or clarify your answer."
        session.clarification_text = prompt
        session.interaction_history.append({
            "type": "clarification",
            "field": session.current_gap_field,
            "title": "Clarification / Repeat Request",
            "subtitle": reason,
            "text": prompt,
            "turn": session.followup_turn_count + 1,
        })
        if prompt is not None:
            self._speak(session, prompt)
        return session

    def _halt_repeat(self, session: SessionState, reason: str) -> SessionState:
        session.halt_reason = reason
        try:
            prompt = self._question_for(session, "halt_repeat")
        except (OSError, json.JSONDecodeError, KeyError) as error:
            session.prompt_text = None
            session.audio_playback_b64 = None
            session.halt_reason = f"{reason} Halt-repeat prompt unavailable: {error}"
            return session

        if session.state == FOLLOWUP_ACTIVE and session.original_question is not None:
            return self._ask_clarification(session, reason)

        session.state = HALT_REPEAT
        session.current_gap_field = None
        session.interaction_history.append({
            "type": "repeat",
            "field": None,
            "title": "Repeat Request",
            "subtitle": reason,
            "text": prompt,
            "turn": 0,
        })
        if prompt is not None:
            self._speak(session, prompt)
        return session

    def _transcribe(
        self,
        session: SessionState,
        audio_bytes: bytes,
        previous_text: str | None = None,
    ) -> str:
        result = self._prisma().transcribe(
            audio_bytes,
            session.language,
            previous_text=previous_text,
        )
        if not isinstance(result, dict) or not result.get("success"):
            raise ValueError("Prisma transcription was unsuccessful.")
        if result.get("truncated") is True:
            raise ValueError("Prisma transcription was truncated.")
        transcript = result.get("transcript")
        if not isinstance(transcript, str):
            raise ValueError("Prisma returned no transcript.")
        return transcript.strip()

    def process_turn1(self, session_id: str, audio_bytes: bytes) -> SessionState:
        session = self.get_session(session_id)
        if session.state not in {IDLE, HALT_REPEAT}:
            raise ValueError("Turn 1 can only be processed for a new or repeat-requested session.")
        session.state = PROCESSING_TURN1
        try:
            transcript = self._transcribe(session, audio_bytes)
        except Exception as error:
            return self._halt_repeat(session, f"Transcription failed: {error}")
        if len(transcript.split()) < 3:
            return self._halt_repeat(session, "Transcript was empty or shorter than three words.")

        try:
            session.record = extract_visit_record(
                transcript,
                language=session.language,
                evon_client=self._evon(),
            )
        except Exception as error:
            return self._halt_repeat(session, f"Extraction failed: {error}")

        session.state = TURN1_EXTRACTED
        session.evaluation = evaluate_visit(
            session.record, previous_visits=session.previous_visits
        )
        if session.evaluation.emergency_bypass:
            session.state = EMERGENCY_HALT
            session.halt_reason = "Emergency referral rule triggered."
            return session
        if session.evaluation.voice_followup_gaps:
            return self._ask_followup(session)
        return self._start_readback(session)

    def process_followup(self, session_id: str, audio_bytes: bytes) -> SessionState:
        session = self.get_session(session_id)
        if session.state != FOLLOWUP_ACTIVE:
            raise ValueError("Session is not waiting for a follow-up answer.")
        previous_question = session.original_question or session.prompt_text
        try:
            transcript = self._transcribe(session, audio_bytes, previous_question)
        except Exception as error:
            return self._halt_repeat(session, f"Follow-up transcription failed: {error}")
        if not transcript.split():
            return self._halt_repeat(session, "Follow-up transcript was empty.")
        try:
            turn2_record = extract_visit_record(
                transcript,
                language=session.language,
                evon_client=self._evon(),
            )
        except Exception as error:
            return self._halt_repeat(session, f"Follow-up extraction failed: {error}")

        session.record = merge_turn2_update(session.record, turn2_record)
        session.conflicts = [
            asdict(conflict) for conflict in session.record.conflicts
        ]
        session.followup_turn_count += 1
        session.evaluation = evaluate_visit(
            session.record, previous_visits=session.previous_visits
        )
        if session.evaluation.emergency_bypass:
            session.state = EMERGENCY_HALT
            session.halt_reason = "Emergency referral rule triggered during follow-up."
            session.current_gap_field = None
            return session
        if session.followup_turn_count < MAX_FOLLOWUP_TURNS and session.evaluation.voice_followup_gaps:
            return self._ask_followup(session)
        return self._start_readback(session)

    def request_clarification(
        self,
        session_id: str,
        reason: str = "Clarification requested.",
    ) -> SessionState:
        session = self.get_session(session_id)
        if session.state != FOLLOWUP_ACTIVE or not session.original_question:
            raise ValueError("Session is not waiting for a follow-up answer to clarify.")
        return self._ask_clarification(session, reason)

    def process_readback(self, session_id: str, audio_bytes: bytes) -> SessionState:
        session = self.get_session(session_id)
        if session.state != READBACK_ACTIVE:
            raise ValueError("Session is not waiting for read-back confirmation.")
        try:
            transcript = self._transcribe(session, audio_bytes, session.prompt_text)
            if not transcript.split():
                raise ValueError("Read-back transcript was empty.")
            correction = extract_numeric_correction(
                transcript,
                current_bp_sys=self._numeric_int(session.record.bp_systolic),
                current_bp_dia=self._numeric_int(session.record.bp_diastolic),
                current_weeks=self._numeric_int(session.record.gestational_weeks),
                language=session.language,
                evon_client=self._evon(),
            )
        except Exception as error:
            session.state = MANUAL_EDIT_REQUIRED
            session.halt_reason = f"Read-back could not be confirmed: {error}"
            session.audio_playback_b64 = None
            return session

        if correction.confirmed:
            if session.conflicts:
                session.state = MANUAL_EDIT_REQUIRED
                session.halt_reason = "Review and confirm extracted field conflicts manually."
            else:
                session.state = FINAL_LOCKED
                session.halt_reason = None
            return session

        corrections = {
            field_name: getattr(correction, field_name)
            for field_name in ("bp_systolic", "bp_diastolic", "gestational_weeks")
            if getattr(correction, field_name) is not None
        }
        if corrections and session.readback_attempts < MAX_READBACK_ATTEMPTS:
            for field_name, value in corrections.items():
                setattr(session.record, field_name, value)
                if correction.evidence:
                    session.record.evidence_spans[field_name] = correction.evidence
            session.readback_attempts += 1
            session.evaluation = evaluate_visit(
                session.record, previous_visits=session.previous_visits
            )
            session.state = MANUAL_EDIT_REQUIRED
            session.halt_reason = "Numeric correction applied; verify and finalize using the edit card."
            return session

        session.state = MANUAL_EDIT_REQUIRED
        session.halt_reason = "Read-back was unclear or the single voice correction was already used."
        return session

    def manual_confirm(
        self,
        session_id: str,
        updates: dict[str, Any],
    ) -> SessionState:
        session = self.get_session(session_id)
        invalid_fields = set(updates) - _RECORD_FIELDS | (_NON_EDITABLE_FIELDS & set(updates))
        if invalid_fields:
            raise ValueError(f"Unsupported manual-edit fields: {sorted(invalid_fields)}")
        try:
            current = {
                item.name: getattr(session.record, item.name)
                for item in fields(ANCVisitRecord)
            }
            current.update(updates)
            current["conflicts"] = []
            session.record = _RECORD_ADAPTER.validate_python(current)
        except ValidationError as error:
            raise ValueError(f"Invalid manual-edit values: {error}") from error

        session.conflicts.clear()
        session.evaluation = evaluate_visit(
            session.record, previous_visits=session.previous_visits
        )
        session.state = FINAL_LOCKED
        session.halt_reason = None
        session.current_gap_field = None
        session.audio_playback_b64 = None
        return session

    def link_patient(
        self,
        session_id: str,
        patient_record: Any,
        previous_visits: list[Any],
    ) -> SessionState:
        session = self.get_session(session_id)
        session.patient_id = patient_record.id
        session.linked_patient = {
            "id": patient_record.id,
            "rch_id": patient_record.rch_id,
            "name": patient_record.name,
            "age": patient_record.age,
            "village": patient_record.village,
            "edd": patient_record.edd,
        }
        session.previous_visits = [
            {
                "visit_number": v.visit_number,
                "gestational_weeks": v.gestational_weeks,
                "bp_systolic": v.bp_systolic,
                "bp_diastolic": v.bp_diastolic,
                "weight_kg": v.weight_kg,
                "hemoglobin": v.hemoglobin,
                "referral_flag": v.referral_flag,
            }
            for v in previous_visits
        ]
        session.evaluation = evaluate_visit(
            session.record, previous_visits=session.previous_visits
        )
        return session
        session.halt_reason = None
        session.current_gap_field = None
        session.audio_playback_b64 = None
        return session

    @staticmethod
    def _numeric_int(value: int | float | None) -> int | None:
        return int(value) if value is not None else None
