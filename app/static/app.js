"use strict";

const LANGUAGES = ["hi-IN", "mr-IN", "te-IN", "ta-IN", "ml-IN", "en-IN"];
const MAX_RECORDING_SECONDS = 30;
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const SAMPLE_RATE = 16000;
const SYMPTOMS = [
  ["swelling", "Swelling"],
  ["severe_headache", "Severe headache"],
  ["blurred_vision", "Blurred vision"],
  ["reduced_fetal_movement", "Reduced fetal movement"],
  ["vaginal_bleeding", "Vaginal bleeding"],
  ["convulsions", "Convulsions"],
  ["leaking_fluid", "Leaking fluid"],
  ["severe_abdominal_pain", "Severe abdominal pain"],
  ["fever", "Fever"],
  ["anemia_or_low_hb_mentioned", "Anemia / low Hb"],
  ["ifa_tablets_taken", "IFA tablets"],
  ["calcium_tablets_taken", "Calcium tablets"],
];
const FIELD_LABELS = Object.fromEntries(SYMPTOMS);
FIELD_LABELS.gestational_weeks = "Gestational weeks";
FIELD_LABELS.bp_systolic = "Systolic blood pressure";
FIELD_LABELS.bp_diastolic = "Diastolic blood pressure";
const elements = {};
let sessionId = null;
let sessionData = null;
let requestCount = 0;
let pendingManualUpdates = {};
let resolvedConflictFields = new Set();
let mediaStream = null;
let audioContext = null;
let processor = null;
let muteNode = null;
let sourceNode = null;
let recordedBuffers = [];
let recordingStartedAt = 0;
let timerInterval = null;
let recording = false;
let uploadingAudio = false;
let requestBusy = false;
let holdPointerId = null;

function cacheElements() {
  [
    "session-badge", "language-select", "api-counter", "mic-button", "mic-state",
    "audio-status", "recording-wave", "recording-timer", "microphone-error",
    "upload-audio-button", "audio-file-input", "demo-mode-banner",
    "interaction-card", "prompt-text", "prompt-audio", "replay-button",
    "clarify-button", "interaction-prompts-container", "original-question-box",
    "original-question-label", "original-question-field", "original-question-text",
    "clarification-box", "clarification-reason-tag", "clarification-text", "default-prompt-bubble",
    "interaction-help", "visit-state", "weeks-input", "bp-sys-input", "bp-dia-input",
    "symptoms-matrix", "incomplete-warning", "gap-chips", "save-manual-button",
    "readback-card", "conflict-list", "readback-numbers", "confirm-button",
    "correction-button", "manual-edit-hint", "referral-card", "referral-heading",
    "referral-details", "rule-details", "final-incomplete", "new-visit-button",
    "patient-select", "add-patient-btn", "network-pill", "network-text",
    "sync-queue-btn", "queue-count", "patient-banner", "banner-patient-name",
    "banner-patient-rch", "banner-patient-meta", "patient-timeline",
    "weight-input", "hb-input", "view-referral-slip-btn", "save-to-db-btn",
    "register-modal", "close-reg-modal", "cancel-reg-btn", "register-mother-form",
    "reg-rch", "reg-name", "reg-age", "reg-village", "reg-edd",
    "referral-slip-modal", "close-slip-modal", "print-slip-btn",
    "slip-patient-name", "slip-patient-rch", "slip-patient-age-village",
    "slip-patient-edd", "slip-badge", "slip-flag-text", "slip-weeks",
    "slip-bp", "slip-weight", "slip-hb", "slip-danger-list", "slip-rule-list",
    "slip-qr-box", "slip-qr-payload", "slip-date",
    "processing-shimmer-container", "shimmer-row-1", "shimmer-row-2", "shimmer-row-3",
    "banner-risk-container", "banner-risk-pill", "banner-risk-badge", "banner-sparkline-box",
    "audit-trail-card", "audit-transcripts-container",
  ].forEach((id) => { elements[id] = document.getElementById(id); });
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderTextShimmerWave(targetElement, text, baseColor = "#64748b", shimmerColor = "#2563eb", duration = 1.4, spread = 1.0) {
  if (!targetElement) return;
  targetElement.replaceChildren();
  const wrapper = document.createElement("span");
  wrapper.className = "text-shimmer-wave";

  const chars = text.split("");
  chars.forEach((char, index) => {
    const span = document.createElement("span");
    span.className = "text-shimmer-wave-char";
    span.style.setProperty("--char-base-color", baseColor);
    span.style.setProperty("--char-shimmer-color", shimmerColor);
    const delay = (index * duration) / (chars.length * spread);
    span.style.setProperty("--char-delay", `${delay.toFixed(3)}s`);
    span.textContent = char === " " ? "\u00A0" : char;
    wrapper.appendChild(span);
  });
  targetElement.appendChild(wrapper);
}

function showProcessingShimmer(active) {
  const container = elements["processing-shimmer-container"];
  if (!container) return;
  if (!active) {
    container.hidden = true;
    return;
  }
  container.hidden = false;

  // Row 1: Reading audio (#64748b base, #2563eb blue shimmer)
  const r1 = elements["shimmer-row-1"];
  if (r1 && !r1.hasChildNodes()) {
    const dot1 = document.createElement("span");
    dot1.className = "shimmer-dot pulse-blue";
    r1.appendChild(dot1);
    const textNode1 = document.createElement("span");
    renderTextShimmerWave(textNode1, "Reading visit audio...", "#64748b", "#2563eb");
    r1.appendChild(textNode1);
  }

  // Row 2: Transcribing speech (#64748b base, #16a34a green shimmer)
  const r2 = elements["shimmer-row-2"];
  if (r2 && !r2.hasChildNodes()) {
    const dot2 = document.createElement("span");
    dot2.className = "shimmer-dot pulse-green";
    r2.appendChild(dot2);
    const textNode2 = document.createElement("span");
    renderTextShimmerWave(textNode2, "Transcribing via Gnani Prisma v3.0...", "#64748b", "#16a34a");
    r2.appendChild(textNode2);
  }

  // Row 3: Extracting facts & rules (#64748b base, #e11d48 rose shimmer)
  const r3 = elements["shimmer-row-3"];
  if (r3 && !r3.hasChildNodes()) {
    const dot3 = document.createElement("span");
    dot3.className = "shimmer-dot pulse-rose";
    r3.appendChild(dot3);
    const textNode3 = document.createElement("span");
    renderTextShimmerWave(textNode3, "Extracting clinical facts & evaluating rules...", "#64748b", "#e11d48");
    r3.appendChild(textNode3);
  }
}

function setMicState(state, statusText) {
  elements["mic-state"].textContent = state;
  elements["audio-status"].textContent = statusText;
  elements["mic-button"].classList.toggle("listening", state === "LISTENING");
  elements["recording-wave"].classList.toggle("active", state === "LISTENING");
  showProcessingShimmer(state === "PROCESSING");
}

async function apiRequest(url, options = {}, countRequest = true) {
  if (countRequest) {
    requestCount += 1;
    elements["api-counter"].textContent = `Session requests: ${requestCount}`;
  }
  const response = await fetch(url, options);
  let payload;
  try { payload = await response.json(); } catch { payload = {}; }
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status}).`);
  return payload;
}

async function createSession(retryCount = 0) {
  elements["microphone-error"].textContent = "";
  setMicState("PROCESSING", "Starting an in-memory visit session...");
  elements["mic-button"].disabled = true;
  requestCount = 0;
  elements["api-counter"].textContent = "Session requests: 0";
  sessionId = null;
  sessionData = null;
  pendingManualUpdates = {};
  resolvedConflictFields = new Set();
  renderSession(null);
  try {
    const health = await apiRequest("/health", {}, false);
    elements["demo-mode-banner"].hidden = !health.demo_offline;
    const created = await apiRequest("/api/session/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language: elements["language-select"].value }),
    });
    sessionId = created.session_id;
    elements["session-badge"].textContent = "Session active";
    elements["session-badge"].setAttribute("aria-label", `Active session ${sessionId}`);
    elements["mic-button"].disabled = false;
    setMicState("IDLE", "Tap and hold to speak your visit note.");
    await refreshSession();
  } catch (error) {
    if (retryCount < 2) {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      return createSession(retryCount + 1);
    }
    elements["session-badge"].textContent = "Session unavailable";
    elements["microphone-error"].textContent = error.message;
    setMicState("IDLE", "Could not start a visit session.");
  }
}

async function refreshSession() {
  if (sessionId) updateSession(await apiRequest(`/api/session/${encodeURIComponent(sessionId)}`));
}

function updateSession(nextSession) {
  const previousAudio = sessionData?.audio_playback_b64;
  const previousPrompt = sessionData?.prompt_text;
  sessionData = nextSession;
  renderSession(nextSession);
  if (nextSession.audio_playback_b64
      && (nextSession.audio_playback_b64 !== previousAudio || nextSession.prompt_text !== previousPrompt)) {
    playPrompt(nextSession.audio_playback_b64);
  }
  if (nextSession.state === "FOLLOWUP_ACTIVE") {
    setMicState("SPEAKING", "Listen to the question, then tap and hold to answer.");
  } else if (nextSession.state === "READBACK_ACTIVE") {
    setMicState("SPEAKING", "Check the numbers, then confirm or speak one correction.");
  } else if (nextSession.state === "PROCESSING_TURN1") {
    setMicState("PROCESSING", "Transcribing via Prisma...");
  } else if (nextSession.state === "HALT_REPEAT") {
    setMicState("IDLE", "Please repeat the visit note clearly.");
  } else if (nextSession.state === "FINAL_LOCKED" || nextSession.state === "EMERGENCY_HALT") {
    setMicState("IDLE", "This visit is locked. Start a new visit when ready.");
    elements["mic-button"].disabled = true;
  } else if (nextSession.state === "MANUAL_EDIT_REQUIRED") {
    setMicState("IDLE", "Review the register and use the on-screen edit card.");
    elements["mic-button"].disabled = true;
  } else {
    setMicState("IDLE", "Tap and hold to speak.");
  }
}

function playPrompt(encodedAudio) {
  const audio = elements["prompt-audio"];
  audio.src = `data:audio/wav;base64,${encodedAudio}`;
  audio.play().catch(() => {
    elements["interaction-help"].textContent = "Audio could not autoplay. Use Replay or read the text below.";
  });
}

function safeText(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = value;
  return node;
}

function renderSession(data) {
  renderSymptoms(data?.record || {});
  renderGaps(data?.evaluation || null);
  elements["visit-state"].textContent = data ? data.state.replaceAll("_", " ") : "Waiting for visit";
  elements["save-manual-button"].disabled = !data || ["IDLE", "PROCESSING_TURN1"].includes(data.state);
  const hasPrompt = Boolean(data?.prompt_text || data?.original_question || data?.clarification_text);
  elements["interaction-card"].hidden = !hasPrompt;

  const originalQ = data?.original_question || (data?.state === "FOLLOWUP_ACTIVE" ? data?.prompt_text : null);
  const clarifyText = data?.clarification_text;

  if (originalQ) {
    if (elements["original-question-box"]) elements["original-question-box"].hidden = false;
    if (elements["original-question-text"]) elements["original-question-text"].textContent = originalQ;
    const gapField = data?.current_gap_field || (data?.asked_gap_fields ? data.asked_gap_fields[data.asked_gap_fields.length - 1] : null);
    if (gapField && FIELD_LABELS[gapField]) {
      if (elements["original-question-field"]) {
        elements["original-question-field"].textContent = FIELD_LABELS[gapField];
        elements["original-question-field"].hidden = false;
      }
    } else if (elements["original-question-field"]) {
      elements["original-question-field"].hidden = true;
    }
    if (elements["original-question-label"]) {
      elements["original-question-label"].textContent = `FOLLOW-UP QUESTION ${data?.followup_turn_count ? "#" + (data.followup_turn_count + 1) : ""}`;
    }

    // Clarification box (Rendered below the original question box, never replacing it):
    if (clarifyText && elements["clarification-box"]) {
      elements["clarification-box"].hidden = false;
      if (elements["clarification-text"]) elements["clarification-text"].textContent = clarifyText;
      if (elements["clarification-reason-tag"]) {
        elements["clarification-reason-tag"].textContent = data?.halt_reason || "Clarification needed";
      }
    } else if (elements["clarification-box"]) {
      elements["clarification-box"].hidden = true;
    }

    if (elements["default-prompt-bubble"]) elements["default-prompt-bubble"].hidden = true;
  } else if (data?.prompt_text) {
    if (elements["original-question-box"]) elements["original-question-box"].hidden = true;
    if (elements["clarification-box"]) elements["clarification-box"].hidden = true;
    if (elements["default-prompt-bubble"]) {
      elements["default-prompt-bubble"].hidden = false;
      elements["prompt-text"].textContent = data.prompt_text;
    }
  } else {
    if (elements["original-question-box"]) elements["original-question-box"].hidden = true;
    if (elements["clarification-box"]) elements["clarification-box"].hidden = true;
    if (elements["default-prompt-bubble"]) elements["default-prompt-bubble"].hidden = true;
  }

  if (elements["clarify-button"]) {
    elements["clarify-button"].disabled = !data || data.state !== "FOLLOWUP_ACTIVE" || !originalQ;
  }

  elements["interaction-help"].textContent = data?.halt_reason || "";
  elements["replay-button"].disabled = !data?.audio_playback_b64;
  elements["upload-audio-button"].disabled = !data
    || ["FINAL_LOCKED", "EMERGENCY_HALT", "MANUAL_EDIT_REQUIRED"].includes(data.state);
  elements["readback-card"].hidden = !data || !["READBACK_ACTIVE", "MANUAL_EDIT_REQUIRED"].includes(data.state);
  const unresolvedConflicts = (data?.conflicts || []).some(
    (conflict) => !resolvedConflictFields.has(conflict.field),
  );
  elements["confirm-button"].disabled = unresolvedConflicts;
  elements["readback-numbers"].textContent = data
    ? `BP ${displayValue(data.record.bp_systolic)} / ${displayValue(data.record.bp_diastolic)} mmHg · ${displayValue(data.record.gestational_weeks)} weeks`
    : "—";
  renderConflicts(data?.conflicts || []);
  renderReferral(data);
  if (data) {
    setInputValue(elements["weeks-input"], data.record.gestational_weeks);
    setInputValue(elements["bp-sys-input"], data.record.bp_systolic);
    setInputValue(elements["bp-dia-input"], data.record.bp_diastolic);
    setInputValue(elements["weight-input"], data.record.weight_kg);
    setInputValue(elements["hb-input"], data.record.hemoglobin);
    if (elements["save-to-db-btn"]) {
      elements["save-to-db-btn"].disabled = data.state !== "FINAL_LOCKED" || !data.patient_id;
    }

    // Render Risk Assessment pill
    if (data.risk_assessment && elements["banner-risk-container"]) {
      const r = data.risk_assessment;
      elements["banner-risk-container"].hidden = false;
      elements["banner-risk-pill"].textContent = `Risk Score: ${r.score}/100`;
      elements["banner-risk-pill"].style.background = r.color || "#0f172a";
      elements["banner-risk-badge"].textContent = `${r.tier} RISK`;
      elements["banner-risk-badge"].style.color = r.color || "#0f172a";
    }

    // Render Audio Transcripts & Explainability Audit Card
    if (elements["audit-trail-card"] && elements["audit-transcripts-container"]) {
      const hasTranscripts = data.transcript_turn1 || (data.transcripts && data.transcripts.length);
      if (hasTranscripts && data.state !== "IDLE") {
        elements["audit-trail-card"].hidden = false;
        const list = (data.transcripts && data.transcripts.length)
          ? data.transcripts
          : [
              { turn: 1, role: "asha_visit_note", transcript: data.transcript_turn1 },
              data.transcript_turn2 ? { turn: 2, role: "followup_response", transcript: data.transcript_turn2 } : null,
            ].filter(Boolean);

        elements["audit-transcripts-container"].innerHTML = list.map((t) => `
          <div class="audit-transcript-item">
            <div class="audit-transcript-meta">
              <span>TURN ${t.turn}: ${t.role === "asha_visit_note" ? "INITIAL ASHA VOICE NOTE" : "FOLLOW-UP SPOKEN RESPONSE"}</span>
              <span>PRISMA v3.0 STT</span>
            </div>
            <p class="audit-transcript-text">“${escapeHtml(t.transcript)}”</p>
            ${t.prompt ? `<div class="audit-evidence-tag">In response to: “${escapeHtml(t.prompt)}”</div>` : ""}
          </div>
        `).join("");
      } else {
        elements["audit-trail-card"].hidden = true;
      }
    }
  }
}

function displayValue(value) {
  return value === null || value === undefined || value === "" ? "not recorded" : String(value);
}

function setInputValue(input, value) {
  if (document.activeElement !== input) input.value = value ?? "";
}

function renderSymptoms(record) {
  const container = elements["symptoms-matrix"];
  container.replaceChildren();
  SYMPTOMS.forEach(([field, label]) => {
    const row = safeText("div", "symptom-row", "");
    row.append(safeText("span", "symptom-name", label));
    const status = record[field] || "not_mentioned";
    row.append(safeText("span", `badge ${status}`, status.replaceAll("_", " ").toUpperCase()));
    if (record.evidence_spans?.[field]) row.append(safeText("p", "evidence", `“${record.evidence_spans[field]}”`));
    container.append(row);
  });
}

function renderGaps(evaluation) {
  const gaps = sessionData && !["IDLE", "PROCESSING_TURN1"].includes(sessionData.state)
    ? evaluation?.top_gaps || []
    : [];
  elements["incomplete-warning"].hidden = gaps.length === 0;
  const container = elements["gap-chips"];
  container.replaceChildren();
  gaps.forEach((field) => {
    const row = safeText("div", "gap-item", "");
    row.append(safeText("strong", "", FIELD_LABELS[field] || field.replaceAll("_", " ")));
    if (field === "gestational_weeks") {
      row.append(safeText("span", "muted", "Enter weeks in the numeric field above."));
      container.append(row);
      return;
    }
    [["present", "Present"], ["denied", "Denied"], ["not_mentioned", "Leave Unknown"]].forEach(([value, label]) => {
      const chip = safeText("button", "gap-choice", label);
      chip.type = "button";
      chip.setAttribute("aria-pressed", pendingManualUpdates[field] === value ? "true" : "false");
      chip.addEventListener("click", () => {
        pendingManualUpdates[field] = value;
        renderGaps(evaluation);
      });
      row.append(chip);
    });
    container.append(row);
  });
}

function renderConflicts(conflicts) {
  const container = elements["conflict-list"];
  container.replaceChildren();
  conflicts.forEach((conflict) => {
    const label = FIELD_LABELS[conflict.field] || conflict.field.replaceAll("_", " ");
    const warning = safeText("div", "conflict-warning", "");
    warning.append(safeText("p", "", `${label}: Turn 1 “${displayValue(conflict.turn1_value)}” · Turn 2 “${displayValue(conflict.turn2_value)}”`));
    [
      ["turn1_value", "Keep Turn 1"],
      ["turn2_value", "Use Turn 2"],
    ].forEach(([key, text]) => {
      const choose = safeText("button", "secondary-button conflict-choice", text);
      choose.type = "button";
      choose.addEventListener("click", () => {
        pendingManualUpdates[conflict.field] = conflict[key];
        resolvedConflictFields.add(conflict.field);
        renderConflicts(conflicts);
        elements["confirm-button"].disabled = conflicts.some(
          (item) => !resolvedConflictFields.has(item.field),
        );
      });
      warning.append(choose);
    });
    container.append(warning);
  });
}

function citationTitle(ruleId) {
  if (ruleId.startsWith("RULE-EMG-")) return "National Health Mission maternal safety guidance";
  if (ruleId === "RULE-HRP-01") return "PMSMA: Hypertensive disorders of pregnancy";
  if (ruleId.startsWith("RULE-HRP-")) return "PMSMA and National Health Mission ANC guidance";
  if (ruleId === "STAGE-GATE-01") return "Official ANC fetal-movement stage gate";
  return "Official ANC rule source";
}

function renderReferral(data) {
  const visible = data && ["FINAL_LOCKED", "EMERGENCY_HALT"].includes(data.state);
  elements["referral-card"].hidden = !visible;
  if (!visible) return;
  const evaluation = data.evaluation || {};
  const urgent = data.state === "EMERGENCY_HALT" || evaluation.flag === "URGENT_REFERRAL";
  const referral = evaluation.flag === "CLINICIAN_REFERRAL";
  elements["referral-card"].className = `card referral-card ${urgent ? "urgent" : referral ? "referral" : "no-trigger"}`;
  elements["referral-heading"].textContent = urgent ? "Immediate Referral to FRU / Hospital"
    : referral ? "Referral for Clinician Evaluation" : "No referral rule triggered";
  elements["referral-details"].textContent = urgent
    ? "An emergency rule was triggered. This tool does not diagnose or recommend treatment."
    : referral ? "One or more official referral rules matched the recorded information."
      : "No positive referral rule is recorded. This is not a diagnosis or guarantee of health.";
  const details = elements["rule-details"];
  details.replaceChildren();
  (evaluation.rule_ids || []).forEach((ruleId) => {
    details.append(safeText("strong", "", `Triggered by ${ruleId}: ${citationTitle(ruleId)}`));
    (evaluation.citations || []).forEach((url) => {
      const link = document.createElement("a");
      link.className = "rule-citation";
      link.href = url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = url;
      details.append(link);
    });
  });
  const remaining = evaluation.top_gaps || [];
  const warning = elements["final-incomplete"];
  warning.hidden = remaining.length === 0;
  warning.replaceChildren();
  if (remaining.length) {
    warning.append(safeText("h3", "", "Incomplete / Needs Verification"));
    warning.append(safeText("p", "", remaining.map((field) => FIELD_LABELS[field] || field).join(", ")));
  }
}

async function withBusy(work) {
  if (requestBusy) return;
  requestBusy = true;
  elements["mic-button"].disabled = true;
  elements["upload-audio-button"].disabled = true;
  try { await work(); } catch (error) {
    elements["microphone-error"].textContent = error.message;
    setMicState("IDLE", "There was a problem. Review the status and try again.");
  } finally {
    requestBusy = false;
    if (sessionData && !["FINAL_LOCKED", "EMERGENCY_HALT", "MANUAL_EDIT_REQUIRED"].includes(sessionData.state)) {
      elements["mic-button"].disabled = false;
      if (!uploadingAudio) elements["upload-audio-button"].disabled = false;
    }
  }
}

async function routeRecording(blob) {
  if (!sessionId) throw new Error("No active session.");
  const state = sessionData?.state;
  const endpoint = state === "FOLLOWUP_ACTIVE" ? "followup"
    : state === "READBACK_ACTIVE" ? "readback"
      : ["IDLE", "HALT_REPEAT"].includes(state) ? "turn1" : null;
  if (!endpoint) throw new Error("The current session is not ready for a voice response.");

  if (!navigator.onLine) {
    const currentRch = elements["patient-select"]?.value || null;
    await queueOfflineAudio(blob, endpoint, currentRch);
    return;
  }

  setMicState("PROCESSING", endpoint === "turn1"
    ? "Transcribing via Prisma and extracting with Evon..."
    : "Transcribing your response and updating the register...");
  const form = new FormData();
  form.append("audio", blob, "visit.wav");
  await withBusy(async () => {
    try {
      updateSession(await apiRequest(`/api/session/${encodeURIComponent(sessionId)}/${endpoint}`, {
        method: "POST", body: form,
      }));
    } catch (err) {
      if (!navigator.onLine || err.message.includes("Failed to fetch") || err.message.includes("offline")) {
        const currentRch = elements["patient-select"]?.value || null;
        await queueOfflineAudio(blob, endpoint, currentRch);
      } else {
        throw err;
      }
    }
  });
}

async function processUploadedAudio(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  if (recording || requestBusy || uploadingAudio || !sessionId) {
    elements["microphone-error"].textContent = "Wait for the current request or session to finish before uploading audio.";
    event.target.value = "";
    return;
  }

  let context = null;
  uploadingAudio = true;
  elements["upload-audio-button"].disabled = true;
  elements["mic-button"].disabled = true;
  elements["microphone-error"].textContent = "";
  setMicState("PROCESSING", "Decoding the selected audio clip in memory...");
  try {
    if (file.size > MAX_UPLOAD_BYTES) {
      throw new Error("Audio upload exceeds the 10 MiB limit.");
    }
    context = new AudioContext();
    const decoded = await context.decodeAudioData(await file.arrayBuffer());
    if (!decoded.length || decoded.duration <= 0) {
      throw new Error("The selected audio clip contains no audio.");
    }
    if (decoded.duration > MAX_RECORDING_SECONDS) {
      throw new Error("Choose an audio clip that is 30 seconds or shorter.");
    }
    const mono = downmixAudioBuffer(decoded);
    const wav = encodeWav(resample([mono], decoded.sampleRate, SAMPLE_RATE), SAMPLE_RATE);
    await context.close();
    context = null;
    elements["recording-timer"].textContent = "00:00 / 00:30";
    await routeRecording(wav);
  } catch (error) {
    elements["microphone-error"].textContent = `Audio upload failed: ${error.message}`;
    setMicState("IDLE", "Choose a supported .mp3 or .wav clip and try again.");
  } finally {
    if (context && context.state !== "closed") await context.close().catch(() => {});
    uploadingAudio = false;
    const terminal = sessionData
      && ["FINAL_LOCKED", "EMERGENCY_HALT", "MANUAL_EDIT_REQUIRED"].includes(sessionData.state);
    elements["mic-button"].disabled = Boolean(terminal);
    elements["upload-audio-button"].disabled = Boolean(terminal);
    event.target.value = "";
  }
}

function downmixAudioBuffer(audioBuffer) {
  if (audioBuffer.numberOfChannels < 1) {
    throw new Error("The selected audio clip has no audio channels.");
  }
  const mono = new Float32Array(audioBuffer.length);
  for (let channel = 0; channel < audioBuffer.numberOfChannels; channel += 1) {
    const samples = audioBuffer.getChannelData(channel);
    for (let index = 0; index < samples.length; index += 1) {
      mono[index] += samples[index] / audioBuffer.numberOfChannels;
    }
  }
  return mono;
}

async function beginRecording(event) {
  event.preventDefault();
  if (recording || uploadingAudio || requestBusy || !sessionId) return;
  elements["microphone-error"].textContent = "";
  if (!navigator.mediaDevices?.getUserMedia) {
    elements["microphone-error"].textContent = "Microphone recording is not available in this browser context.";
    return;
  }
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 }, video: false });
    audioContext = new AudioContext();
    sourceNode = audioContext.createMediaStreamSource(mediaStream);
    processor = audioContext.createScriptProcessor(4096, 1, 1);
    muteNode = audioContext.createGain();
    muteNode.gain.value = 0;
    recordedBuffers = [];
    processor.onaudioprocess = (audioEvent) => {
      if (recording) recordedBuffers.push(new Float32Array(audioEvent.inputBuffer.getChannelData(0)));
    };
    sourceNode.connect(processor);
    processor.connect(muteNode);
    muteNode.connect(audioContext.destination);
    recording = true;
    holdPointerId = event.pointerId;
    recordingStartedAt = Date.now();
    if (Number.isInteger(event.pointerId)) elements["mic-button"].setPointerCapture?.(event.pointerId);
    setMicState("LISTENING", "Listening… release to send, maximum 30 seconds.");
    timerInterval = window.setInterval(updateTimer, 100);
    updateTimer();
  } catch (error) {
    cleanupRecorder();
    elements["microphone-error"].textContent = `Microphone permission or device error: ${error.message}`;
    setMicState("IDLE", "Allow microphone access, then try again.");
  }
}

function updateTimer() {
  if (!recording) return;
  const elapsed = Math.min((Date.now() - recordingStartedAt) / 1000, MAX_RECORDING_SECONDS);
  const seconds = Math.floor(elapsed);
  elements["recording-timer"].textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")} / 00:30`;
  if (elapsed >= MAX_RECORDING_SECONDS) finishRecording();
}

async function finishRecording() {
  if (!recording) return;
  recording = false;
  if (timerInterval) window.clearInterval(timerInterval);
  timerInterval = null;
  const buffers = recordedBuffers;
  const context = audioContext;
  cleanupRecorder(false);
  if (!buffers.length || !context) {
    elements["microphone-error"].textContent = "No audio was captured. Please try again.";
    setMicState("IDLE", "Tap and hold to speak.");
    return;
  }
  try {
    const blob = encodeWav(resample(buffers, context.sampleRate, SAMPLE_RATE), SAMPLE_RATE);
    await context.close();
    await routeRecording(blob);
  } catch (error) {
    elements["microphone-error"].textContent = error.message;
    setMicState("IDLE", "Recording could not be sent.");
  } finally {
    elements["recording-timer"].textContent = "00:00 / 00:30";
    elements["mic-button"].classList.remove("listening");
  }
}

function cleanupRecorder(closeContext = true) {
  if (processor) { processor.disconnect(); processor.onaudioprocess = null; }
  if (muteNode) muteNode.disconnect();
  if (sourceNode) sourceNode.disconnect();
  if (mediaStream) mediaStream.getTracks().forEach((track) => track.stop());
  if (closeContext && audioContext && audioContext.state !== "closed") audioContext.close().catch(() => {});
  processor = null;
  muteNode = null;
  sourceNode = null;
  mediaStream = null;
  audioContext = null;
}

function resample(buffers, sourceRate, targetRate) {
  const input = new Float32Array(buffers.reduce((sum, buffer) => sum + buffer.length, 0));
  let offset = 0;
  buffers.forEach((buffer) => { input.set(buffer, offset); offset += buffer.length; });
  if (sourceRate === targetRate) return input;
  const ratio = sourceRate / targetRate;
  const output = new Float32Array(Math.floor(input.length / ratio));
  for (let index = 0; index < output.length; index += 1) {
    const start = Math.floor(index * ratio);
    const end = Math.min(Math.floor((index + 1) * ratio), input.length);
    let total = 0;
    for (let sample = start; sample < end; sample += 1) total += input[sample];
    output[index] = end > start ? total / (end - start) : input[start] || 0;
  }
  return output;
}

function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeString = (offset, value) => {
    for (let index = 0; index < value.length; index += 1) view.setUint8(offset + index, value.charCodeAt(index));
  };
  writeString(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, samples.length * 2, true);
  for (let index = 0; index < samples.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, samples[index]));
    view.setInt16(44 + index * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}

async function submitManualEdits() {
  if (!sessionId) return;
  if ((sessionData?.conflicts || []).some((conflict) => !resolvedConflictFields.has(conflict.field))) {
    elements["interaction-help"].textContent = "Choose which value to keep for every Turn 1 / Turn 2 conflict before finalizing.";
    return;
  }
  const updates = {
    ...pendingManualUpdates,
    gestational_weeks: numberOrNull(elements["weeks-input"].value),
    bp_systolic: numberOrNull(elements["bp-sys-input"].value),
    bp_diastolic: numberOrNull(elements["bp-dia-input"].value),
    weight_kg: numberOrNull(elements["weight-input"].value),
    hemoglobin: numberOrNull(elements["hb-input"].value),
  };
  Object.keys(updates).forEach((key) => {
    if (updates[key] === null && pendingManualUpdates[key] === undefined) delete updates[key];
  });
  await withBusy(async () => {
    const result = await apiRequest(`/api/session/${encodeURIComponent(sessionId)}/manual-edit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
    pendingManualUpdates = {};
    resolvedConflictFields = new Set();
    updateSession(result);
  });
}

// -------------------------------------------------------------
// Phase 1: Offline-First Queue (IndexedDB)
// -------------------------------------------------------------
const OFFLINE_DB_NAME = "AshaAncOfflineDB";
const OFFLINE_STORE = "offline_visits";

function getOfflineDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(OFFLINE_DB_NAME, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(OFFLINE_STORE)) {
        db.createObjectStore(OFFLINE_STORE, { keyPath: "id", autoIncrement: true });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function queueOfflineAudio(blob, endpoint, rchId) {
  try {
    const db = await getOfflineDB();
    const tx = db.transaction(OFFLINE_STORE, "readwrite");
    tx.objectStore(OFFLINE_STORE).add({
      blob,
      endpoint,
      rchId,
      language: elements["language-select"]?.value || "hi-IN",
      timestamp: new Date().toISOString(),
    });
    await new Promise((res) => { tx.oncomplete = res; });
    updateNetworkStatus();
    setMicState("IDLE", "Offline: visit recording saved to device queue. Tap Sync Queue when connected.");
  } catch (err) {
    console.error("Failed to queue offline visit:", err);
  }
}

async function getQueuedCount() {
  try {
    const db = await getOfflineDB();
    const tx = db.transaction(OFFLINE_STORE, "readonly");
    return new Promise((res) => {
      const countReq = tx.objectStore(OFFLINE_STORE).count();
      countReq.onsuccess = () => res(countReq.result);
      countReq.onerror = () => res(0);
    });
  } catch {
    return 0;
  }
}

async function syncOfflineQueue() {
  const count = await getQueuedCount();
  if (!count) return;
  setMicState("PROCESSING", `Syncing ${count} queued visit(s) to server...`);
  try {
    const db = await getOfflineDB();
    const tx = db.transaction(OFFLINE_STORE, "readwrite");
    const store = tx.objectStore(OFFLINE_STORE);
    const getAllReq = store.getAll();
    getAllReq.onsuccess = async () => {
      const items = getAllReq.result;
      for (const item of items) {
        try {
          const start = await apiRequest("/api/session/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ language: item.language }),
          });
          if (item.rchId) {
            await apiRequest(`/api/session/${start.session_id}/link-patient`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ rch_id: item.rchId }),
            });
          }
          const form = new FormData();
          form.append("audio", item.blob, "visit.wav");
          const res = await apiRequest(`/api/session/${start.session_id}/turn1`, {
            method: "POST",
            body: form,
          });
          sessionId = start.session_id;
          updateSession(res);
        } catch (e) {
          console.error("Queue item sync error:", e);
        }
      }
      const clearTx = db.transaction(OFFLINE_STORE, "readwrite");
      clearTx.objectStore(OFFLINE_STORE).clear();
      clearTx.oncomplete = () => {
        updateNetworkStatus();
        setMicState("IDLE", "Queued visits synchronized successfully!");
      };
    };
  } catch (e) {
    setMicState("IDLE", `Sync failed: ${e.message}`);
  }
}

async function updateNetworkStatus() {
  const isOnline = navigator.onLine;
  if (elements["network-pill"]) {
    elements["network-pill"].className = `network-pill ${isOnline ? "online" : "offline"}`;
  }
  if (elements["network-text"]) {
    elements["network-text"].textContent = isOnline ? "Online" : "Offline";
  }
  const count = await getQueuedCount();
  if (elements["sync-queue-btn"]) {
    elements["sync-queue-btn"].hidden = count === 0;
  }
  if (elements["queue-count"]) {
    elements["queue-count"].textContent = String(count);
  }
}

// -------------------------------------------------------------
// Phase 2: Patient Selector & History Timeline
// -------------------------------------------------------------
async function loadPatientList(selectRch = null) {
  try {
    const list = await apiRequest("/api/patients", {}, false);
    const sel = elements["patient-select"];
    if (!sel) return;
    sel.innerHTML = '<option value="">Select registered mother...</option>';
    list.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.rch_id;
      opt.textContent = `${p.name} (RCH: ${p.rch_id})${p.village ? " · " + p.village : ""}`;
      sel.appendChild(opt);
    });
    if (selectRch) {
      sel.value = selectRch;
      await onSelectPatient(selectRch);
    }
  } catch (e) {
    console.error("loadPatientList error:", e);
  }
}

async function onSelectPatient(rchId) {
  if (!rchId) {
    elements["patient-banner"].hidden = true;
    return;
  }
  try {
    const data = await apiRequest(`/api/patients/${encodeURIComponent(rchId)}/history`, {}, false);
    const p = data.patient;
    elements["banner-patient-name"].textContent = p.name;
    elements["banner-patient-rch"].textContent = `RCH: ${p.rch_id}`;
    elements["banner-patient-meta"].textContent = `Age: ${p.age || "—"} | Village: ${p.village || "—"} | EDD: ${p.edd || "—"}`;
    elements["patient-banner"].hidden = false;

    // Render longitudinal timeline chips
    const timeline = elements["patient-timeline"];
    timeline.replaceChildren();
    const visits = data.visits || [];
    visits.forEach((v) => {
      const chip = document.createElement("div");
      chip.className = `timeline-chip ${v.referral_flag ? "flagged" : ""}`;
      const title = document.createElement("span");
      title.className = "chip-title";
      title.textContent = `Visit ${v.visit_number} (${v.gestational_weeks || "—"} wks)`;
      const vitals = document.createElement("span");
      vitals.className = "chip-vitals";
      vitals.textContent = `BP ${v.bp_systolic || "—"}/${v.bp_diastolic || "—"}${v.weight_kg ? " · " + v.weight_kg + "kg" : ""}`;
      chip.append(title, vitals);
      timeline.append(chip);
    });

    if (visits.length > 0) {
      const latest = visits[visits.length - 1];
      if (latest.risk_score !== null && latest.risk_score !== undefined && elements["banner-risk-container"]) {
        elements["banner-risk-container"].hidden = false;
        elements["banner-risk-pill"].textContent = `Risk Score: ${latest.risk_score}/100`;
        const tier = latest.risk_tier || (latest.risk_score >= 60 ? "HIGH" : latest.risk_score >= 30 ? "MODERATE" : "LOW");
        const color = tier === "HIGH" ? "#ef4444" : tier === "MODERATE" ? "#f59e0b" : "#10b981";
        elements["banner-risk-pill"].style.background = color;
        elements["banner-risk-badge"].textContent = `${tier} RISK`;
        elements["banner-risk-badge"].style.color = color;
      }
    } else if (elements["banner-risk-container"]) {
      elements["banner-risk-container"].hidden = true;
    }

    // Link patient to active session if session exists
    if (sessionId) {
      const updated = await apiRequest(`/api/session/${encodeURIComponent(sessionId)}/link-patient`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rch_id: rchId }),
      });
      updateSession(updated);
    }
  } catch (err) {
    console.error("Error loading patient history:", err);
  }
}

// -------------------------------------------------------------
// Referral Slip View & Modal
// -------------------------------------------------------------
async function openReferralSlip() {
  if (!sessionId) return;
  try {
    const slip = await apiRequest(`/api/session/${encodeURIComponent(sessionId)}/referral-slip`, {}, false);
    const p = slip.patient || {};
    elements["slip-patient-name"].textContent = p.name || "Expectant Mother (Unlinked)";
    elements["slip-patient-rch"].textContent = p.rch_id || "Unregistered / Walk-in";
    elements["slip-patient-age-village"].textContent = `${p.age ? p.age + " yrs" : "—"} · ${p.village || "—"}`;
    elements["slip-patient-edd"].textContent = p.edd || "Not recorded";

    const isUrgent = slip.emergency_bypass || slip.referral_flag === "URGENT_REFERRAL";
    elements["slip-badge"].className = `slip-referral-banner ${isUrgent ? "urgent" : "clinician"}`;
    elements["slip-flag-text"].textContent = isUrgent
      ? "EMERGENCY: IMMEDIATE REFERRAL TO FRU / HOSPITAL"
      : "CLINICIAN REFERRAL REQUIRED";

    const v = slip.vitals || {};
    elements["slip-weeks"].textContent = displayValue(v.gestational_weeks);
    elements["slip-bp"].textContent = v.bp_systolic && v.bp_diastolic ? `${v.bp_systolic}/${v.bp_diastolic}` : "—";
    elements["slip-weight"].textContent = displayValue(v.weight_kg);
    elements["slip-hb"].textContent = displayValue(v.hemoglobin);

    // Dangers
    const dangerList = elements["slip-danger-list"];
    dangerList.replaceChildren();
    const record = sessionData?.record || {};
    const evidenceSpans = slip.evidence_spans || {};
    let dangerFound = false;
    SYMPTOMS.forEach(([field, label]) => {
      if (record[field] === "present") {
        dangerFound = true;
        const item = document.createElement("div");
        item.className = "slip-danger-item";
        const title = document.createElement("span");
        title.className = "slip-danger-title";
        title.textContent = `⚠️ ${label} (Present)`;
        item.appendChild(title);
        if (evidenceSpans[field]) {
          const ev = document.createElement("span");
          ev.className = "slip-danger-evidence";
          ev.textContent = `“${evidenceSpans[field]}”`;
          item.appendChild(ev);
        }
        dangerList.appendChild(item);
      }
    });
    if (!dangerFound) {
      dangerList.textContent = "No acute danger symptoms marked as present.";
    }

    // Rules
    const ruleList = elements["slip-rule-list"];
    ruleList.replaceChildren();
    (slip.rule_ids || []).forEach((ruleId) => {
      const r = document.createElement("div");
      r.style.fontSize = "11px";
      r.style.marginBottom = "3px";
      r.innerHTML = `<strong>${ruleId}</strong>: ${citationTitle(ruleId)}`;
      ruleList.appendChild(r);
    });

    elements["slip-qr-payload"].textContent = slip.qr_code_data;
    elements["slip-date"].textContent = `Generated: ${new Date().toLocaleDateString("en-IN")}`;
    elements["referral-slip-modal"].hidden = false;
  } catch (err) {
    alert("Could not load referral slip: " + err.message);
  }
}

async function saveCurrentVisitToDb() {
  if (!sessionId) return;
  try {
    const res = await apiRequest(`/api/session/${encodeURIComponent(sessionId)}/save-to-db`, {
      method: "POST",
    });
    if (res.status === "ok") {
      alert(`Visit successfully saved to mother's record (Visit #${res.saved_visit.visit_number})!`);
      const sel = elements["patient-select"];
      if (sel?.value) onSelectPatient(sel.value);
    }
  } catch (err) {
    alert("Error saving visit to database: " + err.message);
  }
}

function numberOrNull(value) { return value === "" ? null : Number(value); }

function bindEvents() {
  elements["language-select"].addEventListener("change", () => withBusy(createSession));
  elements["upload-audio-button"].addEventListener("click", () => elements["audio-file-input"].click());
  elements["audio-file-input"].addEventListener("change", processUploadedAudio);
  elements["mic-button"].addEventListener("pointerdown", beginRecording);
  elements["mic-button"].addEventListener("pointerup", (event) => {
    if (holdPointerId === event.pointerId) finishRecording();
  });
  elements["mic-button"].addEventListener("pointercancel", finishRecording);
  elements["mic-button"].addEventListener("lostpointercapture", finishRecording);
  elements["mic-button"].addEventListener("keydown", (event) => {
    if ((event.key === " " || event.key === "Enter") && !event.repeat) beginRecording(event);
  });
  elements["mic-button"].addEventListener("keyup", (event) => {
    if (event.key === " " || event.key === "Enter") finishRecording();
  });
  elements["replay-button"].addEventListener("click", () => {
    if (sessionData?.audio_playback_b64) playPrompt(sessionData.audio_playback_b64);
  });
  elements["clarify-button"]?.addEventListener("click", async () => {
    if (!sessionId || sessionData?.state !== "FOLLOWUP_ACTIVE") return;
    await withBusy(async () => {
      const res = await apiRequest(`/api/session/${encodeURIComponent(sessionId)}/clarify`, {
        method: "POST",
      });
      updateSession(res);
    });
  });
  elements["confirm-button"].addEventListener("click", submitManualEdits);
  elements["save-manual-button"].addEventListener("click", submitManualEdits);
  elements["correction-button"].addEventListener("click", () => {
    setMicState("IDLE", sessionData?.state === "READBACK_ACTIVE"
      ? "Tap and hold to speak your one numeric correction."
      : "The voice correction was already used. Edit the values and save.");
  });
  elements["new-visit-button"].addEventListener("click", () => withBusy(createSession));

  // Patient & Modal Events
  elements["patient-select"]?.addEventListener("change", (e) => onSelectPatient(e.target.value));
  elements["add-patient-btn"]?.addEventListener("click", () => {
    elements["register-modal"].hidden = false;
  });
  elements["close-reg-modal"]?.addEventListener("click", () => {
    elements["register-modal"].hidden = true;
  });
  elements["cancel-reg-btn"]?.addEventListener("click", () => {
    elements["register-modal"].hidden = true;
  });
  elements["register-mother-form"]?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const rch = elements["reg-rch"].value.trim();
    const name = elements["reg-name"].value.trim();
    const age = numberOrNull(elements["reg-age"].value);
    const village = elements["reg-village"].value.trim();
    const edd = elements["reg-edd"].value;
    try {
      await apiRequest("/api/patients", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rch_id: rch, name, age, village, edd }),
      });
      elements["register-modal"].hidden = true;
      await loadPatientList(rch);
    } catch (err) {
      alert("Failed to register mother: " + err.message);
    }
  });

  // Referral Slip Modal Events
  elements["view-referral-slip-btn"]?.addEventListener("click", openReferralSlip);
  elements["close-slip-modal"]?.addEventListener("click", () => {
    elements["referral-slip-modal"].hidden = true;
  });
  elements["print-slip-btn"]?.addEventListener("click", () => {
    window.print();
  });
  elements["save-to-db-btn"]?.addEventListener("click", saveCurrentVisitToDb);
  elements["sync-queue-btn"]?.addEventListener("click", syncOfflineQueue);

  // Network Event Listeners
  window.addEventListener("online", updateNetworkStatus);
  window.addEventListener("offline", updateNetworkStatus);
}

document.addEventListener("DOMContentLoaded", () => {
  cacheElements();
  bindEvents();
  if (!LANGUAGES.includes(elements["language-select"].value)) elements["language-select"].value = "hi-IN";
  updateNetworkStatus();
  loadPatientList();
  createSession();

  // Service Worker Registration for PWA
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/service-worker.js").catch(() => {});
    });
  }
});
