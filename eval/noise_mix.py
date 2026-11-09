"""Reproducible PCM WAV noise mixing for offline ANC evaluation."""

from __future__ import annotations

import argparse
import hashlib
import io
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16_000
NOISE_LEVELS = ("clean", "15dB", "5dB")


def read_pcm_wav(audio_bytes: bytes) -> np.ndarray:
    """Decode 16 kHz, mono, signed 16-bit PCM WAV into a float waveform."""
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
            if (
                wav_file.getframerate() != SAMPLE_RATE
                or wav_file.getnchannels() != 1
                or wav_file.getsampwidth() != 2
                or wav_file.getcomptype() != "NONE"
            ):
                raise ValueError("Expected 16 kHz mono 16-bit PCM WAV.")
            samples = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype="<i2")
    except (EOFError, wave.Error) as error:
        raise ValueError("Invalid PCM WAV input.") from error
    return samples.astype(np.float64) / 32768.0


def write_pcm_wav(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Encode normalized float samples as 16-bit PCM WAV."""
    clipped = np.clip(np.asarray(samples, dtype=np.float64), -1.0, 1.0)
    pcm = np.rint(clipped * 32767).astype("<i2")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())
    return output.getvalue()


def generate_synthetic_test_wav(
    duration_seconds: float = 1.0,
    frequency_hz: float = 440.0,
    sample_rate: int = SAMPLE_RATE,
    amplitude: float = 0.2,
) -> bytes:
    """Build a reproducible synthetic sine-wave WAV for tests and dry runs."""
    if duration_seconds <= 0 or sample_rate != SAMPLE_RATE or not 0 < amplitude < 1:
        raise ValueError("Use positive duration, 16 kHz sample rate, and amplitude in (0, 1).")
    count = int(round(duration_seconds * sample_rate))
    time_axis = np.arange(count, dtype=np.float64) / sample_rate
    signal = amplitude * np.sin(2 * np.pi * frequency_hz * time_axis)
    return write_pcm_wav(signal, sample_rate)


def _pink_noise(sample_count: int, rng: np.random.Generator) -> np.ndarray:
    white = rng.standard_normal(sample_count)
    spectrum = np.fft.rfft(white)
    frequencies = np.fft.rfftfreq(sample_count)
    weights = np.ones_like(frequencies)
    weights[1:] = 1 / np.sqrt(frequencies[1:])
    weights[0] = 0
    pink = np.fft.irfft(spectrum * weights, n=sample_count)
    pink -= pink.mean()
    return pink


def mix_noise(clean_samples: np.ndarray, snr_db: float, seed: int = 0) -> np.ndarray:
    """Mix deterministic pink noise at the requested measured SNR."""
    clean = np.asarray(clean_samples, dtype=np.float64)
    if clean.ndim != 1 or clean.size == 0:
        raise ValueError("Clean audio must be a non-empty mono waveform.")
    if not np.all(np.isfinite(clean)) or not np.isfinite(snr_db):
        raise ValueError("Audio and SNR must contain finite values.")
    signal_rms = float(np.sqrt(np.mean(np.square(clean))))
    if signal_rms == 0:
        raise ValueError("Cannot set SNR for silent audio.")

    noise = _pink_noise(clean.size, np.random.default_rng(seed))
    noise_rms = float(np.sqrt(np.mean(np.square(noise))))
    target_noise_rms = signal_rms / (10 ** (snr_db / 20))
    noise *= target_noise_rms / noise_rms
    mixed = clean + noise
    peak = float(np.max(np.abs(mixed)))
    if peak > 0.999:
        mixed *= 0.999 / peak
    return mixed


def mix_wav_bytes(audio_bytes: bytes, snr_db: float, seed: int = 0) -> bytes:
    return write_pcm_wav(mix_noise(read_pcm_wav(audio_bytes), snr_db, seed))


def noise_variants(
    audio_bytes: bytes,
    seed: int = 0,
) -> dict[str, bytes]:
    """Return original clean bytes and deterministic 15/5 dB variants."""
    return {
        "clean": audio_bytes,
        "15dB": mix_wav_bytes(audio_bytes, 15, seed),
        "5dB": mix_wav_bytes(audio_bytes, 5, seed),
    }


def generate_audio_variants(audio_dir: Path, output_dir: Path | None = None) -> int:
    """Generate clean/15dB/5dB WAV variants for each matching clean recording."""
    target_dir = output_dir or audio_dir / "noisy"
    target_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for source in sorted(audio_dir.glob("*.wav")):
        audio_bytes = source.read_bytes()
        if source.parent == target_dir:
            continue
        seed = int.from_bytes(hashlib.sha256(source.name.encode("utf-8")).digest()[:8], "big")
        for level, variant in noise_variants(audio_bytes, seed).items():
            (target_dir / f"{source.stem}_{level}.wav").write_bytes(variant)
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio-dir", type=Path, default=Path("eval/audio"))
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    print(f"Wrote {generate_audio_variants(args.audio_dir, args.output_dir)} audio variants.")


if __name__ == "__main__":
    main()
