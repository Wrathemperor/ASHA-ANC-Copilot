# Official ANC Rule Set

Use these rules only for clinician referral flags and missing-information prompts. They do not diagnose, prescribe, or assign PMSMA stickers.

## Safety model

- A clinical field is `present`, `denied`, or `not_mentioned`. Silence is never denial.
- Any positive rule produces a clinician referral flag. A missing field produces `Incomplete / Needs Verification`, never a normal finding.
- Emergency rules bypass follow-up. Re-run every rule after each turn.
- PMSMA framing: Green means no risk factor detected; Red means high-risk pregnancy. The product may visually echo this framing, but it never assigns a sticker or replaces clinician assessment.

## Emergency rules

| ID | Deterministic condition | Output |
| --- | --- | --- |
| RULE-EMG-01 | `convulsions == present` | Urgent clinician referral flag. |
| RULE-EMG-02 | `vaginal_bleeding == present` | Urgent clinician referral flag. |
| RULE-EMG-03 | `severe_headache == present and blurred_vision == present` | Urgent clinician referral flag. |
| RULE-EMG-04 | `severe_abdominal_pain == present` | Urgent clinician referral flag. |

## High-risk referral rules

| ID | Deterministic condition | Output |
| --- | --- | --- |
| RULE-HRP-01 | Two BP readings are present and each is at least `140/90` mm Hg. | Clinician referral flag for hypertension assessment. |
| RULE-HRP-02 | `severe_headache == present` or `blurred_vision == present`. | Clinician referral flag. |
| RULE-HRP-03 | `swelling == present`. | Clinician referral flag. |
| RULE-HRP-04 | `reduced_fetal_movement == present`. | Clinician referral flag. |
| RULE-HRP-05 | `anemia_or_low_hb_mentioned == present`, `fever == present`, or `leaking_fluid == present`. | Clinician referral flag. |

## Stage gate

| ID | Deterministic condition | Required action |
| --- | --- | --- |
| STAGE-GATE-01 | `gestational_weeks` is `null`; or it is at least 20 weeks and `reduced_fetal_movement == not_mentioned`. | Ask gestational weeks first when absent. At 20 weeks or later, require a fetal-movement check. If weeks are unknown, keep fetal movement required rather than assuming it does not apply. |

The 18-20 week range is when first perception of fetal movement is documented. This implementation uses the selected 20-week threshold.

## Gap priority

Apply this exact order after emergency bypass and the gestational-weeks gate. Ask at most two voice follow-ups. Each prompt asks one item only. All remaining gaps stay `Incomplete / Needs Verification`.

1. `vaginal_bleeding`
2. `convulsions`
3. `severe_headache`
4. `blurred_vision`
5. `swelling`
6. `reduced_fetal_movement` (subject to STAGE-GATE-01)
7. `severe_abdominal_pain`

## Sources

- PMSMA: [Green/Red sticker framing](https://pmsma.mohfw.gov.in/?lang=en) and [tracking high-risk pregnancies](https://pmsma.mohfw.gov.in/i-am/government-organization/monitoring-and-supervision-plan/).
- National Health Mission: [My Safe Motherhood Booklet](https://www.nhm.gov.in/images/pdf/programmes/maternal-health/guidelines/my_safe_motherhood_booklet_english.pdf).
- PMSMA: [Hypertensive disorders of pregnancy](https://pmsma.mohfw.gov.in/wp-content/uploads/2016/10/High-Risk-Conditions-in-preg-modified-Final.pdf).
- National Health Mission: [Revised CEmONC Curriculum 2024, Part 1](https://nhm.gov.in/pdf/2024/Revised_CEmONC_Curriculum-2024-Part-1.pdf).
