"""Run offline-fixture or explicitly authorized live ANC evaluation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import jiwer
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from app.extraction import extract_numeric_correction, extract_visit_record
from app.gnani.evon import DEFAULT_MODEL, EvonClient
from app.gnani.prisma import PrismaClient
from app.gnani.timbre import TimbreClient
from app.rules import evaluate_visit
from app.schema import ANCVisitRecord
from eval.noise_mix import NOISE_LEVELS, generate_synthetic_test_wav, noise_variants

LANGUAGES = ("hi-IN", "mr-IN", "te-IN", "ta-IN", "ml-IN", "en-IN")
NOISE_ARGUMENTS = ("all", "clean", "15dB", "5dB")
PROMPT_VERSION = "anc-eval-extraction-v1"
PRISMA_MODEL = "prisma-v3.0"
_TRI_STATE_FIELDS = (
    "swelling",
    "severe_headache",
    "blurred_vision",
    "reduced_fetal_movement",
    "vaginal_bleeding",
    "convulsions",
    "severe_abdominal_pain",
    "fever",
    "leaking_fluid",
    "anemia_or_low_hb_mentioned",
    "ifa_tablets_taken",
    "calcium_tablets_taken",
)


def count_critical_extraction_errors(
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> dict[str, int]:
    """Count false reassurance and false alarm without conflating directions."""
    false_reassurance = 0
    expected_present = 0
    false_alarm = 0
    expected_denied = 0
    for field_name in _TRI_STATE_FIELDS:
        expected_value = expected.get(field_name, "not_mentioned")
        actual_value = actual.get(field_name, "not_mentioned")
        if expected_value == "present":
            expected_present += 1
            if actual_value in {"denied", "not_mentioned"}:
                false_reassurance += 1
        elif expected_value == "denied":
            expected_denied += 1
            if actual_value == "present":
                false_alarm += 1
    return {
        "false_reassurance": false_reassurance,
        "expected_present": expected_present,
        "false_alarm": false_alarm,
        "expected_denied": expected_denied,
    }


def _edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for ref_index, ref_token in enumerate(reference, start=1):
        current = [ref_index]
        for hyp_index, hyp_token in enumerate(hypothesis, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[hyp_index] + 1,
                    previous[hyp_index - 1] + (ref_token != hyp_token),
                )
            )
        previous = current
    return previous[-1]


def _jsonable_record(record: ANCVisitRecord) -> dict[str, Any]:
    return asdict(record)


def _scenario_record(scenario: dict[str, Any]) -> ANCVisitRecord:
    return ANCVisitRecord(**scenario["expected_record"])


class FixtureEvonClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        return self.response


class EvalCache:
    """Persist JSON-compatible service outputs without storing API credentials."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir

    @staticmethod
    def key(audio_bytes: bytes, model: str, prompt_version: str) -> str:
        digest = hashlib.sha256()
        digest.update(audio_bytes)
        digest.update(model.encode("utf-8"))
        digest.update(prompt_version.encode("utf-8"))
        return digest.hexdigest()

    def read(self, service: str, audio_bytes: bytes, model: str, prompt_version: str) -> Any | None:
        key = self.key(audio_bytes, model, prompt_version)
        cache_path = self.cache_dir / service / f"{key}.json"
        if not cache_path.exists():
            return None
        return json.loads(cache_path.read_text(encoding="utf-8"))

    def write(self, service: str, audio_bytes: bytes, model: str, prompt_version: str, value: Any) -> None:
        key = self.key(audio_bytes, model, prompt_version)
        cache_path = self.cache_dir / service / f"{key}.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = cache_path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        temporary_path.replace(cache_path)


class CachedPrisma:
    def __init__(self, cache: EvalCache, client: Any) -> None:
        self.cache = cache
        self.client = client

    def transcribe(
        self,
        audio_bytes: bytes,
        language_code: str,
        previous_text: str | None = None,
    ) -> dict[str, Any]:
        context_id = hashlib.sha256((previous_text or "").encode("utf-8")).hexdigest()[:12]
        prompt_version = f"prisma-transcribe-v1-{language_code}-{context_id}"
        cached = self.cache.read("prisma", audio_bytes, PRISMA_MODEL, prompt_version)
        if cached is not None:
            return cached
        response = self.client.transcribe(audio_bytes, language_code, previous_text)
        self.cache.write("prisma", audio_bytes, PRISMA_MODEL, prompt_version, response)
        return response


class CachedEvon:
    def __init__(self, cache: EvalCache, audio_bytes: bytes, client: Any) -> None:
        self.cache = cache
        self.audio_bytes = audio_bytes
        self.client = client
        self.model = getattr(client, "model", DEFAULT_MODEL)

    def complete_json(self, system: str, user: str) -> Any:
        if "numeric-only read-back" in system:
            version = "anc-eval-numeric-readback-v1"
        elif "REPAIR ATTEMPT" in system:
            version = f"{PROMPT_VERSION}-repair-1"
        else:
            version = PROMPT_VERSION
        cached = self.cache.read("evon", self.audio_bytes, self.model, version)
        if cached is not None:
            if isinstance(cached, dict) and cached.get("__cache_error__") == "json_decode":
                raise json.JSONDecodeError(cached["message"], "", 0)
            return cached
        try:
            response = self.client.complete_json(system, user)
        except json.JSONDecodeError as error:
            self.cache.write(
                "evon",
                self.audio_bytes,
                self.model,
                version,
                {"__cache_error__": "json_decode", "message": error.msg},
            )
            raise
        self.cache.write("evon", self.audio_bytes, self.model, version, response)
        return response


def _load_scenarios(path: Path, language: str) -> list[dict[str, Any]]:
    scenarios = json.loads(path.read_text(encoding="utf-8"))
    if language != "all":
        scenarios = [item for item in scenarios if item["language"] == language]
    if not scenarios:
        raise ValueError(f"No ground-truth scenarios found for language {language}.")
    return scenarios


def _selected_noise_levels(noise_arg: str) -> tuple[str, ...]:
    return NOISE_LEVELS if noise_arg == "all" else (noise_arg,)


def _reference_stats(reference: str, hypothesis: str) -> dict[str, Any]:
    reference_words = reference.split()
    hypothesis_words = hypothesis.split()
    word_errors = _edit_distance(reference_words, hypothesis_words)
    character_errors = _edit_distance(list(reference), list(hypothesis))
    reference_characters = len(reference)
    return {
        "reference_words": len(reference_words),
        "word_errors": word_errors,
        "wer": float(jiwer.wer(reference, hypothesis)),
        "reference_characters": reference_characters,
        "character_errors": character_errors,
        "cer": float(jiwer.cer(reference, hypothesis)),
    }


def _fixture_audio_variants(scenario_id: str) -> dict[str, bytes]:
    seed = int.from_bytes(hashlib.sha256(scenario_id.encode("utf-8")).digest()[:8], "big")
    synthetic = generate_synthetic_test_wav(duration_seconds=1.0, frequency_hz=220 + seed % 500)
    return noise_variants(synthetic, seed)


def _latency_fixture(scenario_id: str, noise: str) -> dict[str, float]:
    value = int.from_bytes(hashlib.sha256(f"{scenario_id}|{noise}".encode()).digest()[:4], "big")
    noise_addition = {"clean": 0, "15dB": 85, "5dB": 190}[noise]
    return {
        "prisma_ms": 310 + value % 90 + noise_addition,
        "evon_ms": 540 + (value >> 4) % 120,
        "rules_ms": 1 + (value >> 8) % 3,
        "timbre_ms": 280 + (value >> 12) % 100,
    }


def _question_for(language: str, gap_field: str | None) -> str:
    template_path = Path(__file__).resolve().parents[1] / "app" / "templates" / "questions.json"
    templates = json.loads(template_path.read_text(encoding="utf-8"))
    key_map = {
        "hi-IN": "hi", "mr-IN": "mr", "te-IN": "te",
        "ta-IN": "ta", "ml-IN": "ml", "en-IN": "en",
    }
    return templates.get(gap_field, {}).get(key_map[language], "")


def _evaluate_scenario(
    scenario: dict[str, Any],
    noise: str,
    audio_bytes: bytes,
    dry_run: bool,
    cache: EvalCache,
    live_clients: tuple[Any, Any, Any] | None,
) -> dict[str, Any]:
    expected_record = scenario["expected_record"]
    timbre_ms = 0.0
    dry_latency = _latency_fixture(scenario["id"], noise) if dry_run else None
    if dry_run:
        transcript = scenario["transcript"]
        evon = FixtureEvonClient(expected_record)
        prisma_ms = dry_latency["prisma_ms"]
        evon_ms = dry_latency["evon_ms"]
    else:
        if live_clients is None:
            raise RuntimeError("Live clients were not configured.")
        prisma, evon_api, timbre = live_clients
        cached_prisma = CachedPrisma(cache, prisma)
        started = time.perf_counter()
        stt_response = cached_prisma.transcribe(audio_bytes, scenario["language"])
        prisma_ms = (time.perf_counter() - started) * 1000
        if not stt_response.get("success") or stt_response.get("truncated") is True:
            raise ValueError(f"Prisma halted on scenario {scenario['id']}.")
        transcript = stt_response.get("transcript")
        if not isinstance(transcript, str) or not transcript.strip():
            raise ValueError(f"Prisma returned an empty transcript for {scenario['id']}.")
        evon = CachedEvon(cache, audio_bytes, evon_api)
        started = time.perf_counter()
        record = extract_visit_record(transcript, scenario["language"], evon)
        evon_ms = (time.perf_counter() - started) * 1000

    if dry_run:
        started = time.perf_counter()
        record = extract_visit_record(transcript, scenario["language"], evon)
        evon_ms = 540 + int.from_bytes(
            hashlib.sha256(scenario["id"].encode()).digest()[:2], "big"
        ) % 120

    started = time.perf_counter()
    evaluation = evaluate_visit(record)
    rules_ms = (time.perf_counter() - started) * 1000 if not dry_run else dry_latency["rules_ms"]

    readback_observation: dict[str, Any] | None = None
    readback = scenario.get("readback")
    if readback:
        readback_audio = audio_bytes
        if not dry_run:
            readback_path = Path(__file__).resolve().parent / "audio" / f"{scenario['id']}_readback.wav"
            if not readback_path.exists():
                raise FileNotFoundError(f"Missing live read-back recording: {readback_path}")
            readback_audio = noise_variants(
                readback_path.read_bytes(),
                seed=int.from_bytes(hashlib.sha256(scenario["id"].encode()).digest()[:8], "big"),
            )[noise]
        if dry_run:
            readback_client = FixtureEvonClient(
                {
                    "confirmed": readback["expected_confirmed"],
                    "evidence": readback["transcript"],
                    **readback["expected_updates"],
                }
            )
            readback_transcript = readback["transcript"]
        else:
            cached_prisma = CachedPrisma(cache, live_clients[0])
            started = time.perf_counter()
            readback_stt = cached_prisma.transcribe(
                readback_audio,
                scenario["language"],
                previous_text="Read-back confirmation of blood pressure and gestational weeks.",
            )
            prisma_ms += (time.perf_counter() - started) * 1000
            if not readback_stt.get("success") or readback_stt.get("truncated") is True:
                raise ValueError(f"Prisma halted on read-back {scenario['id']}.")
            readback_transcript = readback_stt.get("transcript", "")
            readback_client = CachedEvon(cache, readback_audio, live_clients[1])
            started = time.perf_counter()
        if not dry_run:
            correction = extract_numeric_correction(
                readback_transcript,
                int(record.bp_systolic) if record.bp_systolic is not None else None,
                int(record.bp_diastolic) if record.bp_diastolic is not None else None,
                int(record.gestational_weeks) if record.gestational_weeks is not None else None,
                scenario["language"],
                readback_client,
            )
            evon_ms += (time.perf_counter() - started) * 1000
        else:
            correction = extract_numeric_correction(
                readback_transcript,
                int(record.bp_systolic) if record.bp_systolic is not None else None,
                int(record.bp_diastolic) if record.bp_diastolic is not None else None,
                int(record.gestational_weeks) if record.gestational_weeks is not None else None,
                scenario["language"],
                readback_client,
            )
        corrections_match = all(
            getattr(correction, field_name) == expected
            for field_name, expected in readback["expected_updates"].items()
        )
        readback_observation = {
            "injected_error": bool(readback["injected_error"]),
            "caught": (
                correction.confirmed is readback["expected_confirmed"]
                and corrections_match
            ),
            "confirmed": correction.confirmed,
        }
        if not dry_run:
            question = _question_for(scenario["language"], "readback_confirm")
            if question:
                started = time.perf_counter()
                live_clients[2].synthesize(question, scenario["language"])
                timbre_ms = (time.perf_counter() - started) * 1000

    actual_record = _jsonable_record(record)
    critical = count_critical_extraction_errors(expected_record, actual_record)
    record_field_total = len(expected_record)
    record_field_matches = sum(
        actual_record.get(key) == value for key, value in expected_record.items()
    )
    expected_rule_ids = scenario.get("expected_rule_ids", [])
    exact_rule_match = evaluation.rule_ids == expected_rule_ids
    expected_gap_order = scenario.get("expected_gap_order", [])
    gap_applicable = bool(scenario.get("gap_check_applicable", False))
    gap_match = not gap_applicable or evaluation.top_gaps == expected_gap_order
    danger_applicable = bool(scenario.get("danger_recall_applicable", False))
    expected_danger_rules = {
        rule_id
        for rule_id in expected_rule_ids
        if rule_id.startswith("RULE-EMG-") or rule_id.startswith("RULE-HRP-")
    }
    danger_match = expected_danger_rules.issubset(evaluation.rule_ids)
    transcription = _reference_stats(scenario["transcript"], transcript)

    if not dry_run and not readback:
        gap = evaluation.voice_followup_gaps[0] if evaluation.voice_followup_gaps else None
        question = _question_for(scenario["language"], gap) or _question_for(
            scenario["language"], "readback_confirm"
        )
        if question:
            started = time.perf_counter()
            live_clients[2].synthesize(question, scenario["language"])
            timbre_ms = (time.perf_counter() - started) * 1000

    if dry_run:
        latency = dry_latency
    else:
        latency = {
            "prisma_ms": prisma_ms,
            "evon_ms": evon_ms,
            "rules_ms": rules_ms,
            "timbre_ms": timbre_ms,
        }
    latency["total_turn_seconds"] = sum(latency.values()) / 1000
    return {
        "scenario_id": scenario["id"],
        "language": scenario["language"],
        "type": scenario["type"],
        "noise": noise,
        "expected_record": expected_record,
        "actual_record": actual_record,
        "critical": critical,
        "record_field_matches": record_field_matches,
        "record_field_total": record_field_total,
        "expected_rule_ids": expected_rule_ids,
        "actual_rule_ids": evaluation.rule_ids,
        "exact_rule_match": exact_rule_match,
        "danger_applicable": danger_applicable,
        "danger_match": danger_match,
        "gap_applicable": gap_applicable,
        "gap_match": gap_match,
        "expected_gap_order": expected_gap_order,
        "actual_gap_order": evaluation.top_gaps,
        "readback": readback_observation,
        "transcription": transcription,
        "latency": latency,
    }


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    return numerator / denominator if denominator else None


def _aggregate(results: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        groups[(result["language"], result["noise"])].append(result)

    breakdown_rows: list[dict[str, Any]] = []
    for (language, noise), items in sorted(groups.items()):
        record_matches = sum(item["record_field_matches"] for item in items)
        record_total = sum(item["record_field_total"] for item in items)
        rule_matches = sum(item["exact_rule_match"] for item in items)
        danger_items = [item for item in items if item["danger_applicable"]]
        gap_items = [item for item in items if item["gap_applicable"]]
        readback_items = [
            item for item in items if item["readback"] and item["readback"]["injected_error"]
        ]
        words = sum(item["transcription"]["reference_words"] for item in items)
        word_errors = sum(item["transcription"]["word_errors"] for item in items)
        chars = sum(item["transcription"]["reference_characters"] for item in items)
        char_errors = sum(item["transcription"]["character_errors"] for item in items)
        critical_totals = {
            key: sum(item["critical"][key] for item in items)
            for key in ("false_reassurance", "expected_present", "false_alarm", "expected_denied")
        }
        row: dict[str, Any] = {
            "language": language,
            "noise": noise,
            "scenario_count": len(items),
            "extraction_fields_correct": record_matches,
            "extraction_fields_total": record_total,
            "extraction_accuracy": _ratio(record_matches, record_total),
            "rule_scenarios_correct": rule_matches,
            "rule_scenarios_total": len(items),
            "rule_accuracy": _ratio(rule_matches, len(items)),
            "danger_recall": f"{sum(item['danger_match'] for item in danger_items)} of {len(danger_items)}",
            "gap_order": f"{sum(item['gap_match'] for item in gap_items)} of {len(gap_items)}",
            "readback_catch": f"{sum(item['readback']['caught'] for item in readback_items)} of {len(readback_items)}",
            "false_reassurance": f"{critical_totals['false_reassurance']} of {critical_totals['expected_present']}",
            "false_alarm": f"{critical_totals['false_alarm']} of {critical_totals['expected_denied']}",
            "word_errors": word_errors,
            "reference_words": words,
            "wer": _ratio(word_errors, words),
            "character_errors": char_errors,
            "reference_characters": chars,
            "cer": _ratio(char_errors, chars),
        }
        for field_name in ("prisma_ms", "evon_ms", "rules_ms", "timbre_ms", "total_turn_seconds"):
            row[f"mean_{field_name}"] = statistics.mean(
                item["latency"][field_name] for item in items
            )
        breakdown_rows.append(row)

    critical_all = {
        key: sum(item["critical"][key] for item in results)
        for key in ("false_reassurance", "expected_present", "false_alarm", "expected_denied")
    }
    danger_items = [item for item in results if item["danger_applicable"]]
    gap_items = [item for item in results if item["gap_applicable"]]
    readback_items = [
        item for item in results if item["readback"] and item["readback"]["injected_error"]
    ]
    words = sum(item["transcription"]["reference_words"] for item in results)
    word_errors = sum(item["transcription"]["word_errors"] for item in results)
    chars = sum(item["transcription"]["reference_characters"] for item in results)
    char_errors = sum(item["transcription"]["character_errors"] for item in results)

    def row(metric: str, numerator: int | float, denominator: int | float, details: str = "") -> dict[str, Any]:
        return {
            "metric": metric,
            "numerator": numerator,
            "denominator": denominator,
            "count": f"{numerator} of {denominator}",
            "rate": _ratio(numerator, denominator),
            "details": details,
        }

    metric_rows = [
        row("1. Critical Extraction Errors — False Reassurance", critical_all["false_reassurance"], critical_all["expected_present"]),
        row("1. Critical Extraction Errors — False Alarm", critical_all["false_alarm"], critical_all["expected_denied"]),
        row("2. Danger-Sign Flag Recall", sum(item["danger_match"] for item in danger_items), len(danger_items)),
        row("3. Gap-Check Correctness / Priority Order", sum(item["gap_match"] for item in gap_items), len(gap_items)),
        row("4. Read-Back Catch Rate — Injected Errors", sum(item["readback"]["caught"] for item in readback_items), len(readback_items)),
        row("5. Transcription Quality — WER", word_errors, words, f"{word_errors} word edit(s)"),
        row("5. Transcription Quality — CER", char_errors, chars, f"{char_errors} character edit(s)"),
    ]
    latency_details = "; ".join(
        f"mean {field_name}={statistics.mean(item['latency'][field_name] for item in results):.2f}"
        for field_name in ("prisma_ms", "evon_ms", "rules_ms", "timbre_ms", "total_turn_seconds")
    )
    metric_rows.append(
        {
            "metric": "6. Per-Turn Latency Breakdown",
            "numerator": len(results),
            "denominator": len(results),
            "count": f"{len(results)} turns",
            "rate": None,
            "details": latency_details,
        }
    )
    return metric_rows, breakdown_rows


def _format_rate(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{100 * float(value):.1f}%"


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_report(path: Path, metrics: list[dict[str, Any]], breakdown: list[dict[str, Any]], dry_run: bool) -> None:
    mode_note = (
        "Offline fixture run: these transcripts and simulated latencies do not measure recorded speech performance."
        if dry_run
        else "Live run: results reflect the available recordings and provider responses; sample size and recording conditions limit generalization."
    )
    lines = [
        "# ANC Evaluation Report",
        "",
        mode_note,
        "",
        f"Evaluation samples: {sum(int(row['scenario_count']) for row in breakdown)} language/noise observations.",
        "",
        "## PRD Section 13 Metrics (priority order)",
        "",
        "| Metric | Raw count | Rate | Notes |",
        "|---|---:|---:|---|",
    ]
    for item in metrics:
        details = item["details"].replace("|", "\\|")
        lines.append(
            f"| {item['metric']} | {item['count']} | {_format_rate(item['rate'])} | {details} |"
        )
    lines.extend(
        [
            "",
            "## Language and Noise Breakdown",
            "",
            "| Language | Noise | Extraction fields | Extraction accuracy | Rule match | WER | CER | Danger recall | Gap order | Read-back catch | Mean turn latency (s) |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in breakdown:
        lines.append(
            f"| {item['language']} | {item['noise']} | "
            f"{item['extraction_fields_correct']} of {item['extraction_fields_total']} | "
            f"{_format_rate(item['extraction_accuracy'])} | {_format_rate(item['rule_accuracy'])} | "
            f"{_format_rate(item['wer'])} | {_format_rate(item['cer'])} | "
            f"{item['danger_recall']} | {item['gap_order']} | {item['readback_catch']} | "
            f"{item['mean_total_turn_seconds']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation and Limitations",
            "",
            "- WER/CER use the scenario transcript as reference. In dry-run mode, the fixture transcript is replayed rather than inferred from audio.",
            "- Dry-run latencies are deterministic simulated values; they are not observed service latency.",
            "- Synthetic scenarios are not a substitute for clinical validation or a representative multilingual speech corpus.",
            "- No output is a diagnosis, treatment recommendation, or PMSMA sticker assignment.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_chart(path: Path, breakdown: list[dict[str, Any]], dry_run: bool) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(16, 9), dpi=320)
    figure.patch.set_facecolor("#f3f7f6")
    colors = {"clean": "#16794b", "15dB": "#d18b16", "5dB": "#ad3038"}
    chart_languages = tuple(dict.fromkeys(item["language"] for item in breakdown))
    labels = [language.replace("-IN", "") for language in chart_languages]
    x_values = np.arange(len(labels))
    chart_noises = tuple(dict.fromkeys(item["noise"] for item in breakdown))
    bar_width = 0.72 / max(len(chart_noises), 1)

    for axis, value_field, title in (
        (axes[0], "extraction_accuracy", "Extraction field accuracy"),
        (axes[1], "rule_accuracy", "Referral-rule match"),
    ):
        for noise_index, noise in enumerate(chart_noises):
            rows = {item["language"]: item for item in breakdown if item["noise"] == noise}
            values = [100 * float(rows[language][value_field] or 0) for language in chart_languages]
            positions = x_values - 0.36 + bar_width / 2 + noise_index * bar_width
            axis.bar(
                positions,
                values,
                bar_width,
                label=noise,
                color=colors[noise],
                edgecolor="#ffffff",
                linewidth=0.8,
            )
        axis.set_title(title, fontsize=18, fontweight="bold", color="#16353a", pad=15)
        axis.set_xticks(x_values, labels, fontsize=12)
        axis.set_ylim(0, 105)
        axis.set_ylabel("Scenario score (%)", fontsize=12)
        axis.grid(axis="y", alpha=0.2)
        axis.set_axisbelow(True)
        axis.spines[["top", "right"]].set_visible(False)
    axes[0].legend(title="Noise condition", frameon=False, loc="lower left")
    subtitle = (
        "OFFLINE FIXTURE DEMO — NOT MEASURED SPEECH PERFORMANCE"
        if dry_run
        else "SYNTHETIC SCENARIO RESULTS — REVIEW RECORDING SAMPLE LIMITATIONS"
    )
    figure.suptitle("Multilingual ANC Extraction & Rule Performance", fontsize=24, fontweight="bold", color="#123c43", y=0.96)
    figure.text(0.5, 0.90, subtitle, ha="center", color="#52686d", fontsize=12, fontweight="bold")
    figure.text(
        0.5,
        0.035,
        "Flags & Records Only — Never Diagnoses | Zero False-Reassurance Defaults",
        ha="center",
        va="center",
        color="#ffffff",
        fontsize=15,
        fontweight="bold",
        bbox={"boxstyle": "round,pad=0.8", "facecolor": "#123c43", "edgecolor": "#123c43"},
    )
    figure.tight_layout(rect=(0.04, 0.10, 0.98, 0.86))
    figure.savefig(path, dpi=320, facecolor=figure.get_facecolor())
    plt.close(figure)


def _live_clients() -> tuple[Any, Any, Any]:
    return PrismaClient(), EvonClient(), TimbreClient()


def run_evaluation(
    language: str,
    noise_arg: str,
    dry_run: bool,
    scenarios_path: Path | None = None,
    output_dir: Path | None = None,
    audio_dir: Path | None = None,
    cache_dir: Path | None = None,
) -> list[dict[str, Any]]:
    root = Path(__file__).resolve().parent
    scenarios = _load_scenarios(scenarios_path or root / "ground_truth" / "scenarios.json", language)
    output = output_dir or root / "results"
    audio_root = audio_dir or root / "audio"
    cache = EvalCache(cache_dir or root.parent / ".cache" / "eval_cache")
    levels = _selected_noise_levels(noise_arg)
    if not dry_run:
        missing_recordings = [
            audio_root / f"{scenario['id']}.wav"
            for scenario in scenarios
            if not (audio_root / f"{scenario['id']}.wav").exists()
        ]
        missing_recordings.extend(
            audio_root / f"{scenario['id']}_readback.wav"
            for scenario in scenarios
            if scenario.get("readback")
            and not (audio_root / f"{scenario['id']}_readback.wav").exists()
        )
        if missing_recordings:
            raise FileNotFoundError(
                "Missing live recording(s): "
                + ", ".join(str(path) for path in missing_recordings)
                + ". Record synthetic clips listed in eval/recording_scripts.md."
            )
    live_clients = None if dry_run else _live_clients()
    results: list[dict[str, Any]] = []

    for scenario in scenarios:
        if dry_run:
            variants = _fixture_audio_variants(scenario["id"])
        else:
            source_path = audio_root / f"{scenario['id']}.wav"
            if not source_path.exists():
                raise FileNotFoundError(
                    f"Missing live recording {source_path}. Record synthetic clips listed in eval/recording_scripts.md."
                )
            variants = noise_variants(source_path.read_bytes(), seed=int.from_bytes(
                hashlib.sha256(scenario["id"].encode()).digest()[:8], "big"
            ))
        for noise in levels:
            results.append(
                _evaluate_scenario(
                    scenario,
                    noise,
                    variants[noise],
                    dry_run,
                    cache,
                    live_clients,
                )
            )

    output.mkdir(parents=True, exist_ok=True)
    metrics, breakdown = _aggregate(results)
    _write_csv(output / "metrics_summary.csv", metrics)
    _write_csv(output / "language_noise_breakdown.csv", breakdown)
    _write_report(output / "evaluation_report.md", metrics, breakdown, dry_run)
    _write_chart(output / "demo_slide_chart.png", breakdown, dry_run)
    return results


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Run fixtures only; makes zero API calls.")
    mode.add_argument("--live", action="store_true", help="Use recorded WAVs and live Gnani APIs (cached).")
    parser.add_argument("--lang", choices=("all", *LANGUAGES), default="all")
    parser.add_argument("--noise", choices=NOISE_ARGUMENTS, default="all")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    try:
        results = run_evaluation(args.lang, args.noise, args.dry_run)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Evaluation stopped: {error}", file=sys.stderr)
        return 2
    print(
        f"Evaluated {len(results)} scenario/noise observations "
        f"({'offline fixture' if args.dry_run else 'live'}); "
        f"artifacts saved under {Path(__file__).resolve().parent / 'results'}."
    )
    if args.dry_run:
        print("Fixture metrics do not represent measured speech or service performance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
