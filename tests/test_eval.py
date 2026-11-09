from __future__ import annotations

import csv
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from eval.noise_mix import generate_synthetic_test_wav, mix_noise, read_pcm_wav
from eval.run_eval import count_critical_extraction_errors

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("target_snr", (15, 5))
def test_pink_noise_mixer_hits_requested_snr(target_snr: int) -> None:
    clean_wav = generate_synthetic_test_wav(
        duration_seconds=2.0,
        frequency_hz=330,
        amplitude=0.15,
    )
    clean = read_pcm_wav(clean_wav)
    mixed = mix_noise(clean, target_snr, seed=8675309)
    noise = mixed - clean
    measured = 10 * math.log10(
        float((clean @ clean) / (noise @ noise))
    )

    assert measured == pytest.approx(target_snr, abs=1e-10)
    assert (mix_noise(clean, target_snr, seed=8675309) == mixed).all()


def test_false_reassurance_and_false_alarm_are_counted_separately() -> None:
    expected = {
        "vaginal_bleeding": "present",
        "convulsions": "present",
        "severe_headache": "denied",
        "swelling": "denied",
    }
    actual = {
        "vaginal_bleeding": "not_mentioned",
        "convulsions": "denied",
        "severe_headache": "present",
        "swelling": "not_mentioned",
    }

    counts = count_critical_extraction_errors(expected, actual)

    assert counts == {
        "false_reassurance": 2,
        "expected_present": 2,
        "false_alarm": 1,
        "expected_denied": 2,
    }


def test_ground_truth_covers_languages_and_all_required_scenario_types() -> None:
    scenarios = json.loads(
        (PROJECT_ROOT / "eval" / "ground_truth" / "scenarios.json").read_text(
            encoding="utf-8"
        )
    )
    languages = {scenario["language"] for scenario in scenarios}
    rule_ids = {
        rule_id
        for scenario in scenarios
        for rule_id in scenario["expected_rule_ids"]
    }
    types = {scenario["type"] for scenario in scenarios}

    assert len(scenarios) >= 12
    assert languages == {"hi-IN", "mr-IN", "te-IN", "ta-IN", "ml-IN", "en-IN"}
    assert {f"RULE-HRP-0{i}" for i in range(1, 6)} <= rule_ids
    assert {"emergency_turn1", "silence_vs_denial", "early_stage_gate", "negation_trap", "self_correction"} <= types
    assert sum(bool(scenario["readback"] and scenario["readback"]["injected_error"]) for scenario in scenarios) >= 2


def test_run_eval_dry_run_writes_csv_report_and_demo_chart() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "eval.run_eval",
            "--dry-run",
            "--lang",
            "all",
            "--noise",
            "all",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    results_dir = PROJECT_ROOT / "eval" / "results"
    summary_path = results_dir / "metrics_summary.csv"
    breakdown_path = results_dir / "language_noise_breakdown.csv"
    report_path = results_dir / "evaluation_report.md"
    chart_path = results_dir / "demo_slide_chart.png"
    assert summary_path.is_file()
    assert breakdown_path.is_file()
    assert report_path.is_file()
    assert chart_path.is_file()
    assert chart_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

    with summary_path.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    assert any("False Reassurance" in row["metric"] for row in rows)
    assert any("Read-Back Catch Rate" in row["metric"] for row in rows)
    assert len(list(csv.DictReader(breakdown_path.open(encoding="utf-8")))) == 18
    report = report_path.read_text(encoding="utf-8")
    assert "Offline fixture run" in report
    assert "not measure recorded speech performance" in report
    assert "WER" in report and "CER" in report
