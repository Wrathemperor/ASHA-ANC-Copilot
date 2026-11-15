from __future__ import annotations

from unittest.mock import MagicMock
from app.firestore_db import FirestoreDatabase, is_firestore_configured


def test_is_firestore_configured(monkeypatch):
    monkeypatch.delenv("FIRESTORE_PROJECT_ID", raising=False)
    monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    assert not is_firestore_configured()

    monkeypatch.setenv("FIRESTORE_PROJECT_ID", "test-project-123")
    assert is_firestore_configured()


def test_firestore_database_operations(monkeypatch):
    import sys
    mock_firestore_module = MagicMock()
    mock_client = MagicMock()
    mock_firestore_module.Client.return_value = mock_client

    mock_google_cloud = MagicMock()
    mock_google_cloud.firestore = mock_firestore_module

    sys.modules["google"] = MagicMock()
    sys.modules["google.cloud"] = mock_google_cloud
    sys.modules["google.cloud.firestore"] = mock_firestore_module
    sys.modules["google.oauth2"] = MagicMock()
    sys.modules["google.oauth2.service_account"] = MagicMock()

    db = FirestoreDatabase(project_id="test-anc-copilot")
    assert db.client == mock_client

    # Test patient creation
    mock_doc = MagicMock()
    mock_client.collection.return_value.document.return_value = mock_doc
    # mock get_patient_by_rch to return None
    mock_client.collection.return_value.where.return_value.limit.return_value.stream.return_value = []

    patient = db.create_patient(
        rch_id="109283748291",
        name="Sunita Devi",
        age=24,
        village="Rampur",
        edd="2026-11-15",
    )
    assert patient.rch_id == "109283748291"
    assert patient.name == "Sunita Devi"
    assert mock_doc.set.called

    # Test save visit
    visit = db.save_visit(
        patient_id=patient.id,
        session_id="test-session-1",
        visit_number=1,
        gestational_weeks=14,
        bp_systolic=120,
        bp_diastolic=80,
        weight_kg=52.0,
        hemoglobin=11.5,
        tri_state_json={"swelling": "denied"},
        referral_flag=None,
        rule_ids=[],
        risk_score=10,
        risk_tier="LOW",
    )
    assert visit.gestational_weeks == 14
    assert visit.bp_systolic == 120
    assert visit.bp_diastolic == 80
