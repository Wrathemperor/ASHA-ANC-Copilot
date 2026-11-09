# ANC Evaluation Report

Offline fixture run: these transcripts and simulated latencies do not measure recorded speech performance.

Evaluation samples: 60 language/noise observations.

## PRD Section 13 Metrics (priority order)

| Metric | Raw count | Rate | Notes |
|---|---:|---:|---|
| 1. Critical Extraction Errors — False Reassurance | 0 of 21 | 0.0% |  |
| 1. Critical Extraction Errors — False Alarm | 0 of 357 | 0.0% |  |
| 2. Danger-Sign Flag Recall | 24 of 24 | 100.0% |  |
| 3. Gap-Check Correctness / Priority Order | 12 of 12 | 100.0% |  |
| 4. Read-Back Catch Rate — Injected Errors | 6 of 6 | 100.0% |  |
| 5. Transcription Quality — WER | 0 of 1326 | 0.0% | 0 word edit(s) |
| 5. Transcription Quality — CER | 0 of 8157 | 0.0% | 0 character edit(s) |
| 6. Per-Turn Latency Breakdown | 60 turns | n/a | mean prisma_ms=451.83; mean evon_ms=601.60; mean rules_ms=1.97; mean timbre_ms=335.72; mean total_turn_seconds=1.39 |

## Language and Noise Breakdown

| Language | Noise | Extraction fields | Extraction accuracy | Rule match | WER | CER | Danger recall | Gap order | Read-back catch | Mean turn latency (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| en-IN | 15dB | 28 of 28 | 100.0% | 100.0% | 0.0% | 0.0% | 1 of 1 | 0 of 0 | 0 of 0 | 1.410 |
| en-IN | 5dB | 28 of 28 | 100.0% | 100.0% | 0.0% | 0.0% | 1 of 1 | 0 of 0 | 0 of 0 | 1.460 |
| en-IN | clean | 28 of 28 | 100.0% | 100.0% | 0.0% | 0.0% | 1 of 1 | 0 of 0 | 0 of 0 | 1.226 |
| hi-IN | 15dB | 41 of 41 | 100.0% | 100.0% | 0.0% | 0.0% | 3 of 3 | 1 of 1 | 1 of 1 | 1.345 |
| hi-IN | 5dB | 41 of 41 | 100.0% | 100.0% | 0.0% | 0.0% | 3 of 3 | 1 of 1 | 1 of 1 | 1.512 |
| hi-IN | clean | 41 of 41 | 100.0% | 100.0% | 0.0% | 0.0% | 3 of 3 | 1 of 1 | 1 of 1 | 1.316 |
| ml-IN | 15dB | 20 of 20 | 100.0% | 100.0% | 0.0% | 0.0% | 1 of 1 | 0 of 0 | 0 of 0 | 1.404 |
| ml-IN | 5dB | 20 of 20 | 100.0% | 100.0% | 0.0% | 0.0% | 1 of 1 | 0 of 0 | 0 of 0 | 1.568 |
| ml-IN | clean | 20 of 20 | 100.0% | 100.0% | 0.0% | 0.0% | 1 of 1 | 0 of 0 | 0 of 0 | 1.262 |
| mr-IN | 15dB | 32 of 32 | 100.0% | 100.0% | 0.0% | 0.0% | 1 of 1 | 2 of 2 | 0 of 0 | 1.409 |
| mr-IN | 5dB | 32 of 32 | 100.0% | 100.0% | 0.0% | 0.0% | 1 of 1 | 2 of 2 | 0 of 0 | 1.451 |
| mr-IN | clean | 32 of 32 | 100.0% | 100.0% | 0.0% | 0.0% | 1 of 1 | 2 of 2 | 0 of 0 | 1.315 |
| ta-IN | 15dB | 31 of 31 | 100.0% | 100.0% | 0.0% | 0.0% | 1 of 1 | 0 of 0 | 1 of 1 | 1.418 |
| ta-IN | 5dB | 31 of 31 | 100.0% | 100.0% | 0.0% | 0.0% | 1 of 1 | 0 of 0 | 1 of 1 | 1.515 |
| ta-IN | clean | 31 of 31 | 100.0% | 100.0% | 0.0% | 0.0% | 1 of 1 | 0 of 0 | 1 of 1 | 1.276 |
| te-IN | 15dB | 27 of 27 | 100.0% | 100.0% | 0.0% | 0.0% | 1 of 1 | 1 of 1 | 0 of 0 | 1.409 |
| te-IN | 5dB | 27 of 27 | 100.0% | 100.0% | 0.0% | 0.0% | 1 of 1 | 1 of 1 | 0 of 0 | 1.465 |
| te-IN | clean | 27 of 27 | 100.0% | 100.0% | 0.0% | 0.0% | 1 of 1 | 1 of 1 | 0 of 0 | 1.298 |

## Interpretation and Limitations

- WER/CER use the scenario transcript as reference. In dry-run mode, the fixture transcript is replayed rather than inferred from audio.
- Dry-run latencies are deterministic simulated values; they are not observed service latency.
- Synthetic scenarios are not a substitute for clinical validation or a representative multilingual speech corpus.
- No output is a diagnosis, treatment recommendation, or PMSMA sticker assignment.
