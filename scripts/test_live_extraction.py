"""[LIVE] Compare Evon extraction with synthetic sample ground-truth records.

This script makes billable Evon calls. Run it manually only when approved.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.extraction import extract_visit_record
from app.gnani.evon import EvonClient


def main() -> None:
    sample_path = Path(__file__).resolve().parents[1] / "eval" / "extraction_samples.json"
    samples = json.loads(sample_path.read_text(encoding="utf-8"))
    failures: list[str] = []

    for sample in samples:
        record = extract_visit_record(
            sample["transcript"],
            language=sample["language"],
            evon_client=EvonClient(),
        )
        actual = record.__dict__
        mismatches = {
            field_name: {"expected": expected, "actual": actual[field_name]}
            for field_name, expected in sample["expected"].items()
            if actual[field_name] != expected
        }
        status = "PASS" if not mismatches else "FAIL"
        print(f'{status} {sample["id"]}')
        if mismatches:
            failures.append(f'{sample["id"]}: {json.dumps(mismatches, ensure_ascii=False)}')

    print(f"{len(samples) - len(failures)} of {len(samples)} samples matched.")
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
