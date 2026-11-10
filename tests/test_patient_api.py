"""Tests for patient management and referral slip API endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    test_db = init_db(tmp_path / "test_api.db", seed=True)
    app.state.db = test_db
    return TestClient(app)


def test_list_patients_and_search(client: TestClient) -> None:
    resp = client.get("/api/patients")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 3
    assert any(p["rch_id"] == "109283748291" for p in data)

    # Search query
    search = client.get("/api/patients?query=Sunita")
    assert search.status_code == 200
    assert len(search.json()) == 1
    assert search.json()[0]["name"] == "Sunita Devi"


def test_create_patient(client: TestClient) -> None:
    resp = client.post(
        "/api/patients",
        json={
            "rch_id": "987654321098",
            "name": "Kavita Verma",
            "age": 25,
            "village": "Belagavi",
            "edd": "2026-12-30",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["rch_id"] == "987654321098"
    assert data["name"] == "Kavita Verma"


def test_get_patient_history(client: TestClient) -> None:
    resp = client.get("/api/patients/109283748291/history")
    assert resp.status_code == 200
    data = resp.json()
    assert data["patient"]["rch_id"] == "109283748291"
    assert len(data["visits"]) >= 1
    assert data["visits"][0]["visit_number"] == 1


def test_link_patient_and_save_visit(client: TestClient) -> None:
    # 1. Start session
    start = client.post("/api/session/start", json={"language": "hi-IN"}).json()
    session_id = start["session_id"]

    # 2. Link patient Sunita Devi (who has baseline BP 110/70 at Visit 1)
    link = client.post(
        f"/api/session/{session_id}/link-patient",
        json={"rch_id": "109283748291"},
    )
    assert link.status_code == 200
    data = link.json()
    assert data["linked_patient"]["rch_id"] == "109283748291"

    # 3. Simulate manual confirm with BP surge 142/92 (triggers RULE-HRP-01 and RULE-LONG-01)
    confirm = client.post(
        f"/api/session/{session_id}/manual-edit",
        json={
            "gestational_weeks": 24,
            "bp_systolic": 142,
            "bp_diastolic": 92,
            "swelling": "present",
            "severe_headache": "present",
        },
    )
    assert confirm.status_code == 200
    eval_res = confirm.json()["evaluation"]
    assert "RULE-LONG-01" in eval_res["rule_ids"]
    assert eval_res["flag"] == "CLINICIAN_REFERRAL"

    # 4. Save visit to DB
    save = client.post(f"/api/session/{session_id}/save-to-db")
    assert save.status_code == 200
    saved_visit = save.json()["saved_visit"]
    assert saved_visit["visit_number"] == 2
    assert saved_visit["referral_flag"] == "CLINICIAN_REFERRAL"

    # 5. Check referral slip
    slip = client.get(f"/api/session/{session_id}/referral-slip")
    assert slip.status_code == 200
    slip_data = slip.json()
    assert slip_data["patient"]["name"] == "Sunita Devi"
    assert slip_data["referral_flag"] == "CLINICIAN_REFERRAL"
    assert "qr_code_data" in slip_data
