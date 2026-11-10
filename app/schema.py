"""Typed visit data and safe merging for follow-up extraction."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Literal

TriState = Literal["present", "denied", "not_mentioned"]
RecordValue = TriState | int | float | str | None


@dataclass(frozen=True)
class ANCFieldConflict:
    field: str
    turn1_value: RecordValue
    turn2_value: RecordValue
    turn2_evidence: str | None = None


@dataclass
class ANCVisitRecord:
    gestational_weeks: int | float | None = None
    bp_systolic: int | float | None = None
    bp_diastolic: int | float | None = None
    weight_kg: float | None = None
    hemoglobin: float | None = None
    swelling: TriState = "not_mentioned"
    severe_headache: TriState = "not_mentioned"
    blurred_vision: TriState = "not_mentioned"
    reduced_fetal_movement: TriState = "not_mentioned"
    vaginal_bleeding: TriState = "not_mentioned"
    convulsions: TriState = "not_mentioned"
    severe_abdominal_pain: TriState = "not_mentioned"
    fever: TriState = "not_mentioned"
    leaking_fluid: TriState = "not_mentioned"
    anemia_or_low_hb_mentioned: TriState = "not_mentioned"
    ifa_tablets_taken: TriState = "not_mentioned"
    calcium_tablets_taken: TriState = "not_mentioned"
    last_anc_visit: str | None = None
    evidence_spans: dict[str, str] = field(default_factory=dict)
    conflicts: list[ANCFieldConflict] = field(default_factory=list)


def _is_unset(value: RecordValue) -> bool:
    return value is None or value == "not_mentioned"


def merge_turn2_update(turn1: ANCVisitRecord, turn2: ANCVisitRecord) -> ANCVisitRecord:
    """Fill unset Turn 1 values and preserve conflicting values for read-back."""
    merged = ANCVisitRecord(
        **{
            item.name: getattr(turn1, item.name)
            for item in fields(ANCVisitRecord)
            if item.name not in {"evidence_spans", "conflicts"}
        },
        evidence_spans=dict(turn1.evidence_spans),
        conflicts=list(turn1.conflicts),
    )

    for item in fields(ANCVisitRecord):
        field_name = item.name
        if field_name in {"evidence_spans", "conflicts"}:
            continue

        original_value = getattr(turn1, field_name)
        followup_value = getattr(turn2, field_name)
        if _is_unset(original_value):
            if not _is_unset(followup_value):
                setattr(merged, field_name, followup_value)
                if field_name in turn2.evidence_spans:
                    merged.evidence_spans[field_name] = turn2.evidence_spans[field_name]
        elif not _is_unset(followup_value) and followup_value != original_value:
            merged.conflicts.append(
                ANCFieldConflict(
                    field=field_name,
                    turn1_value=original_value,
                    turn2_value=followup_value,
                    turn2_evidence=turn2.evidence_spans.get(field_name),
                )
            )

    return merged
