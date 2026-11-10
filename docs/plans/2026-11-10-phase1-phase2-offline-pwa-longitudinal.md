# Phase 1 & 2: Offline-First PWA and Longitudinal Patient Records Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform the ASHA ANC Copilot into an end-to-end, field-ready clinical copilot with offline-first PWA caching and IndexedDB queueing (Phase 1), plus persistent SQLite database storage, RCH-ID-based patient profiles, longitudinal vitals trajectory rules, and printable referral slips (Phase 2).

**Architecture:**
- **Phase 1 (Offline PWA):** Standard Web App Manifest (`manifest.json`), service worker (`service-worker.js`) caching the application shell, and client-side `IndexedDB` queueing for audio notes when offline with an auto-sync engine when connectivity resumes.
- **Phase 2 (Database & Longitudinal ANC):** Standard Python `sqlite3` persistence (`app/db.py`) storing patients (`rch_id`, name, age, village, EDD) and multi-visit longitudinal records. `app/rules.py` extended with longitudinal trajectory rules (`RULE-LONG-01` for BP jumps ≥30/15 mmHg, `RULE-LONG-02` for rapid weight gain, `RULE-LONG-03` for Hb drop). Top rail in UI gains a patient selector and longitudinal timeline chip view, plus a printable clinical referral slip modal.

**Tech Stack:**
- Frontend: Vanilla JavaScript, Service Workers, IndexedDB, CSS3, HTML5 PWA Manifest.
- Backend: Python 3.11/3.13, FastAPI, SQLite3 (`app/db.py`), Pydantic v2.
- Testing: Pytest with mocked fixtures and in-memory test database.

---

### Task 1: Persistent SQLite Database Layer (`app/db.py`)

**Files:**
- Create: `app/db.py`
- Test: `tests/test_db.py`

**Step 1: Write the failing tests for Database Layer**
Cover:
- Database initialization and schema creation (`init_db`).
- Creating a patient with unique `rch_id` and fetching by ID.
- Listing patients with search by name/RCH ID.
- Saving an ANC visit linked to a patient and session.
- Retrieving longitudinal visit history ordered by gestational age / visit date.

**Step 2: Run test to verify it fails**
Run: `pytest tests/test_db.py -v`
Expected: FAIL (module `app.db` does not exist).

**Step 3: Write minimal implementation in `app/db.py`**
- Implement `init_db(db_path: Path | str | None = None)`.
- Create tables: `patients` and `visits`.
- Implement `create_patient`, `get_patient_by_rch`, `list_patients`, `save_patient_visit`, `get_patient_visits`.

**Step 4: Run test to verify it passes**
Run: `pytest tests/test_db.py -v`
Expected: PASS (all DB tests pass).

---

### Task 2: Longitudinal Trajectory Rules in `app/rules.py`

**Files:**
- Modify: `app/rules.py`
- Test: `tests/test_rules.py`

**Step 1: Write failing tests in `tests/test_rules.py`**
Test cases:
- `test_longitudinal_bp_surge_triggers_referral`: baseline BP 100/60 at visit 1, current BP 132/80 at visit 2 (delta systolic +32 >= 30) -> triggers `RULE-LONG-01` and `CLINICIAN_REFERRAL` even though absolute BP < 140/90.
- `test_longitudinal_excessive_weight_gain`: weight gain > 2.0 kg in under 4 weeks -> triggers `RULE-LONG-02`.
- `test_longitudinal_severe_hemoglobin_drop`: Hb drops from 11.5 g/dL to 9.0 g/dL (drop 2.5 g/dL >= 2.0) -> triggers `RULE-LONG-03`.
- `test_longitudinal_no_previous_visits_maintains_standard_rules`: first visit behaves identically to baseline rules.

**Step 2: Run test to verify it fails**
Run: `pytest tests/test_rules.py -k longitudinal -v`
Expected: FAIL.

**Step 3: Implement longitudinal rules in `app/rules.py`**
- Add dataclass/dict parameter `previous_visits: list[dict[str, Any]] | None = None` to `evaluate_visit`.
- Implement `_longitudinal_rule_ids(record, previous_visits)`:
  - Check delta systolic >= 30 or delta diastolic >= 15 (`RULE-LONG-01`).
  - Check weight rate > 2.0 kg / month (`RULE-LONG-02`).
  - Check delta Hb >= 2.0 or current Hb < 7.0 (`RULE-LONG-03`).
- Merge longitudinal rule IDs into `rule_ids` and evaluate `CLINICIAN_REFERRAL`.

**Step 4: Run test to verify it passes**
Run: `pytest tests/test_rules.py -v`
Expected: PASS.

---

### Task 3: Backend API Endpoints for Patients and Referral Slips (`app/main.py`)

**Files:**
- Modify: `app/main.py`
- Modify: `app/session.py`
- Test: `tests/test_patient_api.py`

**Step 1: Write failing tests in `tests/test_patient_api.py`**
- Test `GET /api/patients` returns seed/registered patients.
- Test `POST /api/patients` creates or returns existing patient.
- Test `GET /api/patients/{rch_id}/history` returns longitudinal visit cards.
- Test `POST /api/session/{session_id}/link-patient` links patient to session and re-runs evaluation with longitudinal history.
- Test `GET /api/session/{session_id}/referral-slip` generates structured referral summary with QR code payload string.

**Step 2: Run test to verify it fails**
Run: `pytest tests/test_patient_api.py -v`
Expected: FAIL (endpoints 404).

**Step 3: Implement endpoints in `app/main.py` & session updates**
- Add patient endpoints to FastAPI app.
- Wire database initialization on application startup.
- Update `SessionManager` to accept optional `patient_id` or `rch_id`, fetch past visits from DB, and pass to `evaluate_visit`.
- Provide referral slip generator endpoint.

**Step 4: Run test to verify it passes**
Run: `pytest tests/test_patient_api.py -v`
Expected: PASS.

---

### Task 4: Offline-First PWA Setup (`manifest.json` & `service-worker.js`)

**Files:**
- Create: `app/static/manifest.json`
- Create: `app/static/service-worker.js`
- Create: `app/static/icons/icon-192.svg` & `app/static/icons/icon-512.svg`
- Modify: `app/static/index.html`

**Step 1: Add PWA Manifest and Icons**
- Define `name: "ASHA ANC Home-Visit Copilot"`, `short_name: "ANC Copilot"`.
- Clean medical cross/heart icon SVG.
- Service worker caching core assets: `/`, `/styles.css`, `/app.js`, `/manifest.json`.

**Step 2: Implement Service Worker and Offline Network Handling**
- Cache-first strategy for static assets.
- Network-first with fallback for API status checks.

**Step 3: Verify static files in test**
- Add test in `tests/test_main.py` ensuring `manifest.json` and `service-worker.js` are served with proper MIME types.

---

### Task 5: Frontline Offline IndexedDB Queue & Patient UI Integration

**Files:**
- Modify: `app/static/index.html`
- Modify: `app/static/styles.css`
- Modify: `app/static/app.js`

**Step 1: Add Patient Selector & Longitudinal Rail**
- Add RCH ID search / patient selector to top bar.
- Display mother details chip: `Name`, `Age`, `Village`, `EDD`, `Visit #`.
- Show mini-timeline of past visits: e.g. `Visit 1 (12 wks): 110/70 mmHg, 48 kg`.

**Step 2: Implement IndexedDB Offline Queue in `app.js`**
- Initialize `indexedDB` object store `anc_offline_queue`.
- Detect `navigator.onLine` and `offline` events.
- Display emerald "Online" pill vs amber "Offline Mode (X queued visits)" pill.
- When offline, audio recordings are queued into IndexedDB.
- Add "Sync Queue" button to process queued visits when back online.

**Step 3: Implement Printable Referral Slip Modal**
- Clean printable pass with:
  - Mother's Name, RCH ID, Age, Village, Gestational Age.
  - Critical Referral Category (`URGENT_REFERRAL` / `CLINICIAN_REFERRAL`).
  - Active Danger Signs & Triggered Rule IDs.
  - Verbatim Evidence Spans.
  - Formatted for direct browser print / PDF download (`window.print()`).

---

### Task 6: Full Integration Test & Verification

**Files:**
- Run: Full test suite (`pytest -v`)
- Verify all 70+ tests pass with zero regressions.
- Test offline demo mode, database persistence, and longitudinal rules.
