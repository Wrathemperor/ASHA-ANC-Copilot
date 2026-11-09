"""Pure, deterministic ANC rule evaluation."""

from __future__ import annotations

from dataclasses import dataclass

from app.schema import ANCVisitRecord

URGENT_REFERRAL = "URGENT_REFERRAL"
CLINICIAN_REFERRAL = "CLINICIAN_REFERRAL"
INCOMPLETE_NEEDS_VERIFICATION = "INCOMPLETE_NEEDS_VERIFICATION"

GAP_PRIORITY = (
    "vaginal_bleeding",
    "convulsions",
    "severe_headache",
    "blurred_vision",
    "swelling",
    "reduced_fetal_movement",
    "severe_abdominal_pain",
)

OFFICIAL_CITATIONS = (
    "https://pmsma.mohfw.gov.in/?lang=en",
    "https://pmsma.mohfw.gov.in/i-am/government-organization/monitoring-and-supervision-plan/",
    "https://www.nhm.gov.in/images/pdf/programmes/maternal-health/guidelines/my_safe_motherhood_booklet_english.pdf",
    "https://pmsma.mohfw.gov.in/wp-content/uploads/2016/10/High-Risk-Conditions-in-preg-modified-Final.pdf",
    "https://nhm.gov.in/pdf/2024/Revised_CEmONC_Curriculum-2024-Part-1.pdf",
)


@dataclass(frozen=True)
class EvaluationResult:
    emergency_bypass: bool
    flag: str | None
    top_gaps: list[str]
    voice_followup_gaps: list[str]
    incomplete_fields: list[str]
    rule_ids: list[str]
    citations: list[str]


def _is_present(record: ANCVisitRecord, field_name: str) -> bool:
    return getattr(record, field_name) == "present"


def _is_missing(record: ANCVisitRecord, field_name: str) -> bool:
    return getattr(record, field_name) == "not_mentioned"


def _has_emergency(record: ANCVisitRecord) -> tuple[str, ...]:
    matches: list[str] = []
    if _is_present(record, "convulsions"):
        matches.append("RULE-EMG-01")
    if _is_present(record, "vaginal_bleeding"):
        matches.append("RULE-EMG-02")
    if _is_present(record, "severe_headache") and _is_present(record, "blurred_vision"):
        matches.append("RULE-EMG-03")
    if _is_present(record, "severe_abdominal_pain"):
        matches.append("RULE-EMG-04")
    return tuple(matches)


def _high_risk_rule_ids(record: ANCVisitRecord) -> tuple[str, ...]:
    matches: list[str] = []
    if (
        record.bp_systolic is not None
        and record.bp_diastolic is not None
        and record.bp_systolic >= 140
        and record.bp_diastolic >= 90
    ):
        matches.append("RULE-HRP-01")
    if _is_present(record, "severe_headache") or _is_present(record, "blurred_vision"):
        matches.append("RULE-HRP-02")
    if _is_present(record, "swelling"):
        matches.append("RULE-HRP-03")
    if _is_present(record, "reduced_fetal_movement"):
        matches.append("RULE-HRP-04")
    if any(
        _is_present(record, field_name)
        for field_name in ("anemia_or_low_hb_mentioned", "fever", "leaking_fluid")
    ):
        matches.append("RULE-HRP-05")
    return tuple(matches)


def evaluate_visit(record: ANCVisitRecord) -> EvaluationResult:
    """Evaluate official referral rules and ordered missing-information gaps."""
    emergency_rules = _has_emergency(record)
    if emergency_rules:
        return EvaluationResult(
            emergency_bypass=True,
            flag=URGENT_REFERRAL,
            top_gaps=[],
            voice_followup_gaps=[],
            incomplete_fields=[],
            rule_ids=list(emergency_rules),
            citations=list(OFFICIAL_CITATIONS),
        )

    rule_ids = list(_high_risk_rule_ids(record))
    stage_gate_active = record.gestational_weeks is None or (
        record.gestational_weeks >= 20 and _is_missing(record, "reduced_fetal_movement")
    )
    if stage_gate_active:
        rule_ids.append("STAGE-GATE-01")

    missing_fields = [
        field_name
        for field_name in GAP_PRIORITY
        if _is_missing(record, field_name)
        and (field_name != "reduced_fetal_movement" or stage_gate_active)
    ]

    pressure_at_threshold = (
        record.bp_systolic is not None
        and record.bp_diastolic is not None
        and record.bp_systolic >= 140
        and record.bp_diastolic >= 90
    )
    promote_neurological_gaps = pressure_at_threshold or _is_present(record, "swelling")
    if promote_neurological_gaps:
        promoted = [
            field_name
            for field_name in ("severe_headache", "blurred_vision")
            if field_name in missing_fields
        ]
        missing_fields = promoted + [
            field_name for field_name in missing_fields if field_name not in promoted
        ]

    if record.gestational_weeks is None:
        missing_fields.insert(0, "gestational_weeks")

    top_gaps = missing_fields
    voice_followup_gaps = top_gaps[:2]
    incomplete_fields = top_gaps[2:]
    has_referral = any(rule_id.startswith("RULE-HRP-") for rule_id in rule_ids)
    if has_referral:
        flag = CLINICIAN_REFERRAL
    elif top_gaps:
        flag = INCOMPLETE_NEEDS_VERIFICATION
    else:
        flag = None

    return EvaluationResult(
        emergency_bypass=False,
        flag=flag,
        top_gaps=top_gaps,
        voice_followup_gaps=voice_followup_gaps,
        incomplete_fields=incomplete_fields,
        rule_ids=rule_ids,
        citations=list(OFFICIAL_CITATIONS) if rule_ids else [],
    )
