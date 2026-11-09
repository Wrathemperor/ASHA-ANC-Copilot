PRD: Voice ANC Home-Visit Copilot for ASHA Workers
Entry for the Great Indian AI Internship (Gnani.ai). Submission deadline: November 10, 2026. Status: draft v1.
1. Overview
ASHA workers record home visits in paper registers and cards while moving between households, often in noisy settings and in their own regional language. This project is a browser-based voice copilot that lets an ASHA worker speak a short, code-mixed summary of an antenatal care (ANC) home visit. The system turns it into a structured record, checks for missing mandatory safety questions, asks a short follow-up in her language, reads back key numbers for confirmation, and shows a clinician referral flag based on official MoHFW guidance.
It is a record-keeping and guideline-flagging tool. It never diagnoses, never assigns a PMSMA sticker, and never replaces clinical judgment.
2. Problem and opportunity
• Paper registers are slow to fill, and safety questions get skipped when the worker is tired or rushed.
• A worker who forgets to mention a danger sign (for example, blurred vision with raised BP) leaves no prompt for anyone to catch it.
• Voice is the natural interface for workers who are more comfortable speaking in Marathi, Hindi, Tamil, Telugu or Malayalam than typing.
• Gnani's stack (Prisma for speech-to-text, Evon for reasoning, Timbre for speech output) is built for exactly this kind of Indian-language, noisy-audio problem.
3. Goals and non-goals
Goals
1. Convert a 15-20 second code-mixed voice note into a correct structured ANC visit record.
2. Detect missing mandatory safety fields with deterministic code and ask a single targeted follow-up in the worker's language.
3. Surface a clear clinician referral or danger-sign flag, with the rule and source shown.
4. Never give false reassurance: unknown information stays unknown.
5. Demonstrate measured multilingual and noise performance across six languages.
Non-goals
• Diagnosis, treatment advice, or sticker assignment.
• HBNC (newborn) visits, other visit types, or other programs (roadmap only).
• Real phone-call telephony or streaming conversation.
• Storing audio or real patient data.
• Production deployment, user accounts, or sync with government portals.
4. Users
Primary user: an ASHA worker doing a pregnancy home visit, speaking Hindi, Marathi, Tamil, Telugu, Malayalam or English, often code-mixed, in a noisy environment, using a low-to-mid range phone browser.
Secondary user (demo and evaluation context): ANM, medical officer or reviewer who reads the structured record and the flag.
5. Scope
Antenatal care home visits only. One visit type, one schema, one rule set, six languages.
6. User flow
Step 1: Voice note and extraction. The worker taps a large mic button and speaks for 15-20 seconds. Prisma transcribes. If the transcript is empty, very short, low confidence (if exposed by the API), in an unsupported language, or inconsistent with the expected language, the app stops and asks her to repeat. It never guesses. Evon extracts values into a strict JSON schema. Every clinical field defaults to not_mentioned unless the transcript explicitly says present or denied.
Step 2: Deterministic gates (code only).
• Emergency bypass: if any critical danger sign is present (for example convulsions or heavy vaginal bleeding), skip follow-ups and show an urgent referral flag immediately.
• Gestational-weeks check: if weeks are not_mentioned, ask for weeks first, because stage-gated rules depend on it.
• Gap check: compute which mandatory fields for her stage are still not_mentioned and rank them by priority.
Step 3: Single-focus follow-up (maximum two turns). For the highest-priority gap, the system speaks one non-compound question from a fixed, pre-verified translation template via Timbre. She answers in about five seconds. The answer runs through the same schema extractor: it may fill any field that is still not_mentioned (including an unsolicited danger sign, for example reduced baby movement mentioned while answering about headache) but never overwrites a value locked in Turn 1. If it conflicts with a Turn 1 value, the conflict is shown on the read-back screen for confirmation instead of being applied silently. Emergency and flag rules re-run after every update. Gap priority is an explicit ordered list in rules.py, built from the official rules file, so when related checks compete (for example headache and blurred vision after raised BP with swelling) the top two gaps are asked by voice and the rest fall through to the Incomplete / Needs Verification banner, where she can optionally tap present or denied on screen.
Step 4: Read-back and final flag. Before locking the record, the system reads back the extracted numbers (BP, weeks) and she confirms or corrects by voice (one voice correction, parsed by a small numeric-only extraction; if that also fails, an on-screen tap-to-edit card opens, so read-back can never loop). The final screen shows the structured record, the referral flag with the triggering rule and its source, and an Incomplete / Needs Verification marker on any mandatory field still not_mentioned.
7. Functional requirements
ID
Requirement
Priority
FR-1
Browser push-to-talk recording, 15-20 s typical, hard cap 30 s
Must
FR-2
Transcription via Prisma with language selection or detection
Must
FR-3
Halt-and-repeat on empty, short, low-confidence, wrong-language, unsupported-language, unsuccessful (`not response.get("success")`) or truncated (`response.get("truncated") is True`) input
Must
FR-4
Evon extraction to strict JSON schema with tri-state values; invalid JSON handled by retry then halt
Must
FR-5
Rule engine in plain code: emergency bypass, stage gating, gap ranking, referral flags
Must
FR-6
Follow-up question from fixed translated templates, one symptom per question, spoken via Timbre; maximum two voice follow-ups chosen by the explicit priority order in rules.py; remaining gaps shown as Incomplete with optional tap chips
Must
FR-7
Follow-up answer runs through the same extractor: may fill any not_mentioned field, never overwrites Turn 1 values, conflicts go to read-back confirmation, emergency and flag rules re-run
Must
FR-8
Numeric read-back for BP and gestational weeks; one voice correction via numeric-only extraction, then on-screen tap-to-edit; no read-back loops
Must
FR-9
Final screen: record, flag with rule ID and source, Incomplete markers
Must
FR-10
Live register UI that fills as fields are extracted
Should
FR-11
Text fallback for TTS failure (show question as text)
Should
FR-12
Evaluation harness runnable from CLI, outputs metrics tables and charts
Must
FR-13
Language-selectable UI strings for the six languages
Could
8. Data schema (tri-state)
Every clinical symptom field takes one of: present, denied, not_mentioned. Numeric fields take a number or null (meaning not mentioned). Each extracted value stores the transcript span that supports it.
Core fields (final list to be confirmed against official documents):
• gestational_weeks (number or null)
• bp_systolic, bp_diastolic (numbers or null; may be reported from the ANM or the MCP card)
• swelling, severe_headache, blurred_vision, reduced_fetal_movement, vaginal_bleeding, convulsions, severe_abdominal_pain, fever, leaking_fluid (tri-state)
• anemia_or_low_hb_mentioned, ifa_tablets_taken, calcium_tablets_taken (tri-state)
• last_anc_visit (text or null)
A field is only ever denied if the speaker explicitly says so. Silence is never a denial.
9. Rule layer
• Rules are code, not prompts. Each rule has an ID, conditions on schema fields, an output flag (Urgent referral, Refer for evaluation, Incomplete), and a source citation.
• Rule content comes only from official documents (MCP card, Safe Motherhood Booklet, PMSMA operational framework, MoHFW ANC guidelines). Nothing is hard-coded from model memory.
• Output language is a referral flag, for example: "Possible high-risk indicators found: recommend referral for clinician evaluation." The app never shows a sticker color as a decision. The visual may echo the MCP card's Green/Red idea, labeled as a flag.
• Current official PMSMA sticker scheme is Green (no risk factor detected) and Red (high-risk pregnancy). Older Blue/Yellow stickers are not used in this product.
• Stage gating: age-dependent questions (for example fetal movement) apply only from the official gestational threshold. One source-backed threshold only. If weeks are unknown, treat age-gated fields as required.
10. Safety, ethics and privacy requirements
1. Fail safe: unknown stays unknown and stays flagged. Never default to "normal".
2. No diagnosis, no medication advice, no sticker assignment. State this on screen and in the write-up.
3. Human-in-the-loop: numeric read-back and an editable record before locking.
4. Every flag shows its rule ID and source.
5. Synthetic scripts and consenting volunteers only. No real patient data.
6. The app stores no audio. Do not claim anything about Gnani's server-side retention without checking their data policy.
7. No secrets in the repository. API keys live in environment variables.
11. Non-functional requirements
• Latency: each turn (speech in to speech out) targets under about 6 seconds on a normal connection. Measure and report actual numbers.
• Cost: credits are limited. Cache all TTS audio for fixed templates, use short clips in development, and add a per-session call counter.
• Reliability: every API call has a timeout, one retry, and a visible failure state.
• Compatibility: works in current mobile Chrome. Microphone permission handled clearly.
• Accessibility: large touch targets, high contrast, and text shown alongside speech.
12. Architecture
Browser (mic capture, register UI, audio playback) talks to a small backend (FastAPI or similar) that holds the API keys and orchestrates: Prisma, then Evon extraction, then the rule engine, then a template picker, then Timbre. The rule engine and schema validation are pure functions with unit tests. Evon is used only for extraction (and optionally paraphrase later). Question text comes from the template file. Audio is processed in memory (the browser recording is piped through ffmpeg stdin and stdout to the format and sample rate the Gnani docs require) and never written to disk in the app. Chrome's webm/opus pipes cleanly; Safari and iOS mp4 may need browser-side WAV recording instead, which the spike should test.
Exact endpoints, request formats, supported languages, rate limits and whether Evon is hosted or self-run must be taken from the Gnani documentation, not assumed.
13. Evaluation plan
Test set: about 50-60 synthetic clips across six languages, 8-10 scenarios each, with hand-written ground-truth JSON. Scenario types: normal, one danger sign present, explicit denial, not mentioned, emergency in turn one, numeric-heavy, negation traps, self-correction. Two to three consenting speakers per language where possible. Noise conditions: clean, about 15 dB SNR, about 5 dB SNR (programmatic mixing plus a few real-environment recordings).
Metrics, in priority order
1. Critical extraction errors: present read as denied or not_mentioned (false reassurance) and denied read as present (false alarm), reported separately.
2. Danger-sign flag recall on emergency and danger-sign scenarios, including misses.
3. Gap-check correctness: right field, right order.
4. Read-back catch rate on injected numeric errors.
5. Transcription quality: WER, plus CER for Marathi and the Dravidian languages, per language and noise level.
6. Latency per turn.
Report counts ("11 of 12") rather than inflated percentages, and state limitations plainly.
14. Demo specification (60 seconds)
1. 0-8 s: the problem (paper register, noisy visit) and the promise.
2. 8-25 s: worker speaks a messy code-mixed note; the live register fills.
3. 25-40 s: the system notices a missing danger-sign check and asks in her language.
4. 40-52 s: she answers; read-back of numbers; flag appears with rule and source.
5. 52-60 s: one slide with multilingual accuracy chart and the line "flags and records, never diagnoses".
Use real speech, not scripted shortcuts. Captions on, language labels visible. Post on LinkedIn and X by November 4-5, tagging the official account with the required hashtags, and engage genuinely. No bots or paid engagement.
15. Timeline (October 29 to November 10)
• Oct 29-31: read docs, API key, spike: record clips, test Prisma, check Evon access, bare speech-in to speech-out loop. Decide scope is feasible.
• Nov 1-3: schema, rule engine with unit tests, extraction prompt, templates in six languages, UI skeleton.
• Nov 3-4: full two-turn loop working end to end, read-back step, failure states.
• Nov 4-5: record and post the demo (hard target).
• Nov 5-8: evaluation harness and results, README, write-up.
• Nov 8-9: submit, with buffer. Deadline Nov 10 is final.
16. Risks and mitigations
Risk
Mitigation
Prisma weak in a language
Report it honestly, narrow the demo language, keep the multilingual chart
Evon access or latency
Check docs on day one; keep extraction prompt small; cache and timeouts
Timbre lacks a language
Show question as text and use the supported languages in the demo
Rule content wrong
Source every rule from official documents; you verify; cite IDs on screen
Credits run out
Caching, short clips, session call counter
Scope creep
ANC only; HBNC stays roadmap
Late posting hurts engagement
Demo posted by Nov 5
17. Items to verify before building
• Model names and versions, supported languages, confidence outputs, streaming, rate limits and data-retention policy in the Gnani documentation.
• The official danger-sign list and exact categories (MCP card, Safe Motherhood Booklet, PMSMA framework), including whether severe abdominal pain is listed.
• The BP threshold and the stage threshold for fetal movement, from official ANC guidance.
• Competition rules on team size, required demo format and submission fields.
18. Roadmap (write-up only)
HBNC visit type via config-driven schemas and rules, real telephony for basic phones, offline-first mode, sync with the ANMOL or RCH portal workflow, clinician review dashboard.
