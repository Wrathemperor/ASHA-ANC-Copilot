"""Multilingual spoken visit summary generation for low-literacy ASHA workers and families."""

from __future__ import annotations

import base64
from typing import Any

from app.gnani.timbre import TimbreClient
from app.session import SessionState

# Localized summary templates for low-literacy field communication
_SUMMARY_TEMPLATES: dict[str, dict[str, str]] = {
    "hi-IN": {
        "greeting": "{name}, आरसीएच आईडी {rch_id}।",
        "gestation": "गर्भावस्था {weeks} सप्ताह।",
        "bp_normal": "रक्तचाप {sys} बटा {dia} सामान्य है।",
        "bp_high": "रक्तचाप {sys} बटा {dia} अधिक है।",
        "hb_normal": "हीमोग्लोबिन {hb} ग्राम सामान्य है।",
        "hb_low": "हीमोग्लोबिन {hb} ग्राम कम है, एनीमिया के लक्षण हैं।",
        "danger_signs": "खतरे के लक्षण: {symptoms}।",
        "no_danger": "कोई गंभीर खतरे का लक्षण नहीं देखा गया।",
        "urgent_referral": "तत्काल प्राथमिक स्वास्थ्य केंद्र या जिला अस्पताल जाएं। एम्बुलेंस १०८ पर कॉल करें।",
        "clinician_referral": "चिकित्सक जांच की आवश्यकता है। कृपया अगले दो दिनों में स्वास्थ्य केंद्र जाएं।",
        "routine": "गर्भावस्था सामान्य चल रही है। आयरन और कैल्शियम की गोलियां नियमित रूप से लें।",
    },
    "en-IN": {
        "greeting": "{name}, RCH ID {rch_id}.",
        "gestation": "Pregnancy is at {weeks} weeks.",
        "bp_normal": "Blood pressure is {sys} over {dia}, which is normal.",
        "bp_high": "Blood pressure is {sys} over {dia}, which is high.",
        "hb_normal": "Hemoglobin is {hb} grams, which is normal.",
        "hb_low": "Hemoglobin is {hb} grams, indicating anemia.",
        "danger_signs": "Danger signs noted: {symptoms}.",
        "no_danger": "No severe danger signs observed.",
        "urgent_referral": "Urgent hospital referral required. Call 108 ambulance immediately.",
        "clinician_referral": "Medical officer consultation recommended within two days.",
        "routine": "Pregnancy is progressing normally. Continue daily IFA and calcium tablets.",
    },
    "mr-IN": {
        "greeting": "{name}, आरसीएच आयडी {rch_id}.",
        "gestation": "गर्भधारणा {weeks} आठवडे आहे.",
        "bp_normal": "रक्तदाब {sys} बाय {dia} सामान्य आहे.",
        "bp_high": "रक्तदाब {sys} बाय {dia} जास्त आहे.",
        "hb_normal": "हिमोग्लोबिन {hb} ग्रॅम सामान्य आहे.",
        "hb_low": "हिमोग्लोबिन {hb} ग्रॅम कमी आहे, अशक्तपणाचे लक्षण आहे.",
        "danger_signs": "धोक्याची लक्षणे: {symptoms}.",
        "no_danger": "कोणतेही गंभीर धोक्याचे लक्षण आढळले नाही.",
        "urgent_referral": "तातडीने उपजिल्हा किंवा ग्रामीण रुग्णालयात जा. रुग्णवाहिका १०८ ला कॉल करा.",
        "clinician_referral": "वैद्यकीय अधिकाऱ्यांची तपासणी आवश्यक आहे. दोन दिवसांत केंद्रात जा.",
        "routine": "गर्भधारणा सामान्य आहे. आयर्न आणि कॅल्शियमच्या गोळ्या नियमितपणे घ्या.",
    },
    "te-IN": {
        "greeting": "{name}, RCH ఐడీ {rch_id}.",
        "gestation": "గర్భధారణ {weeks} వారాలు.",
        "bp_normal": "రక్తపోటు {sys} బై {dia} సాధారణంగా ఉంది.",
        "bp_high": "రక్తపోటు {sys} బై {dia} ఎక్కువగా ఉంది.",
        "hb_normal": "హీమోగ్లోబిన్ {hb} గ్రాములు సాధారణంగా ఉంది.",
        "hb_low": "హీమోగ్లోబిన్ {hb} గ్రాములు తక్కువగా ఉంది, రక్తహీనత ఉంది.",
        "danger_signs": "ప్రమాద సంకేతాలు: {symptoms}.",
        "no_danger": "ఎలాంటి తీవ్ర ప్రమాద సంకేతాలు లేవు.",
        "urgent_referral": "తక్షణమే ప్రాథమిక ఆరోగ్య కేంద్రం లేదా ఆసుపత్రికి వెళ్లండి. 108కి కాల్ చేయండి.",
        "clinician_referral": "వైద్యుని సంప్రదింపు అవసరం. రెండు రోజుల్లో కేంద్రానికి వెళ్ళండి.",
        "routine": "గర్భధారణ సాధారణంగా సాగుతోంది. ఐరన్ మరియు కాల్షియం మాత్రలు రోజూ తీసుకోండి.",
    },
    "ta-IN": {
        "greeting": "{name}, RCH எண் {rch_id}.",
        "gestation": "கர்ப்ப காலம் {weeks} வாரங்கள்.",
        "bp_normal": "இரத்த அழுத்தம் {sys} / {dia} இயல்பாக உள்ளது.",
        "bp_high": "இரத்த அழுத்தம் {sys} / {dia} அதிகமாக உள்ளது.",
        "hb_normal": "ஹீமோகுளோபின் {hb} கிராம் இயல்பாக உள்ளது.",
        "hb_low": "ஹீமோகுளோபின் {hb} கிராம் குறைவாக உள்ளது, இரத்த சோகை உள்ளது.",
        "danger_signs": "ஆபத்து அறிகுறிகள்: {symptoms}.",
        "no_danger": "தீவிர ஆபத்து அறிகுறிகள் ஏதுமில்லை.",
        "urgent_referral": "உடனடியாக அரசு மருத்துவமனைக்குச் செல்லுங்கள். 108 அவசர ஊர்தியை அழைக்கவும்.",
        "clinician_referral": "மருத்துவர் பரிசோதனை தேவை. இரு நாட்களில் ஆரம்ப சுகாதார நிலையத்திற்கு செல்லவும்.",
        "routine": "கர்ப்பம் சீராக உள்ளது. இரும்புச்சத்து மற்றும் கால்சியம் மாத்திரைகளை தவறாமல் உட்கொள்ளவும்.",
    },
    "ml-IN": {
        "greeting": "{name}, RCH ഐഡി {rch_id}.",
        "gestation": "ഗർഭാവസ്ഥ {weeks} ആഴ്ചകൾ.",
        "bp_normal": "രക്തസമ്മർദ്ദം {sys} / {dia} സാധാരണ നിലയിലാണ്.",
        "bp_high": "രക്തസമ്മർദ്ദം {sys} / {dia} കൂടുതലാണ്.",
        "hb_normal": "ഹീമോഗ്ലോബിൻ {hb} ഗ്രാം സാധാരണ നിലയിലാണ്.",
        "hb_low": "ഹീമോഗ്ലോബിൻ {hb} ഗ്രാം കുറവാണ്, അനീമിയ ലക്ഷണങ്ങൾ കാണുന്നു.",
        "danger_signs": "അപകട ലക്ഷണങ്ങൾ: {symptoms}.",
        "no_danger": "ഗുരുതരമായ അപകട ലക്ഷണങ്ങളൊന്നുമില്ല.",
        "urgent_referral": "ഉടൻ തന്നെ അടുത്തുള്ള ആശുപത്രിയിൽ എത്തിക്കുക. 108 ആംബുലൻസ് വിളിക്കുക.",
        "clinician_referral": "ഡോക്ടറുടെ പരിശോധന ആവശ്യമാണ്. രണ്ട് ദിവസത്തിനകം പിഎച്ച്സി സന്ദർശിക്കുക.",
        "routine": "ഗർഭാവസ്ഥ തൃപ്തികരമാണ്. അയൺ, കാൽസ്യം ഗുളികകൾ കൃത്യമായി കഴിക്കുക.",
    },
}

_SYMPTOM_NAMES: dict[str, dict[str, str]] = {
    "hi-IN": {
        "severe_headache": "तेज सिरदर्द",
        "blurred_vision": "धुंधला दिखना",
        "swelling": "पैरों या चेहरे पर सूजन",
        "reduced_fetal_movement": "शिशु की हलचल कम होना",
        "vaginal_bleeding": "रक्तस्राव",
        "convulsions": "दौरे पड़ना",
        "severe_abdominal_pain": "पेट में तेज दर्द",
        "fever": "तेज बुखार",
        "leaking_fluid": "पानी छूटना",
    },
    "en-IN": {
        "severe_headache": "severe headache",
        "blurred_vision": "blurred vision",
        "swelling": "swelling of hands/face",
        "reduced_fetal_movement": "reduced fetal movements",
        "vaginal_bleeding": "vaginal bleeding",
        "convulsions": "convulsions",
        "severe_abdominal_pain": "severe abdominal pain",
        "fever": "high fever",
        "leaking_fluid": "leaking fluid",
    },
}


def build_spoken_summary_text(session: SessionState, target_language: str | None = None) -> str:
    """Compose a concise 15-20 second spoken clinical summary."""
    lang = target_language or session.language
    if lang not in _SUMMARY_TEMPLATES:
        lang = "en-IN"

    tpl = _SUMMARY_TEMPLATES[lang]
    symptom_map = _SYMPTOM_NAMES.get(lang, _SYMPTOM_NAMES["en-IN"])

    parts: list[str] = []

    # 1. Mother Identification
    name = (session.linked_patient.get("name") if session.linked_patient else None) or "मातृ"
    rch_id = (session.linked_patient.get("rch_id") if session.linked_patient else None) or "ANC"
    parts.append(tpl["greeting"].format(name=name, rch_id=rch_id))

    # 2. Gestational Age
    if session.record.gestational_weeks is not None:
        parts.append(tpl["gestation"].format(weeks=session.record.gestational_weeks))

    # 3. Blood Pressure
    if session.record.bp_systolic is not None and session.record.bp_diastolic is not None:
        sys = session.record.bp_systolic
        dia = session.record.bp_diastolic
        if sys >= 140 or dia >= 90:
            parts.append(tpl["bp_high"].format(sys=sys, dia=dia))
        else:
            parts.append(tpl["bp_normal"].format(sys=sys, dia=dia))

    # 4. Hemoglobin
    if session.record.hemoglobin is not None:
        hb = session.record.hemoglobin
        if hb < 11.0:
            parts.append(tpl["hb_low"].format(hb=hb))
        else:
            parts.append(tpl["hb_normal"].format(hb=hb))

    # 5. Danger signs
    present_symptoms = [
        symptom_map.get(k, k.replace("_", " "))
        for k in (
            "severe_headache",
            "blurred_vision",
            "swelling",
            "reduced_fetal_movement",
            "vaginal_bleeding",
            "convulsions",
            "severe_abdominal_pain",
            "fever",
            "leaking_fluid",
        )
        if getattr(session.record, k, None) == "present"
    ]

    if present_symptoms:
        parts.append(tpl["danger_signs"].format(symptoms=", ".join(present_symptoms)))
    else:
        parts.append(tpl["no_danger"])

    # 6. Referral recommendation
    flag = session.evaluation.flag if session.evaluation else None
    if flag == "URGENT_REFERRAL":
        parts.append(tpl["urgent_referral"])
    elif flag == "CLINICIAN_REFERRAL":
        parts.append(tpl["clinician_referral"])
    else:
        parts.append(tpl["routine"])

    return " ".join(parts)


def generate_visit_audio_summary(
    session: SessionState,
    target_language: str | None = None,
    timbre_client: TimbreClient | None = None,
) -> dict[str, Any]:
    """Generate localized text and spoken audio bytes for the locked visit."""
    lang = target_language or session.language
    text = build_spoken_summary_text(session, target_language=lang)

    client = timbre_client or TimbreClient()
    audio_b64 = None
    try:
        audio_bytes = client.synthesize(text=text, language=lang)
        if audio_bytes:
            audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
    except Exception as err:
        # Graceful fallback: text remains available
        pass

    return {
        "language": lang,
        "text": text,
        "audio_playback_b64": audio_b64,
        "has_audio": audio_b64 is not None,
    }
