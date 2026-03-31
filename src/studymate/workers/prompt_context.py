from __future__ import annotations


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
    attention = str(profile.get("attention_span_minutes", profile.get("question_focus_level", ""))).strip()
    if age or grade or hobbies or attention:
        parts.append("- App data (student profile):")
        if age:
            parts.append(f"  - age: {age}")
        if grade:
            parts.append(f"  - grade: {grade}")
        if hobbies:
            parts.append(f"  - hobbies: {hobbies}")
        if attention:
            parts.append(f"  - attention_span_minutes: {attention}")

    return "\n".join(parts)
