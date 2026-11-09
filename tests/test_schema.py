from app.schema import ANCVisitRecord, merge_turn2_update


def test_clinical_fields_default_to_not_mentioned_not_denied() -> None:
    record = ANCVisitRecord()

    assert record.vaginal_bleeding == "not_mentioned"
    assert record.convulsions == "not_mentioned"
    assert record.severe_headache == "not_mentioned"
    assert record.blurred_vision == "not_mentioned"
    assert record.reduced_fetal_movement == "not_mentioned"
    assert record.swelling == "not_mentioned"
    assert record.severe_abdominal_pain == "not_mentioned"
    assert record.fever == "not_mentioned"
    assert record.leaking_fluid == "not_mentioned"
    assert record.anemia_or_low_hb_mentioned == "not_mentioned"
    assert record.ifa_tablets_taken == "not_mentioned"
    assert record.calcium_tablets_taken == "not_mentioned"
    assert record.gestational_weeks is None
    assert record.bp_systolic is None
    assert record.bp_diastolic is None
    assert record.evidence_spans == {}


def test_turn2_fills_unset_fields_and_keeps_turn1_locked_values() -> None:
    turn1 = ANCVisitRecord(
        severe_headache="denied",
        gestational_weeks=14,
        evidence_spans={"severe_headache": "no headache"},
    )
    turn2 = ANCVisitRecord(
        severe_headache="present",
        blurred_vision="present",
        bp_systolic=145,
        evidence_spans={
            "severe_headache": "head hurts",
            "blurred_vision": "seeing spots",
            "bp_systolic": "one forty-five",
        },
    )

    merged = merge_turn2_update(turn1, turn2)

    assert merged.severe_headache == "denied"
    assert merged.gestational_weeks == 14
    assert merged.blurred_vision == "present"
    assert merged.bp_systolic == 145
    assert merged.evidence_spans["severe_headache"] == "no headache"
    assert merged.evidence_spans["blurred_vision"] == "seeing spots"
    assert merged.conflicts[0].field == "severe_headache"
    assert merged.conflicts[0].turn1_value == "denied"
    assert merged.conflicts[0].turn2_value == "present"
    assert merged.conflicts[0].turn2_evidence == "head hurts"
    assert turn1.conflicts == []


def test_turn2_captures_unsolicited_danger_sign_without_overwriting_other_data() -> None:
    turn1 = ANCVisitRecord(vaginal_bleeding="denied")
    turn2 = ANCVisitRecord(
        vaginal_bleeding="present",
        convulsions="present",
        evidence_spans={"convulsions": "she shook uncontrollably"},
    )

    merged = merge_turn2_update(turn1, turn2)

    assert merged.vaginal_bleeding == "denied"
    assert merged.convulsions == "present"
    assert merged.evidence_spans["convulsions"] == "she shook uncontrollably"
    assert [conflict.field for conflict in merged.conflicts] == ["vaginal_bleeding"]
