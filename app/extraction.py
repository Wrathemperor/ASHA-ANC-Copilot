"""Evon-backed structured extraction with strict validation and bounded repair."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from app.gnani.gemini import DEFAULT_GEMINI_MODEL, GeminiClient
from app.schema import ANCVisitRecord


class ExtractionValidationError(Exception):
    """Raised when extracted data cannot be validated safely."""


class NumericCorrectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: bool
    bp_systolic: int | None = None
    bp_diastolic: int | None = None
    gestational_weeks: int | None = None
    evidence: str = ""


_RECORD_ADAPTER = TypeAdapter(ANCVisitRecord)
_THINK_PATTERN = re.compile(r"<think>.*?</think>", flags=re.IGNORECASE | re.DOTALL)

_EXTRACTION_SYSTEM_PROMPT = f"""You are a strict structured-data extractor for an antenatal home visit.
Target model: {DEFAULT_GEMINI_MODEL}.
Extract only facts explicitly supported by the transcript. Do not diagnose, advise, assign a risk level, or infer missing facts.
Return exactly one JSON object matching this shape, with no markdown or additional keys:
{{
  "gestational_weeks": null,
  "bp_systolic": null,
  "bp_diastolic": null,
  "swelling": "not_mentioned",
  "severe_headache": "not_mentioned",
  "blurred_vision": "not_mentioned",
  "reduced_fetal_movement": "not_mentioned",
  "vaginal_bleeding": "not_mentioned",
  "convulsions": "not_mentioned",
  "severe_abdominal_pain": "not_mentioned",
  "fever": "not_mentioned",
  "leaking_fluid": "not_mentioned",
  "anemia_or_low_hb_mentioned": "not_mentioned",
  "ifa_tablets_taken": "not_mentioned",
  "calcium_tablets_taken": "not_mentioned",
  "last_anc_visit": null,
  "evidence_spans": {{}},
  "conflicts": []
}}
Rules:
- Default EVERY clinical symptom to "not_mentioned" unless it is explicitly stated.
- Use "present" only when the speaker confirms a symptom; use "denied" only when explicitly negated.
- Silence is never denial. Negation applies only to the symptom actually negated.
- Normal baby movement (for example "movement normal hai" or "halchal theek hai") explicitly means reduced_fetal_movement="denied".
- Resolve clear self-corrections in favor of the corrected value (for example "26 weeks... nahi sorry 28 weeks" means gestational_weeks=28).
- Resolve clear blood-pressure self-corrections in favor of the corrected reading (for example "BP 150 by 100, sorry 140 by 90" means systolic=140 and diastolic=90).
- Extract Indian number words and colloquial BP phrasing, including "140 by 90", "140 over 90", and "ek sau chalis aur nabbe".
- Numbers must be JSON numbers, or null when absent. Text fields are strings or null.
- evidence_spans maps each extracted field name to the exact verbatim transcript snippet that supports its value. Do not paraphrase evidence.
- The conflicts array is empty for initial extraction.
The transcript may be code-mixed. Language hint: {{language}}.
"""

_NUMERIC_SYSTEM_PROMPT = f"""You are a numeric-only read-back confirmation parser for model {DEFAULT_GEMINI_MODEL}.
Return exactly one JSON object matching:
{{"confirmed": false, "bp_systolic": null, "bp_diastolic": null, "gestational_weeks": null, "evidence": ""}}
Do not infer any number or alter clinical symptoms. `confirmed` is true only for an unambiguous affirmative confirmation with no correction, such as "haan sahi hai", "yes correct", "बरोबर आहे", or "అవును".
For an explicit numeric correction, set confirmed=false and return only the corrected numbers actually spoken. For example, "nahi BP 130 over 80 hai" corrects systolic=130 and diastolic=80; "weeks 30 nahi 32 hai" corrects gestational_weeks=32. Do not carry unchanged displayed values into the result.
Put the exact supporting words from the transcript in evidence. For unclear or unrelated speech, confirmed=false and leave all numbers null.
Language hint: {{language}}.
"""


def _client_or_default(evon_client: Any | None) -> Any:
    return evon_client if evon_client is not None else GeminiClient()


def _decode_json_response(response: Any) -> Any:
    if isinstance(response, str):
        cleaned = _THINK_PATTERN.sub("", response).strip()
        return json.loads(cleaned)
    if isinstance(response, dict):
        return response
    raise TypeError("Evon response must be a JSON object or JSON string.")


def _transcript_prompt(transcript: str, language: str) -> str:
    return f"Language: {language}\nTranscript (extract only from this exact text):\n{transcript}"


def extract_visit_record(
    transcript: str,
    language: str = "en-IN",
    evon_client: Any | None = None,
) -> ANCVisitRecord:
    """Extract and validate one visit record, with one targeted JSON repair attempt."""
    if not transcript.strip():
        raise ExtractionValidationError("Transcript is empty; repeat the visit summary.")

    client = _client_or_default(evon_client)
    system_prompt = _EXTRACTION_SYSTEM_PROMPT.replace("{language}", language)
    user_prompt = _transcript_prompt(transcript, language)
    last_error: Exception | None = None

    for attempt in range(2):
        prompt = system_prompt
        if attempt:
            prompt += (
                "\nREPAIR ATTEMPT: The previous response could not be decoded or validated. "
                "Return a corrected JSON object matching the exact schema above. "
                "Do not add commentary and do not guess unsupported values."
            )
        try:
            response = client.complete_json(prompt, user_prompt)
            data = _decode_json_response(response)
            return _RECORD_ADAPTER.validate_python(data)
        except (json.JSONDecodeError, TypeError, ValidationError) as error:
            last_error = error

    raise ExtractionValidationError(
        "Evon extraction failed JSON or schema validation after one repair attempt."
    ) from last_error


def extract_numeric_correction(
    transcript: str,
    current_bp_sys: int | None,
    current_bp_dia: int | None,
    current_weeks: int | None,
    language: str = "en-IN",
    evon_client: Any | None = None,
) -> NumericCorrectionResult:
    """Extract an affirmative read-back or corrected numeric values only."""
    if not transcript.strip():
        raise ExtractionValidationError("Read-back response is empty.")

    client = _client_or_default(evon_client)
    system_prompt = _NUMERIC_SYSTEM_PROMPT.replace("{language}", language)
    user_prompt = (
        f"Current read-back values: bp_systolic={current_bp_sys}, "
        f"bp_diastolic={current_bp_dia}, gestational_weeks={current_weeks}.\n"
        f"Worker response (use only corrections explicitly stated here):\n{transcript}"
    )
    try:
        response = client.complete_json(system_prompt, user_prompt)
        return NumericCorrectionResult.model_validate(_decode_json_response(response))
    except (json.JSONDecodeError, TypeError, ValidationError) as error:
        raise ExtractionValidationError(
            "Read-back response could not be decoded or validated."
        ) from error
