from __future__ import annotations

import json
import re

from PySide6.QtCore import QThread, Signal

from studymate.services.ollama_service import OllamaError, OllamaService
from studymate.workers.prompt_context import build_ask_ai_answer_system_prompt, with_oncard_context


AI_SEARCH_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "needs_show_cards": {"type": "boolean"},
        "tool_name": {"type": "string"},
        "search_query": {"type": "string"},
        "research_message": {"type": "string"},
        "reasoning_steps": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["needs_show_cards", "tool_name", "search_query", "research_message", "reasoning_steps"],
}

AI_IMAGE_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "visible_text": {"type": "string"},
        "topic_hint": {"type": "string"},
        "can_read_clearly": {"type": "boolean"},
        "uncertainty_note": {"type": "string"},
    },
    "required": ["summary", "visible_text", "topic_hint", "can_read_clearly", "uncertainty_note"],
}

IMAGE_SEARCH_TERMS_SCHEMA = {
    "type": "object",
    "properties": {
        "search_terms": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["search_terms"],
}


def _normalize_research_message(message: str) -> str:
    cleaned = " ".join(str(message or "").strip().split())
    if not cleaned:
        return "I am researching the most relevant cards and study context for you so I can answer this properly."
    words = cleaned.split()
    if len(words) < 8:
        return "I am researching the most relevant cards and study context for you so I can answer this properly."
    if len(words) > 24:
        cleaned = " ".join(words[:24]).rstrip(".,;:!?")
    if cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned


def _default_reasoning_steps(prompt: str, *, has_image: bool) -> list[str]:
    steps: list[str] = []
    if has_image:
        steps.append("I’m checking the image and your text together so I don’t miss the actual context.")
    lowered = " ".join(str(prompt or "").lower().split())
    if any(token in lowered for token in ["card", "question", "subject", "topic", "search", "find", "related"]):
        steps.append("I’m deciding whether the app cards are relevant enough to search before I answer.")
    return steps[:2]


def _extract_tool_query(tool_calls: object) -> str:
    if not isinstance(tool_calls, list):
        return ""
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        function_payload = call.get("function")
        if not isinstance(function_payload, dict):
            continue
        if str(function_payload.get("name", "")).strip() != "ShowCards":
            continue
        arguments = function_payload.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"query": arguments}
        if isinstance(arguments, dict):
            query = " ".join(str(arguments.get("query", "")).strip().split())
            if query:
                return query
    return ""


def _append_unique_term(terms: list[str], value: object, *, limit: int) -> None:
    term = " ".join(str(value or "").strip().strip("-*0123456789. )(").split())
    if not term:
        return
    if term.lower() in {existing.lower() for existing in terms}:
        return
    terms.append(term)
    if len(terms) > limit:
        del terms[limit:]


def _extract_image_search_terms(payload: object, *, limit: int) -> list[str]:
    terms: list[str] = []
    if isinstance(payload, dict):
        raw_terms = payload.get("search_terms", [])
        if isinstance(raw_terms, list):
            for item in raw_terms:
                _append_unique_term(terms, item, limit=limit)
        elif isinstance(raw_terms, str):
            for part in re.split(r"[,;\n]+", raw_terms):
                _append_unique_term(terms, part, limit=limit)
    elif isinstance(payload, list):
        for item in payload:
            _append_unique_term(terms, item, limit=limit)
    return terms[:limit]


def _extract_image_search_terms_loose(content: str, *, limit: int) -> list[str]:
    text = str(content or "").strip()
    if not text:
        return []
    candidates = [text]
    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE):
        snippet = str(match.group(1) or "").strip()
        if snippet:
            candidates.insert(0, snippet)
    start_obj = text.find("{")
    end_obj = text.rfind("}")
    if start_obj >= 0 and end_obj > start_obj:
        candidates.insert(0, text[start_obj : end_obj + 1])
    start_array = text.find("[")
    end_array = text.rfind("]")
    if start_array >= 0 and end_array > start_array:
        candidates.insert(0, text[start_array : end_array + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        terms = _extract_image_search_terms(parsed, limit=limit)
        if terms:
            return terms

    terms: list[str] = []
    for line in text.splitlines():
        cleaned = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
        if not cleaned or cleaned.lower().startswith(("search_terms", "search terms", "json")):
            continue
        if ":" in cleaned:
            cleaned = cleaned.split(":", 1)[1].strip()
        if "," in cleaned:
            for part in cleaned.split(","):
                _append_unique_term(terms, part, limit=limit)
        else:
            _append_unique_term(terms, cleaned, limit=limit)
        if len(terms) >= limit:
            break
    return terms[:limit]


def _analyze_attached_image(
    ollama: OllamaService,
    *,
    model: str,
    prompt: str,
    image_paths: list[str],
    context_length: int,
) -> dict:
    if not image_paths:
        return {}
    system_prompt = (
        "You are a precise visual analysis layer for ONCard Ask AI. "
        "Describe only what is actually visible in the attached image. "
        "If text is visible, extract it carefully. "
        "If anything is unclear, say so instead of guessing."
    )
    user_prompt = (
        "Analyze the attached image for Ask AI.\n\n"
        "Return strict JSON.\n"
        "- summary: short factual description of what is visible\n"
        "- visible_text: important text seen in the image\n"
        "- topic_hint: short likely topic or subject based on the image\n"
        "- can_read_clearly: true if the image is clear enough to rely on\n"
        "- uncertainty_note: brief note about anything unclear or unreadable\n\n"
        f"User text:\n{prompt.strip()}"
    )
    try:
        payload = ollama.structured_chat(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=AI_IMAGE_ANALYSIS_SCHEMA,
            temperature=0.0,
            timeout=120,
            image_paths=image_paths,
            extra_options={
                "num_ctx": context_length,
                "num_predict": 220,
            },
        )
    except OllamaError:
        return {}
    return {
        "summary": " ".join(str(payload.get("summary", "")).strip().split()),
        "visible_text": " ".join(str(payload.get("visible_text", "")).strip().split()),
        "topic_hint": " ".join(str(payload.get("topic_hint", "")).strip().split()),
        "can_read_clearly": bool(payload.get("can_read_clearly", False)),
        "uncertainty_note": " ".join(str(payload.get("uncertainty_note", "")).strip().split()),
    }


class AiSearchPlannerWorker(QThread):
    failed = Signal(int, str)
    planned = Signal(int, object)

    def __init__(
        self,
        *,
        request_id: int,
        ollama: OllamaService,
        model: str,
        prompt: str,
        context_length: int = 9216,
        profile_context: dict | None = None,
        image_paths: list[str] | None = None,
        use_native_tools: bool = False,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.ollama = ollama
        self.model = model
        self.prompt = prompt
        self.context_length = context_length
        self.profile_context = profile_context or {}
        self.image_paths = list(image_paths or [])
        self.use_native_tools = use_native_tools
        self._stop_requested = False

    def stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        image_analysis = _analyze_attached_image(
            self.ollama,
            model=self.model,
            prompt=self.prompt,
            image_paths=self.image_paths,
            context_length=self.context_length,
        )
        if self.use_native_tools:
            plan = self._run_native_tool_plan(image_analysis)
            if self._stop_requested:
                return
            if plan is not None:
                self.planned.emit(self.request_id, plan)
                return
        system_prompt = with_oncard_context(
            (
                "You are ONCard's Ask AI routing layer. "
                "Decide whether the app should call the ShowCards tool before answering. "
                "Use ShowCards only when the user explicitly asks about cards, questions, answers, subjects, or topics "
                "that exist in the ONCard app, or explicitly asks you to search, learn from, or explain related ONCard cards/questions. "
                "If an image is attached, use both the image and the text to infer what the user wants. "
                "Do not use ShowCards for general study questions, general subject tutoring, UI questions, account/settings questions, "
                "or purely app-navigation requests. "
                "Return only strict JSON matching the schema."
            ),
            feature="Ask AI route planner",
            profile_context=self.profile_context,
        )
        user_prompt = (
            "Decide whether Ask AI should call the ShowCards tool.\n\n"
            "Rules:\n"
            "- Use ShowCards only if the user explicitly refers to ONCard app cards/questions/subjects/topics, or explicitly asks to search or learn from related cards in the app.\n"
            "- For general tutoring or study help without explicit ONCard card/app context, set needs_show_cards to false.\n"
            "- If needs_show_cards is true, tool_name must be exactly `ShowCards`.\n"
            "- If needs_show_cards is false, tool_name must be an empty string.\n"
            "- search_query must be a short search query that represents the core card/topic lookup.\n"
            "- research_message must be in first person, 16 to 24 words, and tell the user you are researching the matter for them.\n"
            "- The research_message must not promise the final answer yet.\n\n"
            "- reasoning_steps must contain 0 to 2 short first-person status lines for the loading UI.\n"
            "- reasoning_steps should describe what you are checking or interpreting.\n"
            "- If the request is so direct that extra reasoning text would feel unnecessary, reasoning_steps may be empty.\n\n"
            f"Image attached: {'yes' if self.image_paths else 'no'}\n\n"
            f"Grounded image analysis:\n{json.dumps(image_analysis, ensure_ascii=False, indent=2)}\n\n"
            f"User query:\n{self.prompt.strip()}"
        )
        try:
            payload = self.ollama.structured_chat(
                model=self.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=AI_SEARCH_PLAN_SCHEMA,
                temperature=0.0,
                timeout=120,
                image_paths=self.image_paths,
                extra_options={
                    "num_ctx": self.context_length,
                    "num_predict": 120,
                },
            )
        except OllamaError as exc:
            if not self._stop_requested:
                self.failed.emit(self.request_id, str(exc))
            return

        if self._stop_requested:
            return

        needs_show_cards = bool(payload.get("needs_show_cards", False))
        tool_name = str(payload.get("tool_name", "")).strip()
        if needs_show_cards:
            tool_name = "ShowCards"
        else:
            tool_name = ""
        search_query = " ".join(str(payload.get("search_query", "")).strip().split())
        if needs_show_cards and not search_query:
            search_query = " ".join(self.prompt.strip().split())[:120].strip()
        research_message = _normalize_research_message(str(payload.get("research_message", "")))
        reasoning_steps = [
            " ".join(str(step or "").strip().split())
            for step in payload.get("reasoning_steps", [])
            if str(step or "").strip()
        ][:2]

        plan = {
            "needs_show_cards": needs_show_cards,
            "tool_name": tool_name,
            "search_query": search_query,
            "research_message": research_message,
            "reasoning_steps": reasoning_steps,
            "image_analysis": image_analysis,
        }
        self.planned.emit(self.request_id, plan)

    def _run_native_tool_plan(self, image_analysis: dict) -> dict | None:
        system_prompt = with_oncard_context(
            (
                "You are ONCard's Ask AI routing layer. "
                "Use the ShowCards tool when the user explicitly asks about cards, questions, answers, subjects, or topics in the ONCard app, "
                "or explicitly asks to search or learn from related ONCard cards/questions. "
                "Do not call the tool for general study questions, UI help, settings help, or general tutoring."
            ),
            feature="Ask AI native tool route planner",
            profile_context=self.profile_context,
        )
        user_prompt = (
            f"Image attached: {'yes' if self.image_paths else 'no'}\n\n"
            f"Grounded image analysis:\n{json.dumps(image_analysis, ensure_ascii=False, indent=2)}\n\n"
            f"User query:\n{self.prompt.strip()}\n\n"
            "If app-card retrieval is needed, call ShowCards with a short search query. "
            "If not needed, answer normally without any tool call."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": user_prompt,
                "images": self.ollama._encode_images(self.image_paths),
            },
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "ShowCards",
                    "description": "Search ONCard app cards related to the user's request.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Short semantic search query for the relevant ONCard cards.",
                            }
                        },
                        "required": ["query"],
                    },
                },
            }
        ]
        try:
            body = self.ollama.chat_messages(
                model=self.model,
                messages=messages,
                temperature=0.0,
                timeout=120,
                tools=tools,
                extra_options={
                    "num_ctx": self.context_length,
                    "num_predict": 120,
                },
            )
        except OllamaError:
            return None
        if self._stop_requested:
            return None
        message = body.get("message", {}) if isinstance(body, dict) else {}
        tool_query = _extract_tool_query(message.get("tool_calls"))
        needs_show_cards = bool(tool_query)
        return {
            "needs_show_cards": needs_show_cards,
            "tool_name": "ShowCards" if needs_show_cards else "",
            "search_query": tool_query or "",
            "research_message": _normalize_research_message(
                "I am researching the most relevant ONCard cards and study context for you so I can answer this properly."
            ),
            "reasoning_steps": _default_reasoning_steps(self.prompt, has_image=bool(self.image_paths)),
            "image_analysis": image_analysis,
        }


class ImageSearchTermsWorker(QThread):
    failed = Signal(int, str)
    finished = Signal(int, object)

    def __init__(
        self,
        *,
        request_id: int,
        ollama: OllamaService,
        model: str,
        image_path: str,
        term_count: int = 4,
        context_length: int = 9216,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.ollama = ollama
        self.model = model
        self.image_path = image_path
        self.term_count = max(2, min(6, int(term_count or 4)))
        self.context_length = max(4096, int(context_length or 9216))

    def run(self) -> None:
        system_prompt = (
            "You are ONCard's image search query generator. "
            "Look at the image and return concise terms that would find matching study cards. "
            "Use only visible evidence. Prefer subject names, concepts, objects, formulas, and readable text."
        )
        user_prompt = (
            f"Return strict JSON with exactly {self.term_count} probable search terms for this image.\n"
            "Rules:\n"
            "- Each term should be 1 to 5 words.\n"
            "- Do not include explanations.\n"
            "- Do not invent details that are not visible.\n"
            "- If text is visible, include the most searchable visible words.\n"
            f'- Example shape: {{"search_terms": ["term one", "term two"]}}\n'
        )
        payload: dict | None = None
        try:
            payload = self.ollama.structured_chat(
                model=self.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=IMAGE_SEARCH_TERMS_SCHEMA,
                temperature=0.0,
                timeout=120,
                image_paths=[self.image_path],
                extra_options={
                    "num_ctx": self.context_length,
                    "num_predict": 160,
                },
            )
        except OllamaError as exc:
            try:
                fallback_content = self.ollama.chat(
                    model=self.model,
                    system_prompt=system_prompt,
                    user_prompt=(
                        f"{user_prompt}\n\n"
                        "Return only JSON. If your system cannot enforce JSON mode, still write only the JSON object."
                    ),
                    temperature=0.0,
                    timeout=120,
                    image_paths=[self.image_path],
                    extra_options={
                        "num_ctx": self.context_length,
                        "num_predict": 160,
                    },
                )
            except OllamaError:
                self.failed.emit(self.request_id, str(exc))
                return
            terms = _extract_image_search_terms_loose(fallback_content, limit=self.term_count)
            if len(terms) >= 2:
                self.finished.emit(self.request_id, terms)
                return
            self.failed.emit(self.request_id, "Image search could not read enough search terms from the cloud response.")
            return

        terms = _extract_image_search_terms(payload, limit=self.term_count)
        if len(terms) < 2:
            self.failed.emit(self.request_id, "Image search could not find enough searchable terms.")
            return
        self.finished.emit(self.request_id, terms)


class AiSearchAnswerWorker(QThread):
    failed = Signal(int, str)
    finished = Signal(int, str)

    def __init__(
        self,
        *,
        request_id: int,
        ollama: OllamaService,
        model: str,
        prompt: str,
        context_length: int = 9216,
        profile_context: dict | None = None,
        retrieved_cards: list[dict] | None = None,
        retrieval_query: str = "",
        tone: str = "",
        emoji_level: int = 2,
        image_paths: list[str] | None = None,
        image_analysis: dict | None = None,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.ollama = ollama
        self.model = model
        self.prompt = prompt
        self.context_length = context_length
        self.profile_context = profile_context or {}
        self.retrieved_cards = list(retrieved_cards or [])
        self.retrieval_query = retrieval_query
        self.tone = str(tone or "").strip().lower()
        self.emoji_level = max(1, min(4, int(emoji_level or 2)))
        self.image_paths = list(image_paths or [])
        self.image_analysis = dict(image_analysis or {})
        self._stop_requested = False

    def stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        has_cards = bool(self.retrieved_cards)
        image_analysis = dict(self.image_analysis)
        if self.image_paths and not image_analysis:
            image_analysis = _analyze_attached_image(
                self.ollama,
                model=self.model,
                prompt=self.prompt,
                image_paths=self.image_paths,
                context_length=self.context_length,
            )
        system_prompt = build_ask_ai_answer_system_prompt(
            self.profile_context,
            tone=self.tone,
            emoji_level=self.emoji_level,
        )
        instructions = [
            "Answer the user query in the structure that best fits the request.",
            "",
            "Rules:",
            "- Answer naturally. Do not lock yourself into one repeated structure.",
            "- Aim to stay concise, but do not force a short answer if the user clearly needs more explanation.",
            "- Keep the tone casual, warm, and natural.",
            "- Let the tone vary with the situation: funny where needed, serious where needed, empathetic where needed, and hyped where needed.",
            "- The voice can range from Gen Z casual to semi-formal depending on the user's query.",
            "- Answer the user's actual question directly.",
            "- Use your own structure. Use headings, bullets, short paragraphs, or a mix only when they genuinely help.",
            "- Emojis are allowed and should follow the selected emoji level.",
            "- If an image is attached, use the grounded image analysis as primary evidence.",
            "- If the image is unclear or unreadable, say that directly instead of guessing.",
            "- Do not invent image details that are not supported by the grounded image analysis.",
            "- Ground claims in the retrieved cards and performance data when available.",
            "- If marks or performance are available, tailor the study advice to that performance.",
            "- If retrieved cards are weak or partial matches, say so briefly and still help.",
            "- If retrieved ONCard cards are supplied, explicitly talk about the related cards rather than ignoring them.",
            "- If no retrieved ONCard cards are supplied, do not force the answer toward the app.",
            "- Do not mention internal tool names.",
            "- Do not include filler or follow-up questions.",
            "- Use code blocks only if the user explicitly needs code.",
            "",
            "Markdown validity rules:",
            "- Put a space after heading markers.",
            "- Leave one blank line between sections.",
            "- Start every bullet with `- ` on its own line.",
            "- Keep natural word spacing.",
            "",
            f"Image attached: {'yes' if self.image_paths else 'no'}",
            "",
            f"Grounded image analysis:\n{json.dumps(image_analysis, ensure_ascii=False, indent=2)}",
            "",
            f"User query:\n{self.prompt.strip()}",
        ]
        if has_cards:
            instructions.extend(
                [
                    "",
                    f"Retrieved app search query:\n{self.retrieval_query.strip()}",
                    "",
                    "Retrieved cards and performance context:",
                    json.dumps(self.retrieved_cards, ensure_ascii=False, indent=2),
                ]
            )
        else:
            instructions.extend(
                [
                    "",
                    "Retrieved cards and performance context:",
                    "[]",
                    "",
                    "No close card matches were retrieved from app data, so answer generally while staying study-focused.",
                ]
            )
        user_prompt = "\n".join(instructions)

        markdown = ""
        try:
            for piece in self.ollama.stream_chat(
                model=self.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                image_paths=self.image_paths,
                temperature=0.8,
                extra_options={
                    "num_ctx": self.context_length,
                    # Keep Ask AI capable of longer completions (e.g., essays/explanations)
                    # so answers are not cut off mid-response by a low token ceiling.
                    "num_predict": -1,
                    "repeat_penalty": 1.12,
                    "top_p": 0.9,
                },
                should_stop=lambda: self._stop_requested,
            ):
                if self._stop_requested:
                    return
                markdown += piece
        except OllamaError as exc:
            if not self._stop_requested:
                self.failed.emit(self.request_id, str(exc))
            return
        if not self._stop_requested:
            self.finished.emit(self.request_id, markdown.strip())
