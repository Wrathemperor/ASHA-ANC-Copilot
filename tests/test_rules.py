import pytest

from app.rules import (
    CLINICIAN_REFERRAL,
    INCOMPLETE_NEEDS_VERIFICATION,
    OFFICIAL_CITATIONS,
    URGENT_REFERRAL,
    evaluate_visit,
)
from app.schema import ANCVisitRecord


def test_raised_bp_and_swelling_promote_headache_and_vision_gaps() -> None:
    result = evaluate_visit(
        ANCVisitRecord(
            gestational_weeks=20,
            bp_systolic=145,
            bp_diastolic=95,
            swelling="present",
            severe_headache="not_mentioned",
            blurred_vision="not_mentioned",
            reduced_fetal_movement="not_mentioned",
        )
    )

    assert result.voice_followup_gaps == ["severe_headache", "blurred_vision"]
    assert "reduced_fetal_movement" in result.incomplete_fields
    assert result.flag == CLINICIAN_REFERRAL
    assert "RULE-HRP-01" in result.rule_ids
    assert "RULE-HRP-03" in result.rule_ids
    assert result.citations == list(OFFICIAL_CITATIONS)


@pytest.mark.parametrize(
    ("field_name", "expected_rule"),
    (
        ("convulsions", "RULE-EMG-01"),
        ("vaginal_bleeding", "RULE-EMG-02"),
        ("severe_headache", "RULE-EMG-03"),
        ("severe_abdominal_pain", "RULE-EMG-04"),
    ),
)
def test_emergency_bypass_returns_urgent_flag_and_skips_all_followups(
    field_name: str,
    expected_rule: str,
) -> None:
    record_values = {field_name: "present"}
    if field_name == "severe_headache":
        record_values["blurred_vision"] = "present"
    result = evaluate_visit(
        ANCVisitRecord(**record_values)
    )

    assert result.emergency_bypass is True
    assert result.flag == URGENT_REFERRAL
    assert result.top_gaps == []
    assert result.voice_followup_gaps == []
    assert result.incomplete_fields == []
    assert result.rule_ids == [expected_rule]
    assert result.citations == list(OFFICIAL_CITATIONS)


def test_stage_gate_does_not_require_movement_at_14_weeks() -> None:
    result = evaluate_visit(
        ANCVisitRecord(
            gestational_weeks=14,
            vaginal_bleeding="denied",
            convulsions="denied",
            severe_headache="denied",
            blurred_vision="denied",
            swelling="denied",
            severe_abdominal_pain="denied",
        )
    )

    assert "STAGE-GATE-01" not in result.rule_ids
    assert "reduced_fetal_movement" not in result.top_gaps


def test_stage_gate_requires_movement_at_20_weeks() -> None:
    result = evaluate_visit(
        ANCVisitRecord(
            gestational_weeks=20,
            vaginal_bleeding="denied",
            convulsions="denied",
            severe_headache="denied",
            blurred_vision="denied",
            swelling="denied",
            severe_abdominal_pain="denied",
        )
    )

    assert "STAGE-GATE-01" in result.rule_ids
    assert result.top_gaps == ["reduced_fetal_movement"]
    assert result.voice_followup_gaps == ["reduced_fetal_movement"]
    assert result.flag == INCOMPLETE_NEEDS_VERIFICATION


def test_unknown_weeks_asks_weeks_first_and_keeps_movement_required() -> None:
    result = evaluate_visit(
        ANCVisitRecord(
            vaginal_bleeding="denied",
            convulsions="denied",
            severe_headache="denied",
            blurred_vision="denied",
            swelling="denied",
            severe_abdominal_pain="denied",
        )
    )

    assert "STAGE-GATE-01" in result.rule_ids
    assert result.top_gaps == ["gestational_weeks", "reduced_fetal_movement"]
    assert result.voice_followup_gaps == ["gestational_weeks", "reduced_fetal_movement"]
    assert result.incomplete_fields == []


def test_silence_remains_incomplete_not_a_denial() -> None:
    result = evaluate_visit(ANCVisitRecord(gestational_weeks=14))

    assert result.flag == INCOMPLETE_NEEDS_VERIFICATION
    assert result.voice_followup_gaps == ["vaginal_bleeding", "convulsions"]
    assert result.incomplete_fields == [
        "severe_headache",
        "blurred_vision",
        "swelling",
        "severe_abdominal_pain",
    ]
