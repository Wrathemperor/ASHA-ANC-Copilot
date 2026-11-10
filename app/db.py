"""SQLite persistence layer for patients and longitudinal ANC visits."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "asha_anc.db"


@dataclass
class PatientRecord:
    id: str
    rch_id: str
    name: str
    age: int | None = None
    village: str | None = None
    edd: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class VisitRecord:
    id: str
    patient_id: str
    session_id: str
    visit_number: int
    gestational_weeks: int | None
    bp_systolic: int | None
    bp_diastolic: int | None
    weight_kg: float | None
    hemoglobin: float | None
    tri_state_json: dict[str, Any]
    referral_flag: str | None
    rule_ids: list[str]
    evidence_json: dict[str, str] = field(default_factory=dict)
    status: str = "LOCKED"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class Database:
    """Manages SQLite connection and data operations."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS patients (
                    id TEXT PRIMARY KEY,
                    rch_id TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    age INTEGER,
                    village TEXT,
                    edd TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS visits (
                    id TEXT PRIMARY KEY,
                    patient_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    visit_number INTEGER NOT NULL,
                    gestational_weeks INTEGER,
                    bp_systolic INTEGER,
                    bp_diastolic INTEGER,
                    weight_kg REAL,
                    hemoglobin REAL,
                    tri_state_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    referral_flag TEXT,
                    rule_ids TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (patient_id) REFERENCES patients(id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_visits_patient ON visits(patient_id, visit_number)"
            )
            conn.commit()

    def create_patient(
        self,
        rch_id: str,
        name: str,
        age: int | None = None,
        village: str | None = None,
        edd: str | None = None,
    ) -> PatientRecord:
        patient_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO patients (id, rch_id, name, age, village, edd, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(rch_id) DO UPDATE SET
                    name = excluded.name,
                    age = COALESCE(excluded.age, patients.age),
                    village = COALESCE(excluded.village, patients.village),
                    edd = COALESCE(excluded.edd, patients.edd)
                """,
                (patient_id, rch_id.strip(), name.strip(), age, village, edd, created_at),
            )
            conn.commit()
        return self.get_patient_by_rch(rch_id)  # type: ignore[return-value]

    def get_patient_by_rch(self, rch_id: str) -> PatientRecord | None:
        with self.connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM patients WHERE rch_id = ?", (rch_id.strip(),)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return PatientRecord(
                id=row["id"],
                rch_id=row["rch_id"],
                name=row["name"],
                age=row["age"],
                village=row["village"],
                edd=row["edd"],
                created_at=row["created_at"],
            )

    def get_patient_by_id(self, patient_id: str) -> PatientRecord | None:
        with self.connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM patients WHERE id = ?", (patient_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return PatientRecord(
                id=row["id"],
                rch_id=row["rch_id"],
                name=row["name"],
                age=row["age"],
                village=row["village"],
                edd=row["edd"],
                created_at=row["created_at"],
            )

    def list_patients(self, query: str | None = None) -> list[PatientRecord]:
        with self.connect() as conn:
            if query:
                pattern = f"%{query.strip()}%"
                cursor = conn.execute(
                    """
                    SELECT * FROM patients
                    WHERE name LIKE ? OR rch_id LIKE ? OR village LIKE ?
                    ORDER BY created_at DESC LIMIT 50
                    """,
                    (pattern, pattern, pattern),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM patients ORDER BY created_at DESC LIMIT 50"
                )
            rows = cursor.fetchall()
            return [
                PatientRecord(
                    id=row["id"],
                    rch_id=row["rch_id"],
                    name=row["name"],
                    age=row["age"],
                    village=row["village"],
                    edd=row["edd"],
                    created_at=row["created_at"],
                )
                for row in rows
            ]

    def save_visit(
        self,
        patient_id: str,
        session_id: str,
        visit_number: int,
        gestational_weeks: int | None,
        bp_systolic: int | None,
        bp_diastolic: int | None,
        weight_kg: float | None,
        hemoglobin: float | None,
        tri_state_json: dict[str, Any],
        referral_flag: str | None,
        rule_ids: list[str],
        evidence_json: dict[str, str] | None = None,
        status: str = "LOCKED",
    ) -> VisitRecord:
        visit_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        evidence_map = evidence_json or {}
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO visits (
                    id, patient_id, session_id, visit_number,
                    gestational_weeks, bp_systolic, bp_diastolic, weight_kg, hemoglobin,
                    tri_state_json, evidence_json, referral_flag, rule_ids, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    visit_id,
                    patient_id,
                    session_id,
                    visit_number,
                    gestational_weeks,
                    bp_systolic,
                    bp_diastolic,
                    weight_kg,
                    hemoglobin,
                    json.dumps(tri_state_json),
                    json.dumps(evidence_map),
                    referral_flag,
                    json.dumps(rule_ids),
                    status,
                    created_at,
                ),
            )
            conn.commit()
        return VisitRecord(
            id=visit_id,
            patient_id=patient_id,
            session_id=session_id,
            visit_number=visit_number,
            gestational_weeks=gestational_weeks,
            bp_systolic=bp_systolic,
            bp_diastolic=bp_diastolic,
            weight_kg=weight_kg,
            hemoglobin=hemoglobin,
            tri_state_json=tri_state_json,
            evidence_json=evidence_map,
            referral_flag=referral_flag,
            rule_ids=rule_ids,
            status=status,
            created_at=created_at,
        )

    def get_patient_visits(self, patient_id: str) -> list[VisitRecord]:
        with self.connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM visits WHERE patient_id = ? ORDER BY visit_number ASC",
                (patient_id,),
            )
            rows = cursor.fetchall()
            return [
                VisitRecord(
                    id=row["id"],
                    patient_id=row["patient_id"],
                    session_id=row["session_id"],
                    visit_number=row["visit_number"],
                    gestational_weeks=row["gestational_weeks"],
                    bp_systolic=row["bp_systolic"],
                    bp_diastolic=row["bp_diastolic"],
                    weight_kg=row["weight_kg"],
                    hemoglobin=row["hemoglobin"],
                    tri_state_json=json.loads(row["tri_state_json"]),
                    evidence_json=json.loads(row["evidence_json"]),
                    referral_flag=row["referral_flag"],
                    rule_ids=json.loads(row["rule_ids"]),
                    status=row["status"],
                    created_at=row["created_at"],
                )
                for row in rows
            ]

    def seed_initial_patients(self) -> None:
        """Seed initial patient profiles for instant demo and testing."""
        if not self.list_patients():
            self.create_patient(
                rch_id="109283748291",
                name="Sunita Devi",
                age=24,
                village="Rampur",
                edd="2026-12-15",
            )
            p1 = self.get_patient_by_rch("109283748291")
            if p1:
                self.save_visit(
                    patient_id=p1.id,
                    session_id="seed-visit-1",
                    visit_number=1,
                    gestational_weeks=12,
                    bp_systolic=110,
                    bp_diastolic=70,
                    weight_kg=48.0,
                    hemoglobin=11.5,
                    tri_state_json={"swelling": "denied", "vaginal_bleeding": "denied"},
                    referral_flag=None,
                    rule_ids=[],
                )

            self.create_patient(
                rch_id="204918273645",
                name="Meena Kumari",
                age=28,
                village="Shivpur",
                edd="2026-11-28",
            )
            self.create_patient(
                rch_id="309182746501",
                name="Pooja Sharma",
                age=21,
                village="Kalyanpur",
                edd="2027-01-10",
            )


def init_db(db_path: Path | str | None = None, seed: bool = False) -> Database:
    path = db_path or DEFAULT_DB_PATH
    db = Database(path)
    if seed:
        db.seed_initial_patients()
    return db
