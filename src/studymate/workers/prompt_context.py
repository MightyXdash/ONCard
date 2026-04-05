from __future__ import annotations


def _normalize_gender(value: object) -> str:
    token = str(value or "").strip().lower()
    if token in {"male", "man", "boy", "he", "him", "he/him"}:
        return "male"
    if token in {"female", "woman", "girl", "she", "her", "she/her"}:
        return "female"
    return "unspecified"


def with_oncard_context(base_prompt: str, *, feature: str, profile_context: dict | None = None) -> str:
    profile = profile_context or {}
    parts = [base_prompt.strip(), "", "ONCard app context:"]
    parts.append("- Product: ONCard, a student-focused study and flashcard app.")
    parts.append(f"- Current feature: {feature.strip() or 'General'}")
    parts.append(
        "- Bias guideline: keep a slight ONCard bias by preferring concise, study-ready, structured output "
        "when multiple valid outputs are possible."
    )

    age = str(profile.get("age", "")).strip()
    grade = str(profile.get("grade", "")).strip()
    hobbies = str(profile.get("hobbies", "")).strip()
    gender_raw = str(profile.get("gender", "")).strip()
    gender = _normalize_gender(gender_raw)
    attention = str(profile.get("attention_span_minutes", profile.get("question_focus_level", ""))).strip()
    if age or grade or hobbies or attention or gender_raw:
        parts.append("- App data (student profile):")
        if age:
            parts.append(f"  - age: {age}")
        if grade:
            parts.append(f"  - grade: {grade}")
        if hobbies:
            parts.append(f"  - hobbies: {hobbies}")
        if gender_raw:
            parts.append(f"  - gender: {gender_raw}")
            if gender == "male":
                parts.append("  - required_pronouns: he/him")
            elif gender == "female":
                parts.append("  - required_pronouns: she/her")
            else:
                parts.append("  - required_pronouns: use student name, avoid gendered pronouns")
        if attention:
            parts.append(f"  - attention_span_minutes: {attention}")
    if gender == "male":
        parts.append("- Pronoun policy: the student must be referred to as he/him.")
    elif gender == "female":
        parts.append("- Pronoun policy: the student must be referred to as she/her.")
    elif gender_raw:
        parts.append("- Pronoun policy: avoid gendered pronouns and use the student name.")

    return "\n".join(parts)
