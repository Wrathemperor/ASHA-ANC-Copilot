# Gnani AI APIs — Technical Specification & Source of Truth

> **Strict Source of Truth:** Verified against official documentation at `https://docs.gnani.ai` (Vachana Speech APIs & Platform Documentation).  
> **Rule:** Any parameter or endpoint not explicitly documented in the official docs is marked in bold as **UNKNOWN — VERIFY IN DASHBOARD**.

---

## 1. Authentication & Key Safety

### Authentication Format
- **Speech APIs (REST / WebSocket / SSE):**
  - **Header Name:** `X-API-Key-ID`
  - **Format:** `X-API-Key-ID: <GNANI_API_KEY>`
  - **Correlation ID (Optional):** `X-API-Request-ID: <custom_request_id>` (echoed back in response as `request_id`)
  - **HTTP Errors:**
    - `401 Unauthorized` with `{"detail": {"error_code": "MISSING_API_KEY", "message": "..."}}` if header is absent.
    - `401 Unauthorized` with `{"detail": {"error_code": "INVALID_API_KEY", "message": "Unauthorized"}}` if key is invalid.
    - `403 Forbidden` with `{"detail": {"error_code": "SCOPE_NOT_ALLOWED", "message": "Service '...' not in allowed scopes"}}` if the key lacks scope for that service.
- **Agent Platform API (api.inya.ai):**
  - **Header Name:** `x-api-key`
- **Official Python SDK (`gnani-vachana`):**
  - Environment variable automatically loaded by SDK clients (`GnaniSTTClient`, `GnaniTTSClient`):
    ```bash
    export GNANI_API_KEY="<your-api-key>"
    ```

### Key Safety Rule (Account Hard Limit)
- **Account Limit:** The Gnani platform enforces a hard limit of **3 API keys** per account.
- **Shared Secret Rule:** All three service clients (**Prisma STT**, **Evon LLM**, and **Timbre TTS**) **MUST** share and load the single `GNANI_API_KEY` environment variable. Never create or allocate separate environment variables or individual keys per client.

---

## 2. Gnani Prisma v2.5 (Speech-to-Text — STT)

### REST Endpoint
- **URL:** `POST https://api.vachana.ai/stt/v3`
- **Content-Type:** `multipart/form-data`

### Audio Requirements & Limits
- **Audio Formats Supported:** `WAV`, `MP3`, `OGG`, `FLAC`, `AAC`, `M4A` (detected automatically from the file extension).
  - *Note on WebM:* Not listed in the documented supported extensions for REST STT; convert or verify support via dashboard: **UNKNOWN — VERIFY IN DASHBOARD**.
- **Sample Rate:** `8 kHz` to `44.1 kHz` (8000 Hz – 44100 Hz).
- **Duration Limits (REST):**
  - Maximum duration: **30 seconds** per request.
  - Minimum audio: Clips < 0.1 s return `{"success": true, "request_id": "...", "transcript": ""}` without processing.

### Supported Language Codes (BCP-47)
The following 6 language codes are verified from official docs:
- **Hindi:** `hi-IN`
- **Marathi:** `mr-IN`
- **Tamil:** `ta-IN`
- **Telugu:** `te-IN`
- **Malayalam:** `ml-IN`
- **Indian English:** `en-IN`

*(Additional documented languages: Bengali `bn-IN`, Gujarati `gu-IN`, Kannada `kn-IN`, Punjabi `pa-IN`).*  
*Note: Prisma v2.5 accepts exactly 1 language code in `language_code`. Multi-language hints and `indic-auto` are Prisma v3.0 features only.*

### Request Format (`multipart/form-data`)
| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `audio_file` | Binary File | **Yes** | The audio file to transcribe (≤ 30 seconds). |
| `language_code` | `string` | **Yes** | Target language BCP-47 code (e.g., `hi-IN`). |
| `model` | `string` | No | Omit for default Prisma v2.5 (or pass `prisma-v2.5`). |
| `format` | `string` (enum) | No | `verbatim` (default: raw spoken words) or `transcribe` (Inverse Text Normalization enabled). |
| `itn_native_numerals` | `boolean` | No | Default `false`. If `true` with `format=transcribe`, renders numerals in native script (e.g. Devanagari digits). |
| `enable_substitution` | `boolean` | No | Default `false`. Enables post-transcription find-and-replace rules. |
| `substitution_map` | `string` (JSON) | No | JSON array of up to 10 rules: `[{"patterns": ["word"], "replacement": "target"}]`. |
| `bias_list` | `string` (JSON) | No | Up to 100 single words to boost, e.g., `["Prisma", "EMI"]`. |
| `bias_score` | `string` / `float`| No | Word boosting weight (e.g., `1.0`). |

### Response JSON Structure (HTTP 200)
```json
{
  "success": true,
  "request_id": "req_abc123",
  "transcript": "नमस्ते, आप कैसे हैं?",
  "model": "prisma-v2.5",
  "processing_time": 0.14,
  "end_to_end_latency": 0.17,
  "output": {
    "literal": "नमस्ते, आप कैसे हैं?"
  }
}
```
*(If the audio hits a token limit, `"truncated": true` is included).*

### Confidence & Language Return Fields
- **Confidence Score:** **UNKNOWN — VERIFY IN DASHBOARD** (No confidence score field is returned or documented in the REST STT v2.5 response schema).
- **Detected Language Code:** **UNKNOWN — VERIFY IN DASHBOARD** / **Not Returned** (The `detected_language_code` field is documented strictly for Prisma v3.0 when using `indic-auto` or multi-language hints; Prisma v2.5 requires an explicit `language_code` and does not return language detection metadata).

---

## 3. Gnani Evon v3.3 (Reasoning / LLM)

- **Hosting & Availability:** Evon v3.3 is an **open-weight foundation model released on Hugging Face** (`gnani-ai/evon-v3.3-30B-A3B`), not a hosted SaaS API on `gnani.ai` or `api.vachana.ai`.
- **Inference Setup:**
  - Because Gnani does not offer a direct managed SaaS endpoint for Evon under the Vachana API key, Evon must be self-hosted (or run via vLLM, Ollama, Hugging Face Inference Endpoints, or any OpenAI-compatible server).
  - Client applications interact with Evon via an OpenAI-compatible `/v1/chat/completions` API by configuring:
    - `EVON_BASE_URL`: Base URL of your self-hosted inference server (e.g., `http://localhost:8000` or cloud endpoint).
    - `EVON_MODEL`: Model ID (e.g., `gnani/gnani-evon-v3.3-30B-A3B`).
  - **Local Development / Offline Mode:** When self-hosted inference compute is not available, use `DEMO_OFFLINE_MODE=1` to run deterministic fixture-backed extraction without requiring GPU resources or remote LLM calls.

---

## 4. Gnani Timbre v2.5 (Text-to-Speech — TTS)

### REST Endpoint
- **URL:** `POST https://api.vachana.ai/api/v1/tts/inference`
- **Content-Type:** `application/json`

### Model Identifier
- **Model String:** `"model": "timbre-v2.5"` *(Required)*

### Voices
- **Catalog Size:** 42 voices available for Timbre v2.5.
- **Voice Compatibility Rule:** Voices are model-specific. Timbre v2.5 voices cannot be used with Timbre v3.0, and vice versa (will result in HTTP 400 Bad Request).
- **Representative Voices:**
  - **Hindi (`hi-IN`):** `Nalini` (popular default female), `Bhavna`, `Yashvi`, `Urmila`, `Jwala`, `Chitra`, `Ambuja`, `Deepak` (male), `Roop`, `Kabir`
  - **Indian English (`en-IN`):** `Kaveri`, `Trupti`, `Devika`, `Pranav`, `Shlok`, `Girish`
  - **Hinglish (`hi-en`):** `Poorvi`
  - *(Full voice list by language available in dashboard)*

### `audio_config` Schema
The `audio_config` object controls format, sample rate, channels, and encoding:

| Field | Type | Default | Supported Values / Notes |
| :--- | :--- | :--- | :--- |
| `sample_rate` | `integer` | `48000` | `8000`, `16000`, `22050`, `24000`, `44100`, `48000` |
| `num_channels` | `integer` | `1` | `1` (Mono) |
| `sample_width` | `integer` | `2` | `2` (16-bit audio) |
| `encoding` | `string` | `"linear_pcm"` | `"linear_pcm"`, `"pcm_s16le"`, `"pcm_mulaw"`, `"pcm_alaw"`, `"oggopus"` |
| `container` | `string` | `"wav"` | `"wav"` (with header), `"raw"` (headerless), `"mp3"`, `"ogg"`, `"mulaw"` (forces 8kHz), `"alaw"` (forces 8kHz) |
| `bitrate` | `string` | `"128k"` | Only used when `container="mp3"`. Values: `"32k"`, `"64k"`, `"96k"`, `"128k"`, `"192k"` |

### Request Payload Example
```json
{
  "text": "नमस्ते, आप कैसे हैं?",
  "voice": "Nalini",
  "model": "timbre-v2.5",
  "language": "hi-IN",
  "speed": 1.0,
  "audio_config": {
    "sample_rate": 48000,
    "num_channels": 1,
    "sample_width": 2,
    "encoding": "linear_pcm",
    "container": "wav"
  }
}
```
*(Note: `speed` ranges from `0.85` to `1.15`, or aliases `"slow"`, `"medium"`, `"fast"`).*

### Binary WAV Output Handling
- **HTTP Response:** The endpoint returns the audio directly as raw binary bytes in the response body.
- **Content-Type:** `audio/wav` (when `container="wav"`).
- **Handling in Code:**
  - **cURL:** Direct output flag `--output response.wav`.
  - **Python (`requests`):**
    ```python
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        with open("output.wav", "wb") as f:
            f.write(response.content)
    ```
  - **Node.js:** Stream directly or call `await response.arrayBuffer()` and write buffer to disk.

---

## 5. Rate Limits & Data Retention

### Rate Limits
- **Account Quotas:** Current request-rate limits (RPM/RPS) and concurrent session caps are provisioned per organization tier and displayed in the user console at `https://app.gnani.ai`. Numeric baseline tiers are **UNKNOWN — VERIFY IN DASHBOARD**.
- **Concurrency Bottlenecks:** Certain account tiers restrict accounts to a single active synchronous request at a time.
- **HTTP 429 Format:**
  ```json
  {
    "detail": {
      "error_code": "RATE_LIMITED",
      "message": "Only 1 active request is allowed at a time. Wait for your current request to finish before sending another.",
      "status_code": 429
    }
  }
  ```
- **Retry Policy:** The API does **not** provide a `Retry-After` header. Clients must implement exponential backoff with jitter upon receiving HTTP 429.

### Data Retention
- **Data Retention & Privacy Policy:** **UNKNOWN — VERIFY IN DASHBOARD** (The official API documentation does not disclose data-at-rest retention periods, logging duration, or zero-data-retention compliance flags for audio or transcripts).
