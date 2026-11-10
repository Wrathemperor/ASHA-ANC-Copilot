"""Tests for SQLite database persistence layer."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.db import (
    Database,
    PatientRecord,
    VisitRecord,
    init_db,
)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    db_file = tmp_path / "test_anc.db"
    return init_db(db_file)


def test_init_db_creates_tables(db: Database) -> None:
    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
    assert "patients" in tables
    assert "visits" in tables


def test_create_and_get_patient(db: Database) -> None:
    patient = db.create_patient(
        rch_id="109283748291",
        name="Sunita Devi",
        age=24,
        village="Rampur",
        edd="2026-11-20",
    )
    assert patient.rch_id == "109283748291"
    assert patient.name == "Sunita Devi"

    fetched = db.get_patient_by_rch("109283748291")
    assert fetched is not None
    assert fetched.id == patient.id
    assert fetched.age == 24


def test_list_patients_and_search(db: Database) -> None:
    db.create_patient(rch_id="111122223333", name="Anita Kumar", age=22, village="Shivpur")
    db.create_patient(rch_id="444455556666", name="Pooja Sharma", age=26, village="Rampur")

    all_patients = db.list_patients()
    assert len(all_patients) == 2

    search_result = db.list_patients(query="Anita")
    assert len(search_result) == 1
    assert search_result[0].name == "Anita Kumar"

    search_rch = db.list_patients(query="4444")
    assert len(search_rch) == 1
    assert search_rch[0].name == "Pooja Sharma"


def test_save_and_retrieve_longitudinal_visits(db: Database) -> None:
    patient = db.create_patient(rch_id="999988887777", name="Radha Yadav", age=23)

    # Visit 1 at 12 weeks
    v1 = db.save_visit(
        patient_id=patient.id,
        session_id="sess-001",
        visit_number=1,
        gestational_weeks=12,
        bp_systolic=110,
        bp_diastolic=70,
        weight_kg=48.5,
        hemoglobin=11.2,
        tri_state_json={"swelling": "denied", "vaginal_bleeding": "denied"},
        referral_flag=None,
        rule_ids=[],
    )
    assert v1.id is not None
    assert v1.visit_number == 1

    # Visit 2 at 22 weeks
    v2 = db.save_visit(
        patient_id=patient.id,
        session_id="sess-002",
        visit_number=2,
        gestational_weeks=22,
        bp_systolic=142,
        bp_diastolic=92,
        weight_kg=52.0,
        hemoglobin=10.8,
        tri_state_json={"swelling": "present", "severe_headache": "present"},
        referral_flag="CLINICIAN_REFERRAL",
        rule_ids=["RULE-HRP-01", "RULE-HRP-02", "RULE-HRP-03"],
    )
    assert v2.visit_number == 2

    history = db.get_patient_visits(patient.id)
    assert len(history) == 2
    assert history[0].visit_number == 1
    assert history[1].visit_number == 2
    assert history[1].bp_systolic == 142
