from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import requests
import tempfile
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from studymate.services.ollama_service import OllamaError, OllamaService
from studymate.services.model_registry import QN_SUMMARIZER_CONTEXT_LENGTH, QN_SUMMARIZER_MAX_WORDS, QN_SUMMARIZER_MODEL_TAG
from studymate.workers.prompt_context import build_ask_ai_answer_system_prompt, with_oncard_context


WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_HEADERS = {
    "User-Agent": "ONCard/1.0 (Wikipedia breakdown study feature; https://github.com/MightyXdash/ONCard)"
}
WIKIPEDIA_THUMB_CACHE = Path(tempfile.gettempdir()) / "oncard_wiki_thumbnails"
WIKIPEDIA_THUMB_SIZE = 900
WIKIPEDIA_GALLERY_THUMB_SIZE = 1100
WIKIPEDIA_ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".tif", ".tiff"}


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


def _clean_wikipedia_text(text: str, *, max_words: int = 1000) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"\[[0-9A-Za-z,\s]+\]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned.replace("\u00a0", " ")).strip()
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    words = cleaned.split()
    if len(words) > max_words:
        cleaned = " ".join(words[:max_words]).rstrip(" ,;:")
        if cleaned and cleaned[-1] not in ".!?":
            cleaned += "."
    return cleaned


def _word_count(text: str) -> int:
    return len(str(text or "").split())


def _limit_words(text: str, *, max_words: int) -> str:
    words = str(text or "").split()
    if len(words) <= max_words:
        return str(text or "").strip()
    limited = " ".join(words[:max_words]).rstrip(" ,;:")
    if limited and limited[-1] not in ".!?":
        limited += "."
    return limited


def _short_wikipedia_title(query: str, timeout: int = 12) -> str:
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": 1,
        "format": "json",
        "utf8": 1,
    }
    response = requests.get(WIKIPEDIA_API, params=params, headers=WIKIPEDIA_HEADERS, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    results = payload.get("query", {}).get("search", [])
    if not results:
        return ""
    return str(results[0].get("title", "")).strip()


def fetch_wikipedia_extract(query: str, *, timeout: int = 18, max_words: int = 1000, include_images: bool = False) -> dict:
    search_query = " ".join(str(query or "").strip().split())
    if not search_query:
        raise OllamaError("Type a Wikipedia topic after /wiki.")
    title = _short_wikipedia_title(search_query, timeout=timeout)
    if not title:
        raise OllamaError(f"No Wikipedia article was found for `{search_query}`.")

    params = {
        "action": "query",
        "prop": "extracts|info|pageimages",
        "explaintext": 1,
        "exsectionformat": "plain",
        "redirects": 1,
        "inprop": "url",
        "piprop": "thumbnail",
        "pithumbsize": WIKIPEDIA_THUMB_SIZE,
        "titles": title,
        "format": "json",
        "utf8": 1,
    }
    response = requests.get(WIKIPEDIA_API, params=params, headers=WIKIPEDIA_HEADERS, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    pages = payload.get("query", {}).get("pages", {})
    page = next((item for item in pages.values() if isinstance(item, dict) and "missing" not in item), None)
    if not isinstance(page, dict):
        raise OllamaError(f"Wikipedia could not open `{title}`.")

    extract = _clean_wikipedia_text(str(page.get("extract", "")), max_words=max_words)
    if _word_count(extract) < 1:
        raise OllamaError(f"Wikipedia returned no readable article text for `{title}`.")

    thumbnail = page.get("thumbnail", {})
    thumbnail_url = ""
    if isinstance(thumbnail, dict):
        thumbnail_url = str(thumbnail.get("source", "")).strip()
    thumbnail_path = _cache_wikipedia_thumbnail(thumbnail_url, timeout=timeout) if thumbnail_url else ""
    result = {
        "title": str(page.get("title", title)).strip() or title,
        "url": str(page.get("fullurl", "")).strip(),
        "extract": extract,
        "word_count": _word_count(extract),
        "thumbnail_url": thumbnail_url,
        "thumbnail_path": thumbnail_path,
    }
    if include_images:
        result["images"] = _fetch_wikipedia_gallery_images(str(page.get("title", title)).strip() or title, timeout=timeout)
    return result


def _fetch_wikipedia_gallery_images(title: str, *, timeout: int = 18) -> list[dict]:
    return list(_iter_wikipedia_gallery_images(title, timeout=timeout))


def _iter_wikipedia_gallery_images(title: str, *, timeout: int = 18, should_stop=None):
    article_title = " ".join(str(title or "").strip().split())
    if not article_title:
        return

    image_titles: list[str] = []
    seen_titles: set[str] = set()
    imcontinue = ""
    while True:
        if callable(should_stop) and should_stop():
            return
        params = {
            "action": "query",
            "prop": "images",
            "titles": article_title,
            "imlimit": "max",
            "format": "json",
            "utf8": 1,
        }
        if imcontinue:
            params["imcontinue"] = imcontinue
        try:
            response = requests.get(WIKIPEDIA_API, params=params, headers=WIKIPEDIA_HEADERS, timeout=min(timeout, 10))
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            return

        pages = payload.get("query", {}).get("pages", {})
        for page in pages.values():
            if not isinstance(page, dict):
                continue
            for image in page.get("images", []):
                if not isinstance(image, dict):
                    continue
                file_title = str(image.get("title", "")).strip()
                if not file_title.lower().startswith("file:"):
                    continue
                suffix = Path(file_title.split(":", 1)[1]).suffix.lower()
                if suffix not in WIKIPEDIA_ALLOWED_IMAGE_SUFFIXES:
                    continue
                lowered = file_title.lower()
                if lowered in seen_titles:
                    continue
                seen_titles.add(lowered)
                image_titles.append(file_title)

        imcontinue = str(payload.get("continue", {}).get("imcontinue", "")).strip()
        if not imcontinue:
            break

    if not image_titles:
        return

    for batch_start in range(0, len(image_titles), 50):
        if callable(should_stop) and should_stop():
            return
        batch = image_titles[batch_start : batch_start + 50]
        params = {
            "action": "query",
            "prop": "imageinfo",
            "titles": "|".join(batch),
            "iiprop": "url",
            "iiurlwidth": WIKIPEDIA_GALLERY_THUMB_SIZE,
            "format": "json",
            "utf8": 1,
        }
        try:
            response = requests.get(WIKIPEDIA_API, params=params, headers=WIKIPEDIA_HEADERS, timeout=min(timeout, 10))
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            continue

        pages = payload.get("query", {}).get("pages", {})
        for page in pages.values():
            if not isinstance(page, dict):
                continue
            file_title = str(page.get("title", "")).strip()
            imageinfo = page.get("imageinfo", [])
            if not file_title or not isinstance(imageinfo, list) or not imageinfo:
                continue
            info = imageinfo[0] if isinstance(imageinfo[0], dict) else {}
            image_url = str(info.get("thumburl") or info.get("url") or "").strip()
            if not image_url:
                continue
            image_path = _cache_wikipedia_thumbnail(image_url, timeout=timeout)
            if not image_path:
                continue
            label = Path(file_title.split(":", 1)[1]).stem.replace("_", " ").strip()
            yield {
                "title": label or file_title,
                "source_url": image_url,
                "description_url": str(info.get("descriptionurl", "")).strip(),
                "path": image_path,
            }


def _cache_wikipedia_thumbnail(url: str, *, timeout: int = 18) -> str:
    image_url = str(url or "").strip()
    if not image_url:
        return ""
    suffix = Path(image_url.split("?", 1)[0]).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        suffix = ".jpg"
    digest = hashlib.sha256(image_url.encode("utf-8")).hexdigest()[:24]
    target = WIKIPEDIA_THUMB_CACHE / f"{digest}{suffix}"
    if target.exists() and target.stat().st_size > 0:
        if _valid_cached_thumbnail(target):
            return str(target)
        try:
            target.unlink()
        except OSError:
            return ""
    try:
        WIKIPEDIA_THUMB_CACHE.mkdir(parents=True, exist_ok=True)
        response = requests.get(image_url, headers=WIKIPEDIA_HEADERS, timeout=min(timeout, 8))
        response.raise_for_status()
        content_type = str(response.headers.get("content-type", "")).lower()
        if not content_type.startswith("image/"):
            return ""
        target.write_bytes(response.content)
    except (OSError, requests.RequestException):
        return ""
    if target.exists() and target.stat().st_size > 0 and _valid_cached_thumbnail(target):
        return str(target)
    try:
        if target.exists():
            target.unlink()
    except OSError:
        pass
    return ""


def _valid_cached_thumbnail(path: Path) -> bool:
    try:
        return not QImage(str(path)).isNull()
    except RuntimeError:
        return False


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
        self.context_length = max(2000, min(86000, int(context_length or 9216)))

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
            "- Do not begin with a # title or turn the first sentence into a heading.",
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
            "- Do not end with offers like 'Do you want me to break this down further?' or similar.",
            "- Use code blocks only if the user explicitly needs code.",
            "",
            "Markdown validity rules:",
            "- Put a space after heading markers.",
            "- Leave one blank line between sections.",
            "- Start every bullet with `- ` on its own line.",
            "- If using emoji markers like checkmarks or crosses, put each emoji point on its own bullet line. Do not pack multiple emoji points into one paragraph.",
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


class WikipediaBreakdownWorker(QThread):
    failed = Signal(int, str)
    breakdown_started = Signal(int, object)
    finished = Signal(int, str, str)

    def __init__(
        self,
        *,
        request_id: int,
        ollama: OllamaService,
        model: str,
        query: str,
        context_length: int = 6000,
        profile_context: dict | None = None,
        tone: str = "",
        emoji_level: int = 2,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.ollama = ollama
        self.model = model
        self.query = query
        self.context_length = max(2000, min(86000, int(context_length or 6000)))
        self.profile_context = profile_context or {}
        self.tone = str(tone or "").strip().lower()
        self.emoji_level = max(1, min(4, int(emoji_level or 2)))
        self._stop_requested = False

    def stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        try:
            is_qn_summarizer = str(self.model).strip() == QN_SUMMARIZER_MODEL_TAG
            article = fetch_wikipedia_extract(self.query, max_words=QN_SUMMARIZER_MAX_WORDS if is_qn_summarizer else 4000)
        except (OllamaError, requests.RequestException, ValueError) as exc:
            if not self._stop_requested:
                self.failed.emit(self.request_id, f"Wikipedia research failed: {exc}")
            return

        if self._stop_requested:
            return

        self.breakdown_started.emit(self.request_id, article)

        if is_qn_summarizer:
            markdown = ""
            ai_extract = _limit_words(str(article.get("extract", "")), max_words=QN_SUMMARIZER_MAX_WORDS)
            try:
                for piece in self.ollama.stream_prompt(
                    model=self.model,
                    prompt=ai_extract,
                    temperature=0.2,
                    extra_options={
                        "num_ctx": QN_SUMMARIZER_CONTEXT_LENGTH,
                        "num_predict": -1,
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
                short_summary, long_summary = _split_qn_summarizer_output(markdown)
                self.finished.emit(self.request_id, long_summary, short_summary)
            return

        system_prompt = build_ask_ai_answer_system_prompt(
            self.profile_context,
            tone=self.tone,
            emoji_level=self.emoji_level,
        )
        ai_extract = _limit_words(str(article.get("extract", "")), max_words=3000)
        user_prompt = (
            "Break down the cleaned Wikipedia article text for a student.\n\n"
            "Rules:\n"
            "- Use the supplied Wikipedia text as the source material.\n"
            "- Explain it so the user actually understands the topic, not just a short summary.\n"
            "- Start with a direct 2 to 3 sentence plain-English overview.\n"
            "- Then explain the important ideas in a logical order.\n"
            "- Define unfamiliar terms in simple language.\n"
            "- Add a short why-it-matters section if it helps understanding.\n"
            "- Start with a short intro paragraph, then use ## section headings.\n"
            "- Do not begin with a # title or turn the first sentence into a heading.\n"
            "- For bullets, use a bold lead-in followed by a short dash explanation.\n"
            "- If using emoji markers like checkmarks or crosses, put each emoji point on its own bullet line. Do not pack multiple emoji points into one paragraph.\n"
            "- Use > for one important definition, standardization note, or takeaway when it helps readability.\n"
            "- Keep the response study-ready and concise, but do not skip necessary context.\n"
            "- Do not claim to have read beyond the supplied text.\n"
            "- Do not end with offers or follow-up questions like 'Do you want me to break this down further?' Just finish the breakdown.\n"
            "- Do not mention internal limits, prompts, or tool names.\n\n"
            f"Wikipedia article title: {article.get('title', '')}\n"
            f"Source URL: {article.get('url', '')}\n"
            f"Cleaned article word count supplied to AI: {_word_count(ai_extract)}\n\n"
            f"User query:\n{self.query.strip()}\n\n"
            f"Cleaned Wikipedia text:\n{ai_extract}"
        )

        markdown = ""
        try:
            for piece in self.ollama.stream_chat(
                model=self.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.45,
                extra_options={
                    "num_ctx": self.context_length,
                    "num_predict": -1,
                    "repeat_penalty": 1.1,
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
            self.finished.emit(self.request_id, markdown.strip(), "")


class WikipediaImagesWorker(QThread):
    failed = Signal(int, str)
    image_loaded = Signal(int, object)
    finished = Signal(int)

    def __init__(self, *, request_id: int, article_title: str, timeout: int = 18) -> None:
        super().__init__()
        self.request_id = request_id
        self.article_title = " ".join(str(article_title or "").strip().split())
        self.timeout = max(6, int(timeout or 18))
        self._stop_requested = False

    def stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        if not self.article_title:
            if not self._stop_requested:
                self.finished.emit(self.request_id)
            return
        try:
            for image in _iter_wikipedia_gallery_images(
                self.article_title,
                timeout=self.timeout,
                should_stop=lambda: self._stop_requested,
            ):
                if self._stop_requested:
                    return
                self.image_loaded.emit(self.request_id, image)
        except Exception as exc:
            if not self._stop_requested:
                self.failed.emit(self.request_id, f"Wikipedia images failed: {exc}")
            return
        if not self._stop_requested:
            self.finished.emit(self.request_id)


def _split_qn_summarizer_output(markdown: str) -> tuple[str, str]:
    text = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return "", ""
    parts = re.split(r"\n\s*\n+", text, maxsplit=1)
    if len(parts) < 2:
        marker_match = re.search(r"[#*]", text)
        if marker_match is None or marker_match.start() <= 0:
            return "", text
        short_summary = " ".join(text[: marker_match.start()].strip().split())
        long_summary = text[marker_match.start() :].strip()
        if not short_summary or not long_summary:
            return "", text
        return short_summary, long_summary
    short_summary = " ".join(parts[0].strip().split())
    long_summary = parts[1].strip()
    return short_summary, long_summary or text
