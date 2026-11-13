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
    transcript_turn1: str | None = None
    transcript_turn2: str | None = None
    transcripts_json: list[dict[str, Any]] = field(default_factory=list)
    risk_score: int | None = None
    risk_tier: str | None = None
    verified_by_supervisor: bool = False
    supervisor_notes: str | None = None
    referral_status: str = "PENDING"


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
                    transcript_turn1 TEXT,
                    transcript_turn2 TEXT,
                    transcripts_json TEXT,
                    risk_score INTEGER,
                    risk_tier TEXT,
                    verified_by_supervisor INTEGER DEFAULT 0,
                    supervisor_notes TEXT,
                    referral_status TEXT DEFAULT 'PENDING',
                    FOREIGN KEY (patient_id) REFERENCES patients(id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_visits_patient ON visits(patient_id, visit_number)"
            )
            # Ensure new columns exist for existing databases
            existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(visits)").fetchall()}
            for col_name, col_def in (
                ("transcript_turn1", "TEXT"),
                ("transcript_turn2", "TEXT"),
                ("transcripts_json", "TEXT"),
                ("risk_score", "INTEGER"),
                ("risk_tier", "TEXT"),
                ("verified_by_supervisor", "INTEGER DEFAULT 0"),
                ("supervisor_notes", "TEXT"),
                ("referral_status", "TEXT DEFAULT 'PENDING'"),
            ):
                if col_name not in existing_cols:
                    try:
                        conn.execute(f"ALTER TABLE visits ADD COLUMN {col_name} {col_def}")
                    except sqlite3.OperationalError:
                        pass
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
        transcript_turn1: str | None = None,
        transcript_turn2: str | None = None,
        transcripts_json: list[dict[str, Any]] | None = None,
        risk_score: int | None = None,
        risk_tier: str | None = None,
        referral_status: str = "PENDING",
    ) -> VisitRecord:
        visit_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        evidence_map = evidence_json or {}
        transcripts_list = transcripts_json or []
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO visits (
                    id, patient_id, session_id, visit_number,
                    gestational_weeks, bp_systolic, bp_diastolic, weight_kg, hemoglobin,
                    tri_state_json, evidence_json, referral_flag, rule_ids, status, created_at,
                    transcript_turn1, transcript_turn2, transcripts_json, risk_score, risk_tier, referral_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    transcript_turn1,
                    transcript_turn2,
                    json.dumps(transcripts_list),
                    risk_score,
                    risk_tier,
                    referral_status,
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
            transcript_turn1=transcript_turn1,
            transcript_turn2=transcript_turn2,
            transcripts_json=transcripts_list,
            risk_score=risk_score,
            risk_tier=risk_tier,
            referral_status=referral_status,
        )

    def _row_to_visit(self, row: sqlite3.Row) -> VisitRecord:
        keys = row.keys()
        tri_state = json.loads(row["tri_state_json"]) if "tri_state_json" in keys and row["tri_state_json"] else {}
        evidence = json.loads(row["evidence_json"]) if "evidence_json" in keys and row["evidence_json"] else {}
        rule_ids = json.loads(row["rule_ids"]) if "rule_ids" in keys and row["rule_ids"] else []
        transcripts = (
            json.loads(row["transcripts_json"])
            if "transcripts_json" in keys and row["transcripts_json"]
            else []
        )
        return VisitRecord(
            id=row["id"],
            patient_id=row["patient_id"],
            session_id=row["session_id"],
            visit_number=row["visit_number"],
            gestational_weeks=row["gestational_weeks"],
            bp_systolic=row["bp_systolic"],
            bp_diastolic=row["bp_diastolic"],
            weight_kg=row["weight_kg"],
            hemoglobin=row["hemoglobin"],
            tri_state_json=tri_state,
            evidence_json=evidence,
            referral_flag=row["referral_flag"],
            rule_ids=rule_ids,
            status=row["status"],
            created_at=row["created_at"],
            transcript_turn1=row["transcript_turn1"] if "transcript_turn1" in keys else None,
            transcript_turn2=row["transcript_turn2"] if "transcript_turn2" in keys else None,
            transcripts_json=transcripts,
            risk_score=row["risk_score"] if "risk_score" in keys else None,
            risk_tier=row["risk_tier"] if "risk_tier" in keys else None,
            verified_by_supervisor=bool(row["verified_by_supervisor"]) if "verified_by_supervisor" in keys and row["verified_by_supervisor"] else False,
            supervisor_notes=row["supervisor_notes"] if "supervisor_notes" in keys else None,
            referral_status=row["referral_status"] if "referral_status" in keys and row["referral_status"] else "PENDING",
        )

    def get_patient_visits(self, patient_id: str) -> list[VisitRecord]:
        with self.connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM visits WHERE patient_id = ? ORDER BY visit_number ASC",
                (patient_id,),
            )
            rows = cursor.fetchall()
            return [self._row_to_visit(row) for row in rows]

    def get_visit_by_id(self, visit_id: str) -> VisitRecord | None:
        with self.connect() as conn:
            cursor = conn.execute("SELECT * FROM visits WHERE id = ?", (visit_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_visit(row)

    def verify_visit(self, visit_id: str, supervisor_notes: str | None = None) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE visits
                SET verified_by_supervisor = 1, supervisor_notes = COALESCE(?, supervisor_notes)
                WHERE id = ?
                """,
                (supervisor_notes, visit_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_referral_status(
        self, visit_id: str, referral_status: str, supervisor_notes: str | None = None
    ) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE visits
                SET referral_status = ?, supervisor_notes = COALESCE(?, supervisor_notes)
                WHERE id = ?
                """,
                (referral_status, supervisor_notes, visit_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_supervisor_summary(self) -> dict[str, Any]:
        """Aggregate high-level clinical metrics for PHC / ANM supervisor."""
        with self.connect() as conn:
            total_patients = conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
            total_visits = conn.execute("SELECT COUNT(*) FROM visits").fetchone()[0]

            # Latest visits per patient
            cursor = conn.execute(
                """
                SELECT p.id as patient_id, p.rch_id, p.name, p.village, p.edd,
                       v.id as visit_id, v.visit_number, v.gestational_weeks,
                       v.bp_systolic, v.bp_diastolic, v.hemoglobin, v.risk_score,
                       v.risk_tier, v.referral_flag, v.referral_status, v.created_at as last_visit_date
                FROM patients p
                LEFT JOIN visits v ON v.patient_id = p.id AND v.visit_number = (
                    SELECT MAX(v2.visit_number) FROM visits v2 WHERE v2.patient_id = p.id
                )
                """
            )
            rows = cursor.fetchall()

            high_risk_count = 0
            mod_risk_count = 0
            low_risk_count = 0
            overdue_count = 0
            pending_referrals = 0
            villages_map: dict[str, dict[str, int]] = {}

            now = datetime.now(timezone.utc)

            for r in rows:
                village = r["village"] or "Unknown"
                if village not in villages_map:
                    villages_map[village] = {"total": 0, "high_risk": 0, "overdue": 0}
                villages_map[village]["total"] += 1

                tier = r["risk_tier"]
                score = r["risk_score"] or 0
                if tier == "HIGH" or score >= 60:
                    high_risk_count += 1
                    villages_map[village]["high_risk"] += 1
                elif tier == "MODERATE" or score >= 30:
                    mod_risk_count += 1
                else:
                    low_risk_count += 1

                # Check referral status
                ref_flag = r["referral_flag"]
                ref_stat = r["referral_status"] or "PENDING"
                if ref_flag and ref_stat in {"PENDING", "REFERRED"}:
                    pending_referrals += 1

                # Check overdue status
                last_dt_str = r["last_visit_date"]
                is_overdue = False
                if last_dt_str:
                    try:
                        clean_dt = last_dt_str.replace("Z", "+00:00")
                        dt = datetime.fromisoformat(clean_dt)
                        if (now - dt).days > 35:
                            is_overdue = True
                    except (ValueError, TypeError):
                        pass
                else:
                    is_overdue = True  # Registered but never visited

                if is_overdue:
                    overdue_count += 1
                    villages_map[village]["overdue"] += 1

            return {
                "total_mothers": total_patients,
                "total_visits": total_visits,
                "high_risk_mothers": high_risk_count,
                "moderate_risk_mothers": mod_risk_count,
                "low_risk_mothers": low_risk_count,
                "overdue_visits": overdue_count,
                "pending_referrals": pending_referrals,
                "villages": [
                    {
                        "name": v_name,
                        "total_mothers": v_stats["total"],
                        "high_risk_mothers": v_stats["high_risk"],
                        "overdue_visits": v_stats["overdue"],
                    }
                    for v_name, v_stats in sorted(villages_map.items())
                ],
            }

    def seed_initial_patients(self) -> None:
        """Seed rich initial patient profiles for instant demo, testing, and supervisor views."""
        if not self.list_patients():
            # Patient 1: Sunita Devi - Developing Pre-eclampsia (Moderate -> High Risk)
            self.create_patient(
                rch_id="109283748291",
                name="Sunita Devi",
                age=24,
                village="Rampur",
                edd="2026-12-15",
            )
            p1 = self.get_patient_by_rch("109283748291")
            if p1:
                # Visit 1 (Baseline)
                self.save_visit(
                    patient_id=p1.id,
                    session_id="seed-visit-sunita-1",
                    visit_number=1,
                    gestational_weeks=12,
                    bp_systolic=110,
                    bp_diastolic=70,
                    weight_kg=48.0,
                    hemoglobin=11.5,
                    tri_state_json={"swelling": "denied", "vaginal_bleeding": "denied"},
                    referral_flag=None,
                    rule_ids=[],
                    transcript_turn1="सुनीता देवी 12 हफ्ते की गर्भवती हैं, बीपी 110 बटा 70 है, वजन 48 किलो है, कोई ब्लीडिंग या सूजन नहीं है।",
                    risk_score=15,
                    risk_tier="LOW",
                )
                # Visit 2 (Longitudinal Surge)
                self.save_visit(
                    patient_id=p1.id,
                    session_id="seed-visit-sunita-2",
                    visit_number=2,
                    gestational_weeks=28,
                    bp_systolic=142,
                    bp_diastolic=92,
                    weight_kg=54.5,
                    hemoglobin=9.2,
                    tri_state_json={"swelling": "present", "severe_headache": "present", "blurred_vision": "denied"},
                    referral_flag="CLINICIAN_REFERRAL",
                    rule_ids=["RULE-HRP-01", "RULE-HRP-02", "RULE-HRP-03", "RULE-LONG-01", "RULE-LONG-03"],
                    evidence_json={"severe_headache": "सिर में भारी दर्द है", "swelling": "पैरों में हल्की सूजन"},
                    transcript_turn1="सुनीता देवी का 28वां हफ्ता चल रहा है। बीपी 142 बटा 92 आया है। सिर में काफी दर्द है और पैरों में सूजन है।",
                    transcript_turn2="धुंधला दिखने की कोई शिकायत नहीं है।",
                    transcripts_json=[
                        {"turn": 1, "role": "asha_visit_note", "transcript": "सुनीता देवी का 28वां हफ्ता चल रहा है। बीपी 142 बटा 92 आया है। सिर में काफी दर्द है और पैरों में सूजन है।"},
                        {"turn": 2, "role": "followup_response", "transcript": "धुंधला दिखने की कोई शिकायत नहीं है।"}
                    ],
                    risk_score=75,
                    risk_tier="HIGH",
                    referral_status="REFERRED",
                )

            # Patient 2: Meena Kumari - Urgent Eclampsia/BP Crisis (Critical High Risk)
            self.create_patient(
                rch_id="204918273645",
                name="Meena Kumari",
                age=28,
                village="Shivpur",
                edd="2026-11-28",
            )
            p2 = self.get_patient_by_rch("204918273645")
            if p2:
                self.save_visit(
                    patient_id=p2.id,
                    session_id="seed-visit-meena-1",
                    visit_number=1,
                    gestational_weeks=24,
                    bp_systolic=164,
                    bp_diastolic=112,
                    weight_kg=58.0,
                    hemoglobin=10.1,
                    tri_state_json={"severe_headache": "present", "blurred_vision": "present", "swelling": "present"},
                    referral_flag="URGENT_REFERRAL",
                    rule_ids=["RULE-EMG-03", "RULE-HRP-01"],
                    evidence_json={"severe_headache": "तेज सिरदर्द", "blurred_vision": "आंखों के आगे धुंधलापन"},
                    transcript_turn1="मीना कुमारी 24 हफ्ते, बीपी 164 बटा 112 बहुत ज्यादा है, सिर में असहनीय दर्द और आंखों के आगे धुंधलापन है।",
                    risk_score=95,
                    risk_tier="HIGH",
                    referral_status="PENDING",
                )

            # Patient 3: Pooja Sharma - Overdue ANC Checkup
            self.create_patient(
                rch_id="309182746501",
                name="Pooja Sharma",
                age=21,
                village="Kalyanpur",
                edd="2027-01-10",
            )
            p3 = self.get_patient_by_rch("309182746501")
            if p3:
                self.save_visit(
                    patient_id=p3.id,
                    session_id="seed-visit-pooja-1",
                    visit_number=1,
                    gestational_weeks=10,
                    bp_systolic=112,
                    bp_diastolic=72,
                    weight_kg=47.0,
                    hemoglobin=11.8,
                    tri_state_json={"swelling": "denied", "vaginal_bleeding": "denied"},
                    referral_flag=None,
                    rule_ids=[],
                    transcript_turn1="पूजा शर्मा पहली जांच 10 हफ्ते पर, बीपी 112/72 सामान्य, वजन 47 किलो, हीमोग्लोबिन 11.8।",
                    risk_score=10,
                    risk_tier="LOW",
                )

            # Patient 4: Anjali Patel - Model Healthy Pregnancy (3 visits complete)
            self.create_patient(
                rch_id="408192837465",
                name="Anjali Patel",
                age=22,
                village="Rampur",
                edd="2026-10-30",
            )
            p4 = self.get_patient_by_rch("408192837465")
            if p4:
                self.save_visit(
                    patient_id=p4.id,
                    session_id="seed-visit-anjali-1",
                    visit_number=1,
                    gestational_weeks=12,
                    bp_systolic=108,
                    bp_diastolic=68,
                    weight_kg=46.0,
                    hemoglobin=12.0,
                    tri_state_json={"swelling": "denied", "vaginal_bleeding": "denied"},
                    referral_flag=None,
                    rule_ids=[],
                    risk_score=5,
                    risk_tier="LOW",
                )
                self.save_visit(
                    patient_id=p4.id,
                    session_id="seed-visit-anjali-2",
                    visit_number=2,
                    gestational_weeks=22,
                    bp_systolic=112,
                    bp_diastolic=70,
                    weight_kg=49.5,
                    hemoglobin=11.6,
                    tri_state_json={"swelling": "denied", "reduced_fetal_movement": "denied"},
                    referral_flag=None,
                    rule_ids=[],
                    risk_score=5,
                    risk_tier="LOW",
                )
                self.save_visit(
                    patient_id=p4.id,
                    session_id="seed-visit-anjali-3",
                    visit_number=3,
                    gestational_weeks=32,
                    bp_systolic=114,
                    bp_diastolic=72,
                    weight_kg=53.0,
                    hemoglobin=11.4,
                    tri_state_json={"swelling": "denied", "reduced_fetal_movement": "denied"},
                    referral_flag=None,
                    rule_ids=[],
                    risk_score=8,
                    risk_tier="LOW",
                )


def init_db(db_path: Path | str | None = None, seed: bool = False) -> Database:
    path = db_path or DEFAULT_DB_PATH
    db = Database(path)
    if seed:
        db.seed_initial_patients()
    return db
