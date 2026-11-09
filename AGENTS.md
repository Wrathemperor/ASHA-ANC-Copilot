# Project: Voice ANC Home-Visit Copilot for ASHA workers

## What this is
A browser app. An ASHA worker speaks a short code-mixed antenatal care (ANC)
visit summary. We transcribe (Gnani Prisma), extract structured fields
(Gnani Evon), compute missing safety fields and referral flags with plain
code, ask ONE follow-up by voice (Gnani Timbre), read back key numbers for
confirmation, and show a clinician referral flag.
Full requirements: docs/PRD.md. Read it before any task.

## Hard safety rules (never violate)
1. Tri-state clinical fields: present / denied / not_mentioned. Default is
   not_mentioned. Never turn silence into denied or normal.
2. The app never diagnoses, never gives treatment advice, never assigns a
   PMSMA sticker. It outputs a "clinician referral flag" only.
3. All flag logic lives in app/rules.py as pure functions. The LLM only
   extracts values. The LLM never decides a flag.
4. Every rule has an ID and a source from docs/official_rules.md. Do not add
   or change clinical thresholds from memory. If a rule is not in
   docs/official_rules.md, ask the user. Do not invent it.
5. Follow-up questions come from app/templates/questions.json only. Do not
   generate or translate clinical questions yourself.
6. On empty, short, low-confidence, wrong-language or unsupported-language
   input: stop and ask the worker to repeat. Never guess.
7. Store no audio. Process in memory (pipe through ffmpeg stdin/stdout, no temp files).
   No real patient data anywhere.
8. Follow-up answers go through the same extractor. They may fill any not_mentioned
   field (including unsolicited danger signs) but never overwrite a value locked in
   Turn 1. Conflicts are shown on the read-back screen for confirmation. Re-run the
   emergency and flag rules after every update.
9. Follow-up priority order is defined in app/rules.py (from official_rules.md). Max two
   voice follow-ups. Remaining gaps stay visible as Incomplete / Needs Verification.
10. Read-back allows one voice correction (numeric-only extraction), then falls back to
   an on-screen edit card. Never loop.

## Gnani API rules
- The only source of truth for endpoints, params and languages is
  docs/gnani_api_notes.md. If something is missing there, STOP and ask.
  Never guess an endpoint, field name or model name.
- API calls cost credits. Always: timeout, one retry, a per-session call
  counter, and caching of Timbre output for fixed templates.
- Never print or commit keys. Read them from environment variables.
- In tests, mock all Gnani calls. Real calls only in scripts marked [LIVE].

## Engineering rules
- Python 3.11, FastAPI, Pydantic, pytest. Frontend is vanilla JS, no build.
- Work in small steps. After each step run tests and show the results.
- Write tests before or with every change to rules.py and session.py.
- Keep functions small and typed. No dead code, no unused dependencies.
- Do not refactor files outside the task. Do not rename files without asking.
- Before large changes, state the plan in 5-10 lines and wait for approval.

## Commands
- Run app: uvicorn app.main:app --reload
- Tests: pytest -q
- Eval: python eval/run_eval.py --lang all --noise all

## Definition of done for any task
Tests pass, no secrets in diff, safety rules above still hold, and a short
summary of what changed and what is untested.