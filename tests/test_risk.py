from app.risk import compute_risk_score, calculate_compliance, determine_anc_stage
from app.schema import ANCVisitRecord


def test_low_risk_healthy_visit():
    record = ANCVisitRecord(
        gestational_weeks=12,
        bp_systolic=110,
        bp_diastolic=70,
        weight_kg=50.0,
        hemoglobin=12.0,
    )
    assessment = compute_risk_score(record)
    assert assessment.score < 30
    assert assessment.tier == "LOW"
    assert assessment.color == "#10b981"
    assert len(assessment.trajectories) == 1


def test_high_risk_emergency_convulsions():
    record = ANCVisitRecord(
        gestational_weeks=28,
        bp_systolic=150,
        bp_diastolic=100,
        convulsions="present",
        evidence_spans={"convulsions": "had a seizure yesterday"},
    )
    assessment = compute_risk_score(record)
    assert assessment.score >= 60
    assert assessment.tier == "HIGH"
    assert any(f.name == "Convulsions / Eclampsia Alert" for f in assessment.factors)


def test_longitudinal_trajectory_surge_and_hb_drop():
    baseline_visit = {
        "visit_number": 1,
        "gestational_weeks": 12,
        "bp_systolic": 110,
        "bp_diastolic": 70,
        "weight_kg": 48.0,
        "hemoglobin": 11.5,
        "created_at": "2026-08-01T10:00:00Z",
    }
    current_record = ANCVisitRecord(
        gestational_weeks=28,
        bp_systolic=142,  # +32 surge over baseline 110 -> triggers surge factor
        bp_diastolic=88,
        weight_kg=54.0,   # gained 6kg in 16 wks
        hemoglobin=9.2,   # -2.3 drop from 11.5 -> rapid drop factor + moderate anemia
    )
    assessment = compute_risk_score(
        current_record,
        previous_visits=[baseline_visit],
        patient_age=24,
    )
    assert assessment.score >= 30
    factor_names = [f.name for f in assessment.factors]
    assert "Systolic Pressure Surge" in factor_names
    assert "Rapid Hemoglobin Drop" in factor_names
    assert len(assessment.trajectories) == 2


def test_compliance_and_anc_stage():
    assert "ANC 1" in determine_anc_stage(10)
    assert "ANC 2" in determine_anc_stage(20)
    assert "ANC 3" in determine_anc_stage(30)
    assert "ANC 4" in determine_anc_stage(38)

    # Test overdue detection
    past = [{
        "visit_number": 1,
        "gestational_weeks": 14,
        "created_at": "2026-06-01T10:00:00Z",
    }]
    compliance = calculate_compliance(32, previous_visits=past)
    assert compliance.is_overdue is True
