"""Google Cloud Firestore persistence layer for ASHA ANC Copilot.

Supports both:
1. Google Cloud Firestore SDK (google-cloud-firestore)
2. Direct Firestore REST API (using httpx when SDK is unavailable)
3. Flexible credentials via:
   - FIREBASE_SERVICE_ACCOUNT_JSON (raw JSON string in environment variable)
   - GOOGLE_APPLICATION_CREDENTIALS (path to service account json file)
   - FIRESTORE_PROJECT_ID (GCP project id)
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from app.db import PatientRecord, VisitRecord

logger = logging.getLogger(__name__)


def is_firestore_configured() -> bool:
    """Return True if Firestore environment variables are present."""
    return bool(
        os.getenv("FIRESTORE_PROJECT_ID")
        or os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
        or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    )


class FirestoreDatabase:
    """Manages Google Cloud Firestore operations for patients and visits."""

    def __init__(
        self,
        project_id: str | None = None,
        service_account_json: str | None = None,
        credentials_path: str | None = None,
    ) -> None:
        self.project_id = project_id or os.getenv("FIRESTORE_PROJECT_ID")
        self.service_account_json = service_account_json or os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
        self.credentials_path = credentials_path or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        self.client: Any = None
        self._init_client()

    def _init_client(self) -> None:
        """Initialize Google Cloud Firestore Client."""
        try:
            from google.cloud import firestore
            from google.oauth2 import service_account

            creds = None
            if self.service_account_json:
                sa_info = json.loads(self.service_account_json)
                creds = service_account.Credentials.from_service_account_info(sa_info)
                if not self.project_id and "project_id" in sa_info:
                    self.project_id = sa_info["project_id"]
            elif self.credentials_path and os.path.exists(self.credentials_path):
                creds = service_account.Credentials.from_service_account_file(self.credentials_path)

            if creds:
                self.client = firestore.Client(project=self.project_id, credentials=creds)
            else:
                self.client = firestore.Client(project=self.project_id)
            logger.info("Connected to Google Cloud Firestore (Project: %s)", self.project_id or "default")
        except Exception as error:
            logger.warning("Could not initialize google-cloud-firestore client: %s", error)
            raise

    # -------------------------------------------------------------
    # Patients Collection
    # -------------------------------------------------------------
    def create_patient(
        self,
        rch_id: str,
        name: str,
        age: int | None = None,
        village: str | None = None,
        edd: str | None = None,
    ) -> PatientRecord:
        """Create a new patient in Firestore."""
        existing = self.get_patient_by_rch(rch_id)
        if existing:
            return existing

        patient_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        doc_data = {
            "id": patient_id,
            "rch_id": str(rch_id).strip(),
            "name": name.strip(),
            "age": age,
            "village": village.strip() if village else None,
            "edd": edd.strip() if edd else None,
            "created_at": created_at,
        }
        self.client.collection("patients").document(patient_id).set(doc_data)
        return PatientRecord(
            id=patient_id,
            rch_id=str(rch_id).strip(),
            name=name.strip(),
            age=age,
            village=village.strip() if village else None,
            edd=edd.strip() if edd else None,
            created_at=created_at,
        )

    def get_patient_by_rch(self, rch_id: str) -> PatientRecord | None:
        """Fetch patient by 12-digit RCH ID."""
        docs = (
            self.client.collection("patients")
            .where("rch_id", "==", str(rch_id).strip())
            .limit(1)
            .stream()
        )
        for doc in docs:
            data = doc.to_dict()
            return PatientRecord(
                id=data["id"],
                rch_id=data["rch_id"],
                name=data["name"],
                age=data.get("age"),
                village=data.get("village"),
                edd=data.get("edd"),
                created_at=data["created_at"],
            )
        return None

    def get_patient_by_id(self, patient_id: str) -> PatientRecord | None:
        """Fetch patient by primary UUID."""
        doc = self.client.collection("patients").document(patient_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        return PatientRecord(
            id=data["id"],
            rch_id=data["rch_id"],
            name=data["name"],
            age=data.get("age"),
            village=data.get("village"),
            edd=data.get("edd"),
            created_at=data["created_at"],
        )

    def list_patients(self, query: str | None = None) -> list[PatientRecord]:
        """List registered expectant mothers with optional query filter."""
        docs = self.client.collection("patients").order_by("name").stream()
        results = []
        q = query.strip().lower() if query else None
        for doc in docs:
            data = doc.to_dict()
            name = (data.get("name") or "").lower()
            rch_id = (data.get("rch_id") or "").lower()
            village = (data.get("village") or "").lower()
            if q and (q not in name and q not in rch_id and q not in village):
                continue
            results.append(
                PatientRecord(
                    id=data["id"],
                    rch_id=data["rch_id"],
                    name=data["name"],
                    age=data.get("age"),
                    village=data.get("village"),
                    edd=data.get("edd"),
                    created_at=data["created_at"],
                )
            )
        return results

    # -------------------------------------------------------------
    # Visits Collection
    # -------------------------------------------------------------
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
        evidence_json: dict[str, str] | None = None,
        referral_flag: str | None = None,
        rule_ids: list[str] | None = None,
        status: str = "LOCKED",
        created_at: str | None = None,
        transcript_turn1: str | None = None,
        transcript_turn2: str | None = None,
        transcripts_json: list[dict[str, Any]] | None = None,
        risk_score: int | None = None,
        risk_tier: str | None = None,
        referral_status: str = "PENDING",
    ) -> VisitRecord:
        """Persist a completed or locked ANC visit record."""
        visit_id = str(uuid.uuid4())
        created_at_val = created_at or datetime.now(timezone.utc).isoformat()
        evidence_map = evidence_json or {}
        rules_list = rule_ids or []
        transcripts_list = transcripts_json or []

        doc_data = {
            "id": visit_id,
            "patient_id": patient_id,
            "session_id": session_id,
            "visit_number": visit_number,
            "gestational_weeks": gestational_weeks,
            "bp_systolic": bp_systolic,
            "bp_diastolic": bp_diastolic,
            "weight_kg": weight_kg,
            "hemoglobin": hemoglobin,
            "tri_state_json": tri_state_json,
            "evidence_json": evidence_map,
            "referral_flag": referral_flag,
            "rule_ids": rules_list,
            "status": status,
            "created_at": created_at_val,
            "transcript_turn1": transcript_turn1,
            "transcript_turn2": transcript_turn2,
            "transcripts_json": transcripts_list,
            "risk_score": risk_score,
            "risk_tier": risk_tier,
            "verified_by_supervisor": False,
            "supervisor_notes": None,
            "referral_status": referral_status,
        }
        self.client.collection("visits").document(visit_id).set(doc_data)
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
            rule_ids=rules_list,
            status=status,
            created_at=created_at_val,
            transcript_turn1=transcript_turn1,
            transcript_turn2=transcript_turn2,
            transcripts_json=transcripts_list,
            risk_score=risk_score,
            risk_tier=risk_tier,
            referral_status=referral_status,
        )

    def get_patient_visits(self, patient_id: str) -> list[VisitRecord]:
        """Fetch all historical visits for a patient ordered by visit number."""
        docs = (
            self.client.collection("visits")
            .where("patient_id", "==", patient_id)
            .stream()
        )
        visits = [self._doc_to_visit(doc.to_dict()) for doc in docs]
        visits.sort(key=lambda v: v.visit_number)
        return visits

    def get_visit_by_id(self, visit_id: str) -> VisitRecord | None:
        """Fetch a single visit by its UUID."""
        doc = self.client.collection("visits").document(visit_id).get()
        if not doc.exists:
            return None
        return self._doc_to_visit(doc.to_dict())

    def verify_visit(self, visit_id: str, supervisor_notes: str | None = None) -> bool:
        """Mark a visit as verified by medical supervisor."""
        doc_ref = self.client.collection("visits").document(visit_id)
        updates: dict[str, Any] = {"verified_by_supervisor": True}
        if supervisor_notes is not None:
            updates["supervisor_notes"] = supervisor_notes
        doc_ref.update(updates)
        return True

    def update_referral_status(
        self, visit_id: str, referral_status: str, supervisor_notes: str | None = None
    ) -> bool:
        """Update referral status (e.g. COMPLETED, REFERRED, ESCALATED)."""
        doc_ref = self.client.collection("visits").document(visit_id)
        updates: dict[str, Any] = {"referral_status": referral_status}
        if supervisor_notes is not None:
            updates["supervisor_notes"] = supervisor_notes
        doc_ref.update(updates)
        return True

    def get_supervisor_summary(self) -> dict[str, Any]:
        """Compute aggregate clinical indicators across all patients and visits."""
        patients = self.list_patients()
        total_patients = len(patients)

        all_visits_docs = self.client.collection("visits").stream()
        all_visits = [self._doc_to_visit(doc.to_dict()) for doc in all_visits_docs]
        total_visits = len(all_visits)

        # Group latest visit per patient
        patient_latest: dict[str, VisitRecord] = {}
        for v in all_visits:
            cur = patient_latest.get(v.patient_id)
            if cur is None or v.visit_number > cur.visit_number:
                patient_latest[v.patient_id] = v

        high_risk_count = 0
        mod_risk_count = 0
        low_risk_count = 0
        overdue_count = 0
        pending_referrals = 0
        villages_map: dict[str, dict[str, int]] = {}

        now = datetime.now(timezone.utc)

        for p in patients:
            village = p.village or "Unknown"
            if village not in villages_map:
                villages_map[village] = {"total": 0, "high_risk": 0, "overdue": 0}
            villages_map[village]["total"] += 1

            v = patient_latest.get(p.id)
            if v:
                tier = v.risk_tier
                score = v.risk_score or 0
                if tier == "HIGH" or score >= 60:
                    high_risk_count += 1
                    villages_map[village]["high_risk"] += 1
                elif tier == "MODERATE" or score >= 30:
                    mod_risk_count += 1
                else:
                    low_risk_count += 1

                if v.referral_flag and v.referral_status in {"PENDING", "REFERRED"}:
                    pending_referrals += 1

                if v.created_at:
                    try:
                        visit_dt = datetime.fromisoformat(v.created_at.replace("Z", "+00:00"))
                        if (now - visit_dt).days > 35:
                            overdue_count += 1
                            villages_map[village]["overdue"] += 1
                    except Exception:
                        pass
            else:
                low_risk_count += 1

        village_breakdown = [
            {"village": v, "total": data["total"], "high_risk": data["high_risk"], "overdue": data["overdue"]}
            for v, data in sorted(villages_map.items())
        ]

        return {
            "total_mothers": total_patients,
            "total_visits": total_visits,
            "high_risk_count": high_risk_count,
            "moderate_risk_count": mod_risk_count,
            "low_risk_count": low_risk_count,
            "overdue_visits": overdue_count,
            "pending_referrals": pending_referrals,
            "village_breakdown": village_breakdown,
        }

    def seed_initial_patients(self) -> None:
        """Seed initial patient profiles if database is empty."""
        existing = (
            self.client.collection("patients")
            .limit(1)
            .stream()
        )
        if any(existing):
            return

        # Seed standard initial patients
        self.create_patient(
            rch_id="109283748291",
            name="Sunita Devi",
            age=24,
            village="Rampur",
            edd="2026-11-15",
        )
        p1 = self.get_patient_by_rch("109283748291")
        if p1:
            self.save_visit(
                patient_id=p1.id,
                session_id="seed-visit-sunita-1",
                visit_number=1,
                gestational_weeks=14,
                bp_systolic=118,
                bp_diastolic=76,
                weight_kg=48.0,
                hemoglobin=11.2,
                tri_state_json={"swelling": "denied", "vaginal_bleeding": "denied"},
                referral_flag=None,
                rule_ids=[],
                transcript_turn1="सुनीता देवी 14 हफ्ते की गर्भवती, बीपी 118/76 सामान्य, वजन 48 किलो।",
                risk_score=15,
                risk_tier="LOW",
            )
            self.save_visit(
                patient_id=p1.id,
                session_id="seed-visit-sunita-2",
                visit_number=2,
                gestational_weeks=26,
                bp_systolic=148,
                bp_diastolic=96,
                weight_kg=51.5,
                hemoglobin=10.4,
                tri_state_json={
                    "swelling": "present",
                    "severe_headache": "present",
                    "blurred_vision": "denied",
                    "vaginal_bleeding": "denied",
                },
                evidence_json={"swelling": "pairon me sujan hai", "severe_headache": "sir me dard rehta hai"},
                referral_flag="CLINICIAN",
                rule_ids=["ANC-01", "ANC-04"],
                transcript_turn1="26 हफ्ते, बीपी 148/96 है, पैरों में सूजन और सिरदर्द है।",
                risk_score=75,
                risk_tier="HIGH",
            )

        self.create_patient(
            rch_id="209384758192",
            name="Meena Kumari",
            age=28,
            village="Kalyanpur",
            edd="2026-12-05",
        )
        p2 = self.get_patient_by_rch("209384758192")
        if p2:
            self.save_visit(
                patient_id=p2.id,
                session_id="seed-visit-meena-1",
                visit_number=1,
                gestational_weeks=16,
                bp_systolic=110,
                bp_diastolic=70,
                weight_kg=52.0,
                hemoglobin=8.2,
                tri_state_json={"swelling": "denied"},
                evidence_json={"anemia_or_low_hb_mentioned": "hb kam hai 8.2"},
                referral_flag="CLINICIAN",
                rule_ids=["ANC-08"],
                transcript_turn1="16 हफ्ते, बीपी 110/70, हीमोग्लोबिन केवल 8.2 है, बहुत कमजोरी महसूस होती है।",
                risk_score=65,
                risk_tier="HIGH",
            )

        self.create_patient(
            rch_id="408192837465",
            name="Anjali Patel",
            age=22,
            village="Rampur",
            edd="2026-10-30",
        )
        p3 = self.get_patient_by_rch("408192837465")
        if p3:
            self.save_visit(
                patient_id=p3.id,
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

    def _doc_to_visit(self, data: dict[str, Any]) -> VisitRecord:
        """Convert Firestore dictionary document to VisitRecord dataclass."""
        return VisitRecord(
            id=data["id"],
            patient_id=data["patient_id"],
            session_id=data["session_id"],
            visit_number=int(data["visit_number"]),
            gestational_weeks=data.get("gestational_weeks"),
            bp_systolic=data.get("bp_systolic"),
            bp_diastolic=data.get("bp_diastolic"),
            weight_kg=data.get("weight_kg"),
            hemoglobin=data.get("hemoglobin"),
            tri_state_json=data.get("tri_state_json") or {},
            evidence_json=data.get("evidence_json") or {},
            referral_flag=data.get("referral_flag"),
            rule_ids=data.get("rule_ids") or [],
            status=data.get("status", "LOCKED"),
            created_at=data.get("created_at") or datetime.now(timezone.utc).isoformat(),
            transcript_turn1=data.get("transcript_turn1"),
            transcript_turn2=data.get("transcript_turn2"),
            transcripts_json=data.get("transcripts_json") or [],
            risk_score=data.get("risk_score"),
            risk_tier=data.get("risk_tier"),
            verified_by_supervisor=bool(data.get("verified_by_supervisor", False)),
            supervisor_notes=data.get("supervisor_notes"),
            referral_status=data.get("referral_status", "PENDING"),
        )
