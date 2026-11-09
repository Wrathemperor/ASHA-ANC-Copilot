"""End-to-end test: Pass transcript through Gemini extraction and evaluate rules."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from app.extraction import extract_visit_record
from app.gnani.gemini import GeminiClient
from app.rules import evaluate_visit

TRANSCRIPT = (
    "सुनीता देवी का ANC home visit किया, अभी उनकी... 32 weeks की pregnancy चल रही है। "
    "कल checkup में BP 145/95 आया था। और दोनों पैरों में काफ़ी swelling है। "
    "vaginal bleeding बिल्कुल नहीं है, बुखार नहीं है। और baby का movement normal है। "
    "IFA और calcium की गोली रोज़ ले रही है।"
)


def main() -> None:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("ERROR: GEMINI_API_KEY is not set in .env")
        print("Get a free key at: https://aistudio.google.com/app/apikey")
        sys.exit(1)

    print("=== Input Transcript (from Prisma STT) ===")
    print(TRANSCRIPT)
    print()

    print("Running extraction with Gemini Flash...")
    client = GeminiClient()
    record = extract_visit_record(TRANSCRIPT, language="hi-IN", evon_client=client)

    print("=== Extracted Visit Record ===")
    from dataclasses import asdict
    print(json.dumps(asdict(record), indent=2, ensure_ascii=False))
    print()

    print("=== Evaluating Clinical Rules ===")
    evaluation = evaluate_visit(record)
    print(f"Emergency Bypass: {evaluation.emergency_bypass}")
    print(f"Referral Flag   : {evaluation.flag}")
    print(f"Triggered Rules : {evaluation.rule_ids}")
    print(f"Top Gaps        : {evaluation.top_gaps}")
    print(f"Incomplete Gaps : {evaluation.incomplete_fields}")


if __name__ == "__main__":
    main()
