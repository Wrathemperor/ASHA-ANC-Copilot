from __future__ import annotations

import json
from typing import Any

import pytest

from app.extraction import (
    ExtractionValidationError,
    NumericCorrectionResult,
    extract_numeric_correction,
    extract_visit_record,
)
from app.schema import ANCVisitRecord


class MockEvonClient:
    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str) -> Any:
        self.calls.append((system, user))
        return self.responses.pop(0)


@pytest.fixture
def extraction_result() -> dict[str, Any]:
    return {
        "gestational_weeks": None,
        "bp_systolic": None,
        "bp_diastolic": None,
        "swelling": "not_mentioned",
        "severe_headache": "not_mentioned",
        "blurred_vision": "not_mentioned",
        "reduced_fetal_movement": "not_mentioned",
        "vaginal_bleeding": "not_mentioned",
        "convulsions": "not_mentioned",
        "severe_abdominal_pain": "not_mentioned",
        "fever": "not_mentioned",
        "leaking_fluid": "not_mentioned",
        "anemia_or_low_hb_mentioned": "not_mentioned",
        "ifa_tablets_taken": "not_mentioned",
        "calcium_tablets_taken": "not_mentioned",
        "last_anc_visit": None,
        "evidence_spans": {},
        "conflicts": [],
    }


def test_full_visit_preserves_explicit_denials_and_numeric_evidence(
    extraction_result: dict[str, Any],
) -> None:
    extraction_result.update(
        gestational_weeks=28,
        bp_systolic=120,
        bp_diastolic=80,
        swelling="denied",
        severe_headache="denied",
        blurred_vision="denied",
        reduced_fetal_movement="denied",
        vaginal_bleeding="denied",
        convulsions="denied",
        severe_abdominal_pain="denied",
        fever="denied",
        leaking_fluid="denied",
        anemia_or_low_hb_mentioned="denied",
        ifa_tablets_taken="present",
        calcium_tablets_taken="present",
        last_anc_visit="last month",
        evidence_spans={"gestational_weeks": "28 weeks", "bp_systolic": "120 by 80"},
    )
    client = MockEvonClient(extraction_result)

    record = extract_visit_record(
        "28 weeks, BP 120 by 80; no swelling, no headache, no blurred vision, "
        "movement normal, no bleeding, no fits, no severe stomach pain, no fever, "
        "no leaking, no anemia; taking IFA and calcium; ANC last month.",
        evon_client=client,
    )

    assert record.gestational_weeks == 28
    assert record.vaginal_bleeding == "denied"
    assert record.ifa_tablets_taken == "present"
    assert record.evidence_spans["bp_systolic"] == "120 by 80"


def test_preeclampsia_gap_scenario_keeps_headache_and_vision_unknown(
    extraction_result: dict[str, Any],
) -> None:
    extraction_result.update(
        gestational_weeks=24,
        bp_systolic=145,
        bp_diastolic=95,
        swelling="present",
    )
    client = MockEvonClient(extraction_result)

    record = extract_visit_record(
        "24 weeks, BP 145 over 95, swelling present.", evon_client=client
    )

    assert record.swelling == "present"
    assert record.severe_headache == "not_mentioned"
    assert record.blurred_vision == "not_mentioned"
    assert record.reduced_fetal_movement == "not_mentioned"


def test_negation_trap_marks_only_negated_headache_and_vision_denied(
    extraction_result: dict[str, Any],
) -> None:
    extraction_result.update(severe_headache="denied", blurred_vision="denied")
    client = MockEvonClient(extraction_result)

    record = extract_visit_record(
        "sir dard ya dhundhla dikhne ki koi shikayat nahi hai",
        language="hi-IN",
        evon_client=client,
    )

    assert record.severe_headache == "denied"
    assert record.blurred_vision == "denied"
    assert record.swelling == "not_mentioned"
    assert record.vaginal_bleeding == "not_mentioned"


def test_normal_baby_movement_is_explicitly_mapped_to_denied(
    extraction_result: dict[str, Any],
) -> None:
    extraction_result["reduced_fetal_movement"] = "denied"
    extraction_result["evidence_spans"] = {
        "reduced_fetal_movement": "halchal theek hai"
    }
    client = MockEvonClient(extraction_result)

    record = extract_visit_record(
        "halchal theek hai", language="hi-IN", evon_client=client
    )

    assert record.reduced_fetal_movement == "denied"
    assert record.evidence_spans["reduced_fetal_movement"] == "halchal theek hai"


def test_self_corrected_weeks_and_blood_pressure_use_corrected_values(
    extraction_result: dict[str, Any],
) -> None:
    extraction_result.update(
        gestational_weeks=28,
        bp_systolic=140,
        bp_diastolic=90,
        evidence_spans={
            "gestational_weeks": "28 weeks",
            "bp_systolic": "140 by 90",
            "bp_diastolic": "140 by 90",
        },
    )
    client = MockEvonClient(extraction_result)

    record = extract_visit_record(
        "26 weeks... nahi sorry 28 weeks; BP 150 by 100, sorry 140 by 90.",
        evon_client=client,
    )

    assert record.gestational_weeks == 28
    assert record.bp_systolic == 140
    assert record.bp_diastolic == 90


def test_code_mixed_hindi_english_extraction_uses_language_hint(
    extraction_result: dict[str, Any],
) -> None:
    extraction_result.update(gestational_weeks=30, vaginal_bleeding="denied")
    client = MockEvonClient(extraction_result)

    record = extract_visit_record(
        "30 weeks pregnant hoon, bleeding nahi hai.",
        language="hi-IN",
        evon_client=client,
    )

    assert record.gestational_weeks == 30
    assert record.vaginal_bleeding == "denied"
    assert "hi-IN" in client.calls[0][0]


def test_code_mixed_marathi_extraction_uses_language_hint(
    extraction_result: dict[str, Any],
) -> None:
    extraction_result.update(swelling="present")
    client = MockEvonClient(extraction_result)

    record = extract_visit_record(
        "Sujan aahe, BP check kela.", language="mr-IN", evon_client=client
    )

    assert record.swelling == "present"
    assert "mr-IN" in client.calls[0][0]


def test_think_tags_are_stripped_before_json_decode(
    extraction_result: dict[str, Any],
) -> None:
    client = MockEvonClient(
        f"<think>internal reasoning</think>{json.dumps(extraction_result)}"
    )

    record = extract_visit_record("No symptoms were discussed.", evon_client=client)

    assert isinstance(record, ANCVisitRecord)


def test_invalid_json_retries_once_with_targeted_repair(
    extraction_result: dict[str, Any],
) -> None:
    client = MockEvonClient("{not json", extraction_result)

    record = extract_visit_record("28 weeks.", evon_client=client)

    assert isinstance(record, ANCVisitRecord)
    assert len(client.calls) == 2
    assert "REPAIR ATTEMPT" in client.calls[1][0]


def test_invalid_schema_retries_once_and_fails_closed(
    extraction_result: dict[str, Any],
) -> None:
    invalid = dict(extraction_result, vaginal_bleeding="maybe")
    client = MockEvonClient(invalid, invalid)

    with pytest.raises(ExtractionValidationError):
        extract_visit_record("bleeding", evon_client=client)

    assert len(client.calls) == 2


def test_unrecoverable_json_raises_after_exactly_two_attempts() -> None:
    client = MockEvonClient("invalid", "{still invalid")

    with pytest.raises(ExtractionValidationError):
        extract_visit_record("some visit transcript", evon_client=client)

    assert len(client.calls) == 2


def test_empty_transcript_halts_without_calling_evon() -> None:
    client = MockEvonClient()

    with pytest.raises(ExtractionValidationError, match="empty"):
        extract_visit_record("  ", evon_client=client)

    assert client.calls == []


@pytest.mark.parametrize(
    ("transcript", "language"),
    (
        ("haan sahi hai", "hi-IN"),
        ("yes correct", "en-IN"),
        ("बरोबर आहे", "mr-IN"),
        ("అవును", "te-IN"),
    ),
)
def test_read_back_affirmative_confirmation(
    transcript: str,
    language: str,
) -> None:
    client = MockEvonClient({"confirmed": True, "evidence": transcript})

    result = extract_numeric_correction(
        transcript,
        current_bp_sys=120,
        current_bp_dia=80,
        current_weeks=28,
        language=language,
        evon_client=client,
    )

    assert result == NumericCorrectionResult(confirmed=True, evidence=transcript)
    assert language in client.calls[0][0]


def test_read_back_numeric_correction_returns_only_corrected_values() -> None:
    client = MockEvonClient(
        {
            "confirmed": False,
            "bp_systolic": 130,
            "bp_diastolic": 80,
            "evidence": "BP 130 over 80 hai",
        }
    )

    result = extract_numeric_correction(
        "nahi BP 130 over 80 hai",
        current_bp_sys=145,
        current_bp_dia=95,
        current_weeks=28,
        evon_client=client,
    )

    assert result.bp_systolic == 130
    assert result.bp_diastolic == 80
    assert result.gestational_weeks is None
    assert result.confirmed is False


def test_read_back_week_correction_prompt_disallows_carrying_old_values() -> None:
    client = MockEvonClient(
        {
            "confirmed": False,
            "gestational_weeks": 32,
            "evidence": "weeks 30 nahi 32 hai",
        }
    )

    result = extract_numeric_correction(
        "weeks 30 nahi 32 hai",
        current_bp_sys=120,
        current_bp_dia=80,
        current_weeks=30,
        evon_client=client,
    )

    assert result.gestational_weeks == 32
    assert result.bp_systolic is None
    assert "Do not carry unchanged displayed values" in client.calls[0][0]
