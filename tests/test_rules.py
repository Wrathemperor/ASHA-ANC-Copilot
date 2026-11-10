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


def test_longitudinal_bp_surge_triggers_referral() -> None:
    current = ANCVisitRecord(
        gestational_weeks=28,
        bp_systolic=132,
        bp_diastolic=82,
        vaginal_bleeding="denied",
        convulsions="denied",
        severe_headache="denied",
        blurred_vision="denied",
        swelling="denied",
        reduced_fetal_movement="denied",
        severe_abdominal_pain="denied",
    )
    previous_visits = [
        {
            "visit_number": 1,
            "gestational_weeks": 12,
            "bp_systolic": 100,
            "bp_diastolic": 65,
            "weight_kg": 46.0,
            "hemoglobin": 11.5,
        }
    ]
    # Current BP 132/82 is below the 140/90 threshold, but delta systolic is +32 (>= 30).
    result = evaluate_visit(current, previous_visits=previous_visits)
    assert "RULE-LONG-01" in result.rule_ids
    assert result.flag == CLINICIAN_REFERRAL


def test_longitudinal_excessive_weight_gain() -> None:
    current = ANCVisitRecord(
        gestational_weeks=24,
        bp_systolic=115,
        bp_diastolic=75,
        weight_kg=53.0,
        vaginal_bleeding="denied",
        convulsions="denied",
        severe_headache="denied",
        blurred_vision="denied",
        swelling="denied",
        reduced_fetal_movement="denied",
        severe_abdominal_pain="denied",
    )
    previous_visits = [
        {
            "visit_number": 1,
            "gestational_weeks": 21,
            "bp_systolic": 110,
            "bp_diastolic": 70,
            "weight_kg": 50.0,
            "hemoglobin": 11.0,
        }
    ]
    result = evaluate_visit(current, previous_visits=previous_visits)
    assert "RULE-LONG-02" in result.rule_ids
    assert result.flag == CLINICIAN_REFERRAL


def test_longitudinal_severe_hemoglobin_drop() -> None:
    current = ANCVisitRecord(
        gestational_weeks=32,
        bp_systolic=110,
        bp_diastolic=70,
        hemoglobin=8.5,
        vaginal_bleeding="denied",
        convulsions="denied",
        severe_headache="denied",
        blurred_vision="denied",
        swelling="denied",
        reduced_fetal_movement="denied",
        severe_abdominal_pain="denied",
    )
    previous_visits = [
        {
            "visit_number": 1,
            "gestational_weeks": 20,
            "bp_systolic": 110,
            "bp_diastolic": 70,
            "weight_kg": 49.0,
            "hemoglobin": 11.0,
        }
    ]
    result = evaluate_visit(current, previous_visits=previous_visits)
    assert "RULE-LONG-03" in result.rule_ids
    assert result.flag == CLINICIAN_REFERRAL

