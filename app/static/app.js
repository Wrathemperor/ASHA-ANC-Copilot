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
    "interaction-help", "visit-state", "weeks-input", "bp-sys-input", "bp-dia-input",
    "symptoms-matrix", "incomplete-warning", "gap-chips", "save-manual-button",
    "readback-card", "conflict-list", "readback-numbers", "confirm-button",
    "correction-button", "manual-edit-hint", "referral-card", "referral-heading",
    "referral-details", "rule-details", "final-incomplete", "new-visit-button",
  ].forEach((id) => { elements[id] = document.getElementById(id); });
}

function setMicState(state, statusText) {
  elements["mic-state"].textContent = state;
  elements["audio-status"].textContent = statusText;
  elements["mic-button"].classList.toggle("listening", state === "LISTENING");
  elements["recording-wave"].classList.toggle("active", state === "LISTENING");
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
  elements["interaction-card"].hidden = !data?.prompt_text;
  elements["prompt-text"].textContent = data?.prompt_text || "";
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
  setMicState("PROCESSING", endpoint === "turn1"
    ? "Transcribing via Prisma and extracting with Evon..."
    : "Transcribing your response and updating the register...");
  const form = new FormData();
  form.append("audio", blob, "visit.wav");
  await withBusy(async () => {
    updateSession(await apiRequest(`/api/session/${encodeURIComponent(sessionId)}/${endpoint}`, {
      method: "POST", body: form,
    }));
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
  elements["confirm-button"].addEventListener("click", submitManualEdits);
  elements["save-manual-button"].addEventListener("click", submitManualEdits);
  elements["correction-button"].addEventListener("click", () => {
    setMicState("IDLE", sessionData?.state === "READBACK_ACTIVE"
      ? "Tap and hold to speak your one numeric correction."
      : "The voice correction was already used. Edit the values and save.");
  });
  elements["new-visit-button"].addEventListener("click", () => withBusy(createSession));
}

document.addEventListener("DOMContentLoaded", () => {
  cacheElements();
  bindEvents();
  if (!LANGUAGES.includes(elements["language-select"].value)) elements["language-select"].value = "hi-IN";
  createSession();
});
