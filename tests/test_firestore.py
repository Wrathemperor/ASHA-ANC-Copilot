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

    mock_google = MagicMock()
    monkeypatch.setitem(sys.modules, "google", mock_google)
    monkeypatch.setitem(sys.modules, "google.cloud", mock_google_cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.firestore", mock_firestore_module)
    monkeypatch.setitem(sys.modules, "google.oauth2", MagicMock())
    monkeypatch.setitem(sys.modules, "google.oauth2.service_account", MagicMock())

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

    # Test list_patients with and without query filter
    mock_p1 = MagicMock()
    mock_p1.to_dict.return_value = {
        "id": "p1", "rch_id": "1001", "name": "Sunita Devi", "age": 24, "village": "Rampur", "edd": "2026-12-01", "created_at": "2026-11-01"
    }
    mock_p2 = MagicMock()
    mock_p2.to_dict.return_value = {
        "id": "p2", "rch_id": "1002", "name": "Pooja Sharma", "age": 22, "village": "Sitapur", "edd": "2026-12-15", "created_at": "2026-11-01"
    }
    mock_client.collection.return_value.order_by.return_value.stream.return_value = [mock_p1, mock_p2]

    # No query
    all_pts = db.list_patients()
    assert len(all_pts) == 2

    # Query matching Sunita
    filtered_sunita = db.list_patients("sunita")
    assert len(filtered_sunita) == 1
    assert filtered_sunita[0].name == "Sunita Devi"

    # Query matching village Sitapur
    filtered_village = db.list_patients(query="sitapur")
    assert len(filtered_village) == 1
    assert filtered_village[0].name == "Pooja Sharma"

    # Query non-matching
    filtered_none = db.list_patients(query="nomatch")
    assert len(filtered_none) == 0
