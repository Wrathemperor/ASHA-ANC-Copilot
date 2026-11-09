# Progress Log

## Direct REST Integration and Local API Verification

- Added direct `httpx` REST fallback for Prisma and Timbre when the optional Gnani SDK is not installed; SDK-backed behavior remains available.
- Prisma REST sends the official `keyterms` field, ANC topic, and previous question context. Timbre REST requests cached 16 kHz WAV output.
- Added mocked REST-client tests; all tests remain offline. Added a user-run API verification script entry to the README; live checks are explicitly prompted and Prisma is opt-in by sample WAV.
- Removed `gnani` from required dependencies because REST works without the proprietary SDK distribution; existing Evon Bearer auth is unchanged.
- Validation: full suite passes (`70 passed`); direct verifier `--help` works without making API calls; `git diff --check` passes. One existing Starlette/httpx deprecation warning remains. No hosted API calls were made.

## Hosted Cloud Integration and Offline Laptop Demo

- Added opt-in `DEMO_OFFLINE_MODE=1` loading from process environment or `.env`; dotenv is now an explicit runtime dependency, with shell environment values retaining precedence.
- Added fixture-backed offline Prisma/Evon providers and deterministic 16 kHz WAV tone output for Timbre. The server health response and browser UI identify this mode; fixture transcripts are selected by audio-content hash and are explicitly not speech recognition.
- Updated the cloud Evon client to send its configured key as a Bearer authorization value; empty `.env` endpoint/model entries now fall back to documented defaults. Prisma/Timbre continue using the documented hosted SDK when available.
- Added an audio upload control for MP3/WAV, decoding in browser memory, mono downmixing/resampling to 16 kHz PCM WAV, and routing through the same session endpoint flow as microphone audio.
- Updated `scripts/live_spike.py` to use the validated extractor and deterministic rules, and to work with fixture mode without credentials or network access.
- Updated README quickstart, hosted-vs-offline behavior, model-weight non-use, safety guardrails, and fixture benchmark caveats.
- Validation: full suite passes (`63 passed`); `node --check app\static\app.js` passes; `git diff --check` passes. One existing Starlette/httpx deprecation warning remains. No hosted API calls or model downloads were made.

## Final Documentation and Dependency Manifest

- Added the repository README with the product scope, clinical safety disclaimer, Mermaid architecture/session flow, implemented rule guardrails, quickstart commands, evaluation methodology, complete generated report tables, and chart link.
- Documented the official emergency rules accurately: leaking fluid is covered by `RULE-HRP-05`, not the emergency bypass. Clarified that benchmark scores and latencies are from deterministic fixtures, not measured acoustic performance.
- Explicitly listed runtime, evaluation, and test dependencies in `requirements.txt`, including Pydantic and `gnani==0.9.0` per the Gnani API notes. The notes do not provide a private package index or wheel URL.
- Validation: full offline suite passes (`59 passed`); `git diff --check` passes. One existing Starlette/httpx deprecation warning remains.

## Phase 6 — Offline-Cached Evaluation Harness and Demo Chart

- Added 20 synthetic ground-truth scenarios covering all six supported languages, danger-sign rules, emergency bypasses, silence/denial distinctions, stage gates, negation, self-correction, and read-back cases; documented matching recording scripts.
- Added reproducible 16 kHz PCM WAV utilities for clean, 15 dB, and 5 dB pink-noise variants, plus a synthetic WAV generator for fixture-only runs.
- Added `eval/run_eval.py` with explicit offline `--dry-run` and opt-in `--live` modes, Prisma/Evon response caching, language/noise selectors, and the six PRD metrics with raw counts and rates.
- Added CSV and Markdown reports plus a high-DPI 16:9 demo chart with the required non-diagnostic footer. Dry-run transcripts and simulated latencies are clearly identified as fixtures, not measured speech or service performance.
- Added evaluation tests for measured SNR, separate false-reassurance/false-alarm counting, fixture coverage, and end-to-end artifact generation. No live API evaluation was run.
- Full suite passes: `59 passed` (`.venv\Scripts\python.exe -m pytest -q`).

## 2026-10-30

- Replaced the audio-check placeholder with a mobile-first ASHA register UI: language/session indicators, persistent disclaimer, 30-second push-to-talk WAV capture, follow-up/read-back playback, tri-state symptom/evidence matrix, missing-field chips, numeric edit controls, explicit conflict choices, and final clinician referral information.
- Added vanilla Web Audio downsampling/PCM WAV encoding and integration with all session endpoints; audio is held in memory and UI retries Turn 1 after `HALT_REPEAT`.
- Mounted the static UI at `/` and added static asset plus full start → Turn 1 → follow-up → read-back API integration tests.
- Kept final status wording aligned with backend rules: the interface does not claim routine/no-risk care when unknown information remains, and conflict finalization requires an explicit Turn 1/Turn 2 choice.
- Verified responsive layout at a 360px browser viewport, minimum 48px button targets, and successful local page serving. Browser testing did not submit any microphone recording.
- Full backend test suite passes: `54 passed` (`.venv\Scripts\python.exe -m pytest -q`). `node --check app\static\app.js` and `git diff --check` also pass.

- Implemented the in-memory two-turn session state machine, including Prisma transcription, Halt-and-Repeat handling, extraction/evaluation, emergency bypass, capped follow-ups, conflict tracking, numeric read-back correction, manual edit locking, and base64 cached Timbre responses.
- Wired session start, turn 1, follow-up, read-back, manual edit, and session retrieval API routes; upload size bounds and supported language validation are enforced.
- Added offline state-machine and API tests for normal completion, emergency bypass, unsolicited Turn 2 emergencies, short input, conflict preservation, the single numeric correction, the two-follow-up cap, missing reviewed question templates, TTS text fallback, and route integration.
- For gaps without a pre-reviewed question in `questions.json` (currently convulsions and severe abdominal pain), the session safely requests manual edit instead of generating clinical wording.
- Full test suite passes: `51 passed` (`.venv\Scripts\python.exe -m pytest -q`).

- Added `app/extraction.py` with structured ANC extraction, explicit tri-state/evidence prompting, one targeted JSON/schema repair attempt, and numeric-only read-back confirmation/correction parsing.
- Added mocked extraction tests covering normal explicit denials, safety gaps, negation, normal movement, self-corrections, Hindi/English and Marathi code-mixing, think-tag removal, repair/fail-safe behavior, and affirmative/numeric read-back responses.
- Added synthetic ground-truth samples and `[LIVE]` `scripts/test_live_extraction.py`; live calls were not run.
- Kept Evon transport retries limited to transport/request failures so malformed JSON can be repaired by extraction with the required targeted prompt.
- Full test suite passes: `38 passed` (`.venv\Scripts\python.exe -m pytest -q`).

- Implemented the tri-state ANC visit schema, evidence spans, and safe Turn 2 merging. Unset values can be filled, while differing values locked in Turn 1 are retained and captured as read-back conflicts.
- Added a pure deterministic rule engine with emergency bypass, stage-gated fetal-movement checks, documented gap ordering, promoted headache/vision gaps, clinician referral flags, and official source citations.
- Aligned `STAGE-GATE-01` to 20 weeks per the Phase 2 requirement; gestational weeks remain the first prompt when absent.
- Added schema and rule-engine unit tests for defaults, conflicts, bypass, priority, and stage gates.
- Full test suite passes: `19 passed` (`.venv\Scripts\python.exe -m pytest -q`). The standalone `pytest.exe` resolved to the global Python installation, so validation used the project virtual environment directly.

- Added shared Gnani client base with single-key loading, bounded one-retry policy, typed errors, and `.cache/api_usage.json` accounting.
- Added Prisma `transcribe_bytes` wrapper with fixed ANC keywords, topic, `prisma-v3.0`, and `format="transcribe"`.
- Added Timbre v2.5 wrapper with Nalini default and SHA-256 `.cache/tts/` caching.
- Added Evon OpenAI-compatible `httpx` wrapper with configured model, non-thinking payload, and `<think>` stripping.
- Added mocked unit tests and `[LIVE]` manual spike script. Live calls were not executed.
- Test suite passes: `7 passed`. Added pytest configuration to scope collection to `tests/` and avoid unwritable cache directories.
