import pytest

from app.db import init_db
from app.main import (
    app,
    get_supervisor_summary,
    get_supervisor_patients,
    get_supervisor_patient_detail,
    verify_visit_supervisor,
    update_visit_referral_status,
    get_visit_audit,
    VerifyVisitRequest,
    UpdateReferralStatusRequest,
)


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path):
    test_db = init_db(tmp_path / "test.db", seed=True)
    app.state.db = test_db
    return test_db


def test_supervisor_summary_metrics():
    data = get_supervisor_summary()
    assert "total_mothers" in data
    assert data["total_mothers"] >= 4
    assert "high_risk_mothers" in data
    assert "villages" in data
    assert len(data["villages"]) >= 2


def test_supervisor_patients_list():
    data = get_supervisor_patients()
    assert data["count"] >= 4
    # First patient should be high risk due to sort
    first_patient = data["patients"][0]
    assert first_patient["risk_tier"] in {"HIGH", "MODERATE"}


def test_supervisor_patient_detail():
    data = get_supervisor_patient_detail("109283748291")
    assert data["patient"]["name"] == "Sunita Devi"
    assert len(data["visits"]) >= 2
    assert "risk_assessment" in data
    assert data["risk_assessment"]["score"] > 0
    assert len(data["risk_assessment"]["trajectories"]) >= 2


def test_visit_verification_and_referral_status_update():
    detail = get_supervisor_patient_detail("109283748291")
    visit_id = detail["visits"][1]["id"]

    # Verify visit
    verify_res = verify_visit_supervisor(
        visit_id,
        VerifyVisitRequest(supervisor_notes="Reviewed by Dr. Sharma MO Rampur PHC. BP surge confirmed."),
    )
    assert verify_res["verified"] is True

    # Update referral status
    ref_res = update_visit_referral_status(
        visit_id,
        UpdateReferralStatusRequest(referral_status="ATTENDED_PHC", supervisor_notes="Admitted to Day Care for lab workup"),
    )
    assert ref_res["referral_status"] == "ATTENDED_PHC"

    # Audit endpoint returns updated status and transcripts
    audit = get_visit_audit(visit_id)
    assert audit["verified_by_supervisor"] is True
    assert audit["visit"]["referral_status"] == "ATTENDED_PHC"
    assert "सुनीता देवी" in (audit["transcript_turn1"] or "")
