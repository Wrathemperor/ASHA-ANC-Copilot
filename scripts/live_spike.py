"""Send one clip through Prisma, Evon, deterministic rules, and Timbre.

Live calls can incur credits. With DEMO_OFFLINE_MODE=1, use synthetic fixtures
and local tone output instead; no audio is sent to a service.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from app.extraction import extract_visit_record
from app.gnani.demo import demo_offline_enabled
from app.gnani.evon import EvonClient
from app.gnani.prisma import PrismaClient
from app.gnani.timbre import TimbreClient
from app.rules import evaluate_visit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--language", default="en-IN")
    args = parser.parse_args()
    started = time.perf_counter()
    transcription = PrismaClient().transcribe(args.audio.read_bytes(), args.language)
    print("prisma_seconds", round(time.perf_counter() - started, 3))
    transcript = transcription.get("transcript", "")
    started = time.perf_counter()
    record = extract_visit_record(transcript, language=args.language, evon_client=EvonClient())
    evaluation = evaluate_visit(record)
    print("evon_seconds", round(time.perf_counter() - started, 3))
    started = time.perf_counter()
    audio = TimbreClient().synthesize("Test question.", args.language)
    print("timbre_seconds", round(time.perf_counter() - started, 3), "bytes", len(audio))
    print(
        json.dumps(
            {
                "mode": "offline_fixture" if demo_offline_enabled() else "hosted_api",
                "transcript": transcript,
                "record": asdict(record),
                "evaluation": asdict(evaluation),
                "timbre_audio_bytes": len(audio),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
