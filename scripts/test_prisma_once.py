"""One-shot Prisma STT test — no interactive prompt."""
import os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()

import httpx

key = os.environ["GNANI_API_KEY"]
wav_path = Path(sys.argv[1])
audio = wav_path.read_bytes()

print(f"Sending {wav_path.name} ({len(audio)} bytes) to Prisma v3.0 …")
t0 = time.perf_counter()

r = httpx.post(
    "https://api.vachana.ai/stt/v3",
    headers={"X-API-Key-ID": key},
    files={"audio_file": (wav_path.name, audio, "audio/wav")},
    data={
        "language_code": "hi-IN",
        "model": "prisma-v3.0",
        "format": "transcribe",
        "topic": "ASHA worker recording an Antenatal Care (ANC) pregnancy home visit",
    },
    timeout=60,
)

elapsed = time.perf_counter() - t0
print(f"HTTP {r.status_code}  ({elapsed:.2f}s)")
print(r.text)
