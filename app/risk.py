"""Deterministic composite Antenatal Risk Engine aligned with MoHFW PMSMA guidelines.

Computes an explainable 0-100 ANC Risk Score, risk tier classification (LOW/MODERATE/HIGH),
sub-score component breakdown, longitudinal trajectories, and ANC compliance tracking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.schema import ANCVisitRecord


@dataclass(frozen=True)
class RiskFactor:
    name: str
    category: str  # "vitals" | "danger_signs" | "anemia" | "trajectory" | "compliance" | "demographic"
    points: int
    severity: str  # "critical" | "warning" | "advisory"
    evidence: str


@dataclass(frozen=True)
class TrimesterCompliance:
    current_gestational_weeks: int | None
    expected_anc_stage: str  # "ANC 1" | "ANC 2" | "ANC 3" | "ANC 4" | "Post-Term" | "Unknown"
    is_overdue: bool
    days_since_last_visit: int | None
    completed_visits_count: int
    overdue_reason: str | None


@dataclass(frozen=True)
class TrajectoryPoint:
    visit_number: int
    gestational_weeks: int | None
    bp_systolic: int | None
    bp_diastolic: int | None
    weight_kg: float | None
    hemoglobin: float | None
    risk_score: int | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class RiskAssessment:
    score: int  # 0 to 100
    tier: str  # "LOW" | "MODERATE" | "HIGH"
    color: str  # "#10b981" (green), "#f59e0b" (amber), "#ef4444" (red)
    badge_label: str  # "Low Risk - Routine Care", "Moderate Risk - ANM Review", "High Risk - Urgent Referral"
    summary: str
    factors: list[RiskFactor]
    compliance: TrimesterCompliance
    trajectories: list[TrajectoryPoint]
    clinician_action: str
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def determine_anc_stage(weeks: int | None) -> str:
    """Determine expected MoHFW ANC visit stage based on gestational age."""
    if weeks is None:
        return "Unknown"
    if weeks <= 12:
        return "ANC 1 (First Trimester - Registration & Baseline)"
    if 13 <= weeks <= 26:
        return "ANC 2 (Second Trimester - Growth & Anemia Check)"
    if 27 <= weeks <= 35:
        return "ANC 3 (Third Trimester - Pre-eclampsia & Presentation)"
    if 36 <= weeks <= 41:
        return "ANC 4 (Term - Delivery Preparedness)"
    return "Post-Term (Hospital Delivery Alert)"


def calculate_compliance(
    current_weeks: int | None,
    previous_visits: list[dict[str, Any]] | None = None,
) -> TrimesterCompliance:
    """Evaluate ANC visit frequency against MoHFW 4-visit schedule."""
    past = previous_visits or []
    count = len(past)
    stage = determine_anc_stage(current_weeks)
    
    if not past:
        # First recorded visit
        return TrimesterCompliance(
            current_gestational_weeks=current_weeks,
            expected_anc_stage=stage,
            is_overdue=False,
            days_since_last_visit=None,
            completed_visits_count=0,
            overdue_reason=None,
        )

    # Sort past visits chronologically
    sorted_past = sorted(
        past,
        key=lambda v: (v.get("visit_number") or 0, v.get("created_at") or ""),
    )
    latest_visit = sorted_past[-1]
    last_weeks = latest_visit.get("gestational_weeks")
    last_date_str = latest_visit.get("created_at")

    days_diff: int | None = None
    if last_date_str:
        try:
            # Strip Z or offset for simple parsing
            cleaned_date = last_date_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned_date)
            now = datetime.now(timezone.utc)
            days_diff = max(0, (now - dt).days)
        except (ValueError, TypeError):
            days_diff = None

    # Check gestational week gap
    is_overdue = False
    reasons: list[str] = []

    if current_weeks is not None and last_weeks is not None:
        week_gap = current_weeks - last_weeks
        if current_weeks >= 28 and week_gap > 4:
            is_overdue = True
            reasons.append(f"{week_gap} weeks since last visit in third trimester (recommended: every 2-4 wks)")
        elif current_weeks >= 14 and week_gap > 8:
            is_overdue = True
            reasons.append(f"{week_gap} weeks gap between ANC checks (exceeds recommended trimester interval)")

    if days_diff is not None and days_diff > 45:
        is_overdue = True
        reasons.append(f"Last recorded visit was {days_diff} days ago")

    return TrimesterCompliance(
        current_gestational_weeks=current_weeks,
        expected_anc_stage=stage,
        is_overdue=is_overdue,
        days_since_last_visit=days_diff,
        completed_visits_count=count,
        overdue_reason="; ".join(reasons) if reasons else None,
    )


def compute_risk_score(
    record: ANCVisitRecord,
    previous_visits: list[dict[str, Any]] | None = None,
    patient_age: int | None = None,
) -> RiskAssessment:
    """Deterministic, explainable calculation of composite ANC Risk Score (0-100)."""
    factors: list[RiskFactor] = []
    points = 0
    past = previous_visits or []

    # 1. Blood Pressure Risk (up to 40 pts)
    sys = record.bp_systolic
    dia = record.bp_diastolic
    if sys is not None and dia is not None:
        if sys >= 160 or dia >= 110:
            points += 40
            factors.append(
                RiskFactor(
                    name="Severe Hypertension / Pre-eclampsia Alert",
                    category="vitals",
                    points=40,
                    severity="critical",
                    evidence=f"BP {sys}/{dia} mmHg (Severe cutoff >= 160/110)",
                )
            )
        elif sys >= 140 or dia >= 90:
            points += 25
            factors.append(
                RiskFactor(
                    name="Stage 1 Gestational Hypertension",
                    category="vitals",
                    points=25,
                    severity="warning",
                    evidence=f"BP {sys}/{dia} mmHg (Stage 1 cutoff >= 140/90)",
                )
            )
        elif sys >= 130 or dia >= 85:
            points += 10
            factors.append(
                RiskFactor(
                    name="Pre-Hypertensive Trend",
                    category="vitals",
                    points=10,
                    severity="advisory",
                    evidence=f"BP {sys}/{dia} mmHg (Approaching high-risk threshold)",
                )
            )

    # 2. Longitudinal BP Surge vs Baseline (up to 15 pts)
    if past and sys is not None and dia is not None:
        baseline = past[0]
        base_sys = baseline.get("bp_systolic")
        base_dia = baseline.get("bp_diastolic")
        if base_sys is not None and (sys - base_sys) >= 30:
            points += 15
            factors.append(
                RiskFactor(
                    name="Systolic Pressure Surge",
                    category="trajectory",
                    points=15,
                    severity="warning",
                    evidence=f"Systolic rose by +{sys - base_sys} mmHg from baseline ({base_sys} -> {sys})",
                )
            )
        elif base_dia is not None and (dia - base_dia) >= 15:
            points += 15
            factors.append(
                RiskFactor(
                    name="Diastolic Pressure Surge",
                    category="trajectory",
                    points=15,
                    severity="warning",
                    evidence=f"Diastolic rose by +{dia - base_dia} mmHg from baseline ({base_dia} -> {dia})",
                )
            )

    # 3. Obstetric Danger Signs (up to 40 pts)
    if record.convulsions == "present":
        points += 40
        factors.append(
            RiskFactor(
                name="Convulsions / Eclampsia Alert",
                category="danger_signs",
                points=40,
                severity="critical",
                evidence=record.evidence_spans.get("convulsions") or "Convulsions reported present",
            )
        )
    if record.vaginal_bleeding == "present":
        points += 35
        factors.append(
            RiskFactor(
                name="Antepartum Vaginal Bleeding",
                category="danger_signs",
                points=35,
                severity="critical",
                evidence=record.evidence_spans.get("vaginal_bleeding") or "Vaginal bleeding reported present",
            )
        )
    if record.severe_headache == "present" and record.blurred_vision == "present":
        points += 35
        factors.append(
            RiskFactor(
                name="Imminent Eclampsia Syndrome (Headache + Blurred Vision)",
                category="danger_signs",
                points=35,
                severity="critical",
                evidence="Concurrent severe headache and visual disturbances reported",
            )
        )
    elif record.severe_headache == "present":
        points += 15
        factors.append(
            RiskFactor(
                name="Severe Persistent Headache",
                category="danger_signs",
                points=15,
                severity="warning",
                evidence=record.evidence_spans.get("severe_headache") or "Severe headache reported",
            )
        )
    elif record.blurred_vision == "present":
        points += 15
        factors.append(
            RiskFactor(
                name="Visual Disturbance / Blurred Vision",
                category="danger_signs",
                points=15,
                severity="warning",
                evidence=record.evidence_spans.get("blurred_vision") or "Blurred vision reported",
            )
        )

    if record.severe_abdominal_pain == "present":
        points += 30
        factors.append(
            RiskFactor(
                name="Severe Abdominal Pain (Abruption/Spasm)",
                category="danger_signs",
                points=30,
                severity="critical",
                evidence=record.evidence_spans.get("severe_abdominal_pain") or "Severe abdominal pain reported",
            )
        )

    if record.reduced_fetal_movement == "present":
        points += 25
        factors.append(
            RiskFactor(
                name="Decreased Fetal Movement",
                category="danger_signs",
                points=25,
                severity="warning",
                evidence=record.evidence_spans.get("reduced_fetal_movement") or "Reduced fetal kick count reported",
            )
        )

    if record.leaking_fluid == "present":
        points += 20
        factors.append(
            RiskFactor(
                name="Premature Rupture of Membranes / Leaking Fluid",
                category="danger_signs",
                points=20,
                severity="warning",
                evidence=record.evidence_spans.get("leaking_fluid") or "Leaking fluid reported",
            )
        )

    if record.swelling == "present":
        points += 15
        factors.append(
            RiskFactor(
                name="Gestational Edema / Swelling",
                category="danger_signs",
                points=15,
                severity="advisory",
                evidence=record.evidence_spans.get("swelling") or "Swelling of hands/face reported",
            )
        )

    if record.fever == "present":
        points += 10
        factors.append(
            RiskFactor(
                name="Maternal Pyrexia / Fever",
                category="danger_signs",
                points=10,
                severity="advisory",
                evidence=record.evidence_spans.get("fever") or "Maternal fever reported",
            )
        )

    # 4. Hemoglobin & Anemia Trajectory (up to 30 pts)
    hb = record.hemoglobin
    if hb is not None:
        if hb < 7.0:
            points += 30
            factors.append(
                RiskFactor(
                    name="Severe Maternal Anemia",
                    category="anemia",
                    points=30,
                    severity="critical",
                    evidence=f"Hb {hb} g/dL (Severe anemia cutoff < 7.0 g/dL)",
                )
            )
        elif hb < 10.0:
            points += 15
            factors.append(
                RiskFactor(
                    name="Moderate Maternal Anemia",
                    category="anemia",
                    points=15,
                    severity="warning",
                    evidence=f"Hb {hb} g/dL (Moderate anemia cutoff 7.0 - 9.9 g/dL)",
                )
            )
        elif hb < 11.0:
            points += 5
            factors.append(
                RiskFactor(
                    name="Mild Maternal Anemia",
                    category="anemia",
                    points=5,
                    severity="advisory",
                    evidence=f"Hb {hb} g/dL (Normal cutoff >= 11.0 g/dL)",
                )
            )

    if past and hb is not None:
        latest_past = past[-1]
        prev_hb = latest_past.get("hemoglobin")
        if prev_hb is not None and (prev_hb - hb) >= 2.0:
            points += 20
            factors.append(
                RiskFactor(
                    name="Rapid Hemoglobin Drop",
                    category="trajectory",
                    points=20,
                    severity="critical",
                    evidence=f"Hb dropped by {round(prev_hb - hb, 1)} g/dL since last visit ({prev_hb} -> {hb})",
                )
            )

    # 5. Weight Gain Trajectory (up to 15 pts)
    curr_wt = record.weight_kg
    curr_wk = record.gestational_weeks
    if past and curr_wt is not None and curr_wk is not None:
        latest_past = past[-1]
        prev_wt = latest_past.get("weight_kg")
        prev_wk = latest_past.get("gestational_weeks")
        if prev_wt is not None and prev_wk is not None and curr_wk > prev_wk:
            delta_wt = curr_wt - prev_wt
            delta_wk = curr_wk - prev_wk
            rate = delta_wt / delta_wk
            if rate > 0.5 and delta_wt >= 2.0:
                points += 15
                factors.append(
                    RiskFactor(
                        name="Excessive Gestational Weight Gain",
                        category="trajectory",
                        points=15,
                        severity="warning",
                        evidence=f"Gained {round(delta_wt, 1)} kg in {delta_wk} wks ({round(rate, 2)} kg/wk vs normal <= 0.5 kg/wk)",
                    )
                )
            elif curr_wk >= 20 and delta_wt < 0:
                points += 10
                factors.append(
                    RiskFactor(
                        name="Inadequate Weight Gain / Weight Loss",
                        category="trajectory",
                        points=10,
                        severity="warning",
                        evidence=f"Weight loss of {abs(round(delta_wt, 1))} kg observed between weeks {prev_wk} and {curr_wk}",
                    )
                )

    # 6. Demographic Vulnerabilities (up to 10 pts)
    if patient_age is not None:
        if patient_age < 18:
            points += 10
            factors.append(
                RiskFactor(
                    name="Adolescent Pregnancy Risk",
                    category="demographic",
                    points=10,
                    severity="warning",
                    evidence=f"Age {patient_age} (< 18 years higher risk profile)",
                )
            )
        elif patient_age >= 35:
            points += 10
            factors.append(
                RiskFactor(
                    name="Advanced Maternal Age Risk",
                    category="demographic",
                    points=10,
                    severity="advisory",
                    evidence=f"Age {patient_age} (>= 35 years elevated risk)",
                )
            )

    # 7. Compliance & Overdue Check (up to 10 pts)
    weeks_val = int(record.gestational_weeks) if record.gestational_weeks is not None else None
    compliance = calculate_compliance(weeks_val, previous_visits=past)
    if compliance.is_overdue:
        points += 10
        factors.append(
            RiskFactor(
                name="Overdue ANC Checkup",
                category="compliance",
                points=10,
                severity="advisory",
                evidence=compliance.overdue_reason or "Visit interval exceeded recommended MoHFW schedule",
            )
        )

    # Cap score at 100
    final_score = min(100, max(0, points))

    # Determine Tier & Color
    if final_score >= 60:
        tier = "HIGH"
        color = "#ef4444"
        badge = "High Risk — Immediate Clinical Referral"
        action = "Immediate transfer to First Referral Unit (FRU) / Sub-district Hospital. Medical Officer review required today."
        summary = f"Composite risk score is {final_score}/100 with {len([f for f in factors if f.severity == 'critical'])} critical danger signs."
    elif final_score >= 30:
        tier = "MODERATE"
        color = "#f59e0b"
        badge = "Moderate Risk — Close ANM Surveillance"
        action = "Schedule follow-up review by Auxiliary Nurse Midwife (ANM) within 7 days. Monitor BP, Hb, and fetal wellness."
        summary = f"Composite risk score is {final_score}/100 with key warning indicators requiring prioritized surveillance."
    else:
        tier = "LOW"
        color = "#10b981"
        badge = "Low Risk — Routine Antenatal Care"
        action = "Continue standard MoHFW antenatal visit protocol, daily IFA/calcium supplementation, and nutrition counseling."
        summary = f"Composite risk score is {final_score}/100. Routine pregnancy progression with no active red flags."

    # Build Trajectory Points
    trajectories: list[TrajectoryPoint] = []
    for visit in past:
        trajectories.append(
            TrajectoryPoint(
                visit_number=visit.get("visit_number") or len(trajectories) + 1,
                gestational_weeks=visit.get("gestational_weeks"),
                bp_systolic=visit.get("bp_systolic"),
                bp_diastolic=visit.get("bp_diastolic"),
                weight_kg=visit.get("weight_kg"),
                hemoglobin=visit.get("hemoglobin"),
                created_at=visit.get("created_at"),
            )
        )

    # Add current visit point
    trajectories.append(
        TrajectoryPoint(
            visit_number=len(trajectories) + 1,
            gestational_weeks=weeks_val,
            bp_systolic=int(record.bp_systolic) if record.bp_systolic is not None else None,
            bp_diastolic=int(record.bp_diastolic) if record.bp_diastolic is not None else None,
            weight_kg=float(record.weight_kg) if record.weight_kg is not None else None,
            hemoglobin=float(record.hemoglobin) if record.hemoglobin is not None else None,
            risk_score=final_score,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    )

    return RiskAssessment(
        score=final_score,
        tier=tier,
        color=color,
        badge_label=badge,
        summary=summary,
        factors=factors,
        compliance=compliance,
        trajectories=trajectories,
        clinician_action=action,
    )
