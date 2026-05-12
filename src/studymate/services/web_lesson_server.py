from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import random
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from urllib.parse import parse_qs, urlparse
import uuid

from studymate.constants import SUBJECT_TAXONOMY
from studymate.services.data_store import DataStore
from studymate.services.model_registry import resolve_feature_text_model_tag
from studymate.services.ollama_service import OllamaError, OllamaService
from studymate.services.study_intelligence import (
    StudySessionState,
    build_session_state,
    card_cluster_key,
    mark_card_completed,
    next_card_for_session,
    register_grade_result,
)
from studymate.utils.prompt_files import follow_up_study_mode_prompt
from studymate.workers.mcq_worker import build_mcq_payload, cached_mcq_payload, generate_mcq_payload, save_mcq_payload


@dataclass
class WebLessonSession:
    session_id: str
    state: StudySessionState
    current_card_id: str = ""


def local_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            address = sock.getsockname()[0]
            if address:
                return str(address)
    except OSError:
        pass
    return "127.0.0.1"


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _safe_card(card: dict, *, mcq_payload: dict | None = None) -> dict:
    payload = {
        "id": _normalize_text(card.get("id")),
        "title": _normalize_text(card.get("title")) or "Untitled card",
        "question": _normalize_text(card.get("question")),
        "subject": _normalize_text(card.get("subject")) or "General",
        "category": _normalize_text(card.get("category")) or "All",
        "subtopic": _normalize_text(card.get("subtopic")) or "All",
        "hints": [str(item) for item in list(card.get("hints", [])) if str(item).strip()],
        "natural_difficulty": int(card.get("natural_difficulty", 5) or 5),
    }
    if isinstance(mcq_payload, dict):
        payload["mcq"] = {
            "choices": [str(choice) for choice in list(mcq_payload.get("choices", []))],
            "correct_index": int(mcq_payload.get("correct_index", -1)),
        }
    return payload


def _card_expected_answer(card: dict) -> str:
    answer = _normalize_text(card.get("answer"))
    if answer:
        return answer
    answers = card.get("mcq_answers", [])
    if isinstance(answers, list) and answers:
        return _normalize_text(answers[0])
    return ""


def _format_review_markdown(report: dict) -> str:
    score = float(report.get("marks_out_of_10", 0) or 0)
    state = str(report.get("state", "wrong")).title()
    parts: list[str] = [f"### Final score: {score:.1f}/10 | {state}"]
    good = _normalize_text(report.get("what_went_good"))
    bad = _normalize_text(report.get("what_went_bad"))
    improve = _normalize_text(report.get("what_to_improve"))
    if good:
        parts.append(f"- Good: {good}")
    if bad:
        parts.append(f"- Bad: {bad}")
    if improve:
        parts.append(f"- Improve: {improve}")
    if score >= 9:
        parts.append("- Coach: Great work. You got the core meaning right.")
    elif score <= 5:
        parts.append("- Coach: Keep going. Use follow-up help to work through it step by step.")
    return "\n\n".join(parts)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _mcq_target_seconds(card: dict, hints_used: int) -> float:
    question_words = len(str(card.get("question", "")).split())
    difficulty = _clamp(float(card.get("natural_difficulty", 5) or 5), 1.0, 10.0)
    base_seconds = 6.0 + (difficulty * 1.55) + min(question_words, 28) * 0.33
    hint_adjustment = min(max(hints_used, 0), 3) * 2.2
    return _clamp(base_seconds + hint_adjustment, 7.5, 36.0)


def _mcq_speed_factor(response_seconds: float, target_seconds: float) -> float:
    if target_seconds <= 0:
        return 0.0
    ratio = max(0.0, response_seconds) / target_seconds
    if ratio <= 0.65:
        return 1.0
    if ratio <= 1.0:
        return 1.0 - ((ratio - 0.65) * 0.22)
    if ratio <= 2.4:
        return max(0.20, 0.78 - ((ratio - 1.0) * 0.42))
    return max(0.0, 0.20 - min(0.20, (ratio - 2.4) * 0.08))


def _mcq_grade_report(card: dict, payload: dict, selected_index: int, response_seconds: float, hints_used: int) -> dict:
    choices = list(payload.get("choices", []))
    correct_index = int(payload.get("correct_index", -1))
    if not (0 <= selected_index < len(choices)) or not (0 <= correct_index < len(choices)):
        raise ValueError("Choose one MCQ answer before submitting.")
    selected_answer = str(choices[selected_index])
    correct = selected_index == correct_index
    response_seconds = round(max(0.2, float(response_seconds or 0.2)), 2)
    hints_used = max(0, int(hints_used or 0))
    target_seconds = _mcq_target_seconds(card, hints_used)
    speed_factor = _mcq_speed_factor(response_seconds, target_seconds)
    hint_multiplier = max(0.55, 1.0 - (min(hints_used, 4) * 0.12))
    difficulty = _clamp(float(card.get("natural_difficulty", 5) or 5), 1.0, 10.0)
    difficulty_bonus = ((difficulty - 5.0) / 5.0) * 0.4
    if correct:
        marks = (5.6 + (4.1 * speed_factor) + difficulty_bonus) * hint_multiplier
        how_good = _clamp((89.0 + (11.0 * speed_factor) + (difficulty_bonus * 4.0)) - (hints_used * 2.5), 0.0, 100.0)
    else:
        marks = max(0.0, (0.4 + (3.0 * speed_factor) + max(0.0, difficulty_bonus * 0.5)) * (hint_multiplier - 0.08))
        how_good = _clamp((10.0 + (34.0 * speed_factor) + (difficulty_bonus * 3.0)) - (hints_used * 3.5), 0.0, 55.0)
    return {
        "marks_out_of_10": round(_clamp(marks, 0.0, 10.0), 1),
        "how_good": round(how_good, 4),
        "state": "correct" if correct else "wrong",
        "what_went_good": "Correct MCQ choice." if correct else "",
        "what_went_bad": "" if correct else "Selected the wrong MCQ choice.",
        "what_to_improve": "" if correct else f"Review the correct answer: {payload.get('correct_answer', '')}",
        "mcq": True,
        "hide_score": True,
        "selected_answer": selected_answer,
        "selected_index": selected_index,
        "correct_answer": payload.get("correct_answer", ""),
        "correct_index": correct_index,
        "response_time_seconds": response_seconds,
        "answered_at": datetime.now(timezone.utc).isoformat(),
        "scoring_factors": {
            "correct": correct,
            "target_seconds": round(target_seconds, 2),
            "speed_factor": round(speed_factor, 4),
            "hint_multiplier": round(hint_multiplier, 4),
            "difficulty_bonus": round(difficulty_bonus, 4),
            "hints_used": hints_used,
        },
    }


class WebLessonBackend:
    def __init__(self, datastore: DataStore, ollama: OllamaService) -> None:
        self.datastore = datastore
        self.ollama = ollama
        self._sessions: dict[str, WebLessonSession] = {}
        self._lock = Lock()

    def bootstrap(self) -> dict:
        cards = self._filtered_cards({})
        return {
            "app": "ONCard Web Lesson",
            "profile": self.datastore.load_profile(),
            "subjects": list(SUBJECT_TAXONOMY.keys()),
            "subject_counts": self.datastore.card_counts_by_subject(),
            "cards": [_safe_card(card) for card in cards[:96]],
            "total_cards": len(cards),
        }

    def cards(self, query: dict[str, list[str]]) -> dict:
        cards = self._filtered_cards(query)
        return {"cards": [_safe_card(card) for card in cards[:200]], "total_cards": len(cards)}

    def start_session(self, payload: dict) -> dict:
        cards = self._filtered_cards(
            {
                "subject": [_normalize_text(payload.get("subject"))],
                "category": [_normalize_text(payload.get("category"))],
                "subtopic": [_normalize_text(payload.get("subtopic"))],
                "q": [_normalize_text(payload.get("q"))],
            }
        )
        if not cards:
            raise ValueError("No cards match this lesson filter.")
        state = build_session_state(cards, self._scope_label(payload), random.Random())
        card = next_card_for_session(state, None)
        if card is None:
            raise ValueError("Could not start a lesson from these cards.")
        mcq_payload = self._mcq_payload_for_card(card)
        session_id = str(uuid.uuid4())
        session = WebLessonSession(session_id=session_id, state=state, current_card_id=str(card.get("id", "")))
        with self._lock:
            self._sessions[session_id] = session
        return {"session_id": session_id, "card": _safe_card(card, mcq_payload=mcq_payload), "remaining": len(state.unseen_ids)}

    def next_card(self, payload: dict) -> dict:
        session = self._require_session(_normalize_text(payload.get("session_id")))
        card = next_card_for_session(session.state, None)
        if card is None:
            return {"done": True, "card": None, "remaining": 0}
        mcq_payload = self._mcq_payload_for_card(card)
        session.current_card_id = str(card.get("id", ""))
        return {"done": False, "card": _safe_card(card, mcq_payload=mcq_payload), "remaining": len(session.state.unseen_ids)}

    def grade(self, payload: dict) -> dict:
        session = self._require_session(_normalize_text(payload.get("session_id")))
        card_id = _normalize_text(payload.get("card_id")) or session.current_card_id
        card = session.state.card_lookup.get(card_id)
        if not isinstance(card, dict):
            raise ValueError("Card not found in this lesson session.")
        mcq_payload = self._mcq_payload_for_card(card)
        selected_index = int(payload.get("selected_index", -1))
        report = _mcq_grade_report(
            card,
            mcq_payload,
            selected_index,
            float(payload.get("response_seconds", 0.2) or 0.2),
            int(payload.get("hints_used", 0) or 0),
        )
        report["review_markdown"] = _format_review_markdown(report)
        attempt = self._attempt_payload(
            session=session,
            card=card,
            user_answer=str(report.get("selected_answer", "")),
            hints_used=int(payload.get("hints_used", 0) or 0),
            report=report,
        )
        self.datastore.save_attempt(attempt)
        result = register_grade_result(session.state, card, report)
        mark_card_completed(session.state, card)
        return {
            "report": report,
            "mcq": {"correct_index": int(mcq_payload.get("correct_index", -1)), "correct_answer": str(mcq_payload.get("correct_answer", ""))},
            "attempt": {"card_id": attempt.get("card_id"), "session_id": attempt.get("session_id")},
            "weak": bool(result.get("weak")),
        }

    def followup(self, payload: dict) -> dict:
        session = self._require_session(_normalize_text(payload.get("session_id")))
        card_id = _normalize_text(payload.get("card_id")) or session.current_card_id
        card = session.state.card_lookup.get(card_id)
        if not isinstance(card, dict):
            raise ValueError("Card not found in this lesson session.")
        prompt = _normalize_text(payload.get("prompt")) or "Explain this to me step by step."
        ai_settings = self.datastore.load_ai_settings()
        model = resolve_feature_text_model_tag(ai_settings, "followup_context_length")
        context = (
            f"Question: {card.get('question', '')}\n"
            f"Correct answer: {_card_expected_answer(card)}\n"
            f"Hints: {', '.join(card.get('hints', []))}\n"
        )
        system_prompt = follow_up_study_mode_prompt()
        pieces: list[str] = []
        for piece in self.ollama.stream_chat(
            model=model,
            system_prompt=system_prompt,
            user_prompt=f"{context}\n\nFollow-up request:\n{prompt}",
            temperature=0.3,
            extra_options={"num_ctx": int(ai_settings.get("followup_context_length", 8192) or 8192)},
        ):
            pieces.append(piece)
        return {"markdown": "".join(pieces).strip()}

    def health(self) -> dict:
        return {
            "ok": True,
            "cards": len(self.datastore.list_all_cards()),
            "sessions": len(self._sessions),
        }

    def _require_session(self, session_id: str) -> WebLessonSession:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("Lesson session expired or does not exist. Start a new lesson.")
        return session

    def _filtered_cards(self, query: dict[str, list[str]]) -> list[dict]:
        subject = _first_query_value(query, "subject")
        category = _first_query_value(query, "category")
        subtopic = _first_query_value(query, "subtopic")
        text = _first_query_value(query, "q").lower()
        cards = self.datastore.list_all_cards()
        if subject and subject != "All Subjects":
            cards = [card for card in cards if _normalize_text(card.get("subject")) == subject]
        if category and category != "All":
            cards = [card for card in cards if _normalize_text(card.get("category")) == category]
        if subtopic and subtopic != "All":
            cards = [card for card in cards if _normalize_text(card.get("subtopic")) == subtopic]
        if text:
            cards = [
                card
                for card in cards
                if text
                in " ".join(
                    [
                        _normalize_text(card.get("title")).lower(),
                        _normalize_text(card.get("question")).lower(),
                        _normalize_text(card.get("subject")).lower(),
                        _normalize_text(card.get("category")).lower(),
                        _normalize_text(card.get("subtopic")).lower(),
                    ]
                )
            ]
        return cards

    def _mcq_payload_for_card(self, card: dict) -> dict:
        ai_settings = self.datastore.load_ai_settings()
        model = resolve_feature_text_model_tag(ai_settings, "mcq_context_length")
        cached = cached_mcq_payload(self.datastore, card, model)
        if cached is not None:
            return cached
        if card.get("mcq_answers"):
            payload = build_mcq_payload(card, list(card.get("mcq_answers", [])), model)
            save_mcq_payload(self.datastore, card, payload)
            return payload
        payload = generate_mcq_payload(
            card=card,
            ollama=self.ollama,
            model=model,
            profile_context=self.datastore.load_profile(),
            context_length=int(ai_settings.get("mcq_context_length", 8192) or 8192),
            difficulty="slightly_harder",
        )
        save_mcq_payload(self.datastore, card, payload)
        updated = dict(card)
        updated["answer"] = str(payload.get("correct_answer", "")).strip()
        updated["mcq_answers"] = list(payload.get("answers", []))
        self.datastore.save_card(updated)
        card.update(updated)
        return payload

    @staticmethod
    def _scope_label(payload: dict) -> str:
        parts = [
            _normalize_text(payload.get("subject")) or "All Subjects",
            _normalize_text(payload.get("category")),
            _normalize_text(payload.get("subtopic")),
        ]
        return " / ".join(part for part in parts if part and part != "All")

    @staticmethod
    def _attempt_payload(
        *,
        session: WebLessonSession,
        card: dict,
        user_answer: str,
        hints_used: int,
        report: dict,
    ) -> dict:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session.session_id,
            "card_id": card.get("id"),
            "subject": card.get("subject"),
            "category": card.get("category"),
            "subtopic": card.get("subtopic"),
            "question": card.get("question"),
            "answer_text": user_answer,
            "hints_used": max(0, hints_used),
            "graded": True,
            "temporary": bool(card.get("temporary", False)),
            "topic_cluster_key": card_cluster_key(session.state, card),
            "marks_out_of_10": report.get("marks_out_of_10"),
            "how_good": report.get("how_good"),
            "state": report.get("state"),
            "what_went_bad": report.get("what_went_bad"),
            "what_went_good": report.get("what_went_good"),
            "what_to_improve": report.get("what_to_improve"),
            "mcq": bool(report.get("mcq", False)),
            "selected_answer": report.get("selected_answer"),
            "correct_answer": report.get("correct_answer"),
            "response_time_seconds": report.get("response_time_seconds"),
            "scoring_factors": dict(report.get("scoring_factors", {})) if isinstance(report.get("scoring_factors"), dict) else {},
            "source": "web_lesson",
        }


class WebLessonServer:
    def __init__(self, datastore: DataStore, ollama: OllamaService, *, preferred_port: int = 8765) -> None:
        self.backend = WebLessonBackend(datastore, ollama)
        self.preferred_port = preferred_port
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None
        self.url = ""

    @property
    def is_running(self) -> bool:
        return self._server is not None and self._thread is not None and self._thread.is_alive()

    def start(self) -> str:
        if self.is_running:
            return self.url
        handler = self._handler_class(self.backend)
        last_error: OSError | None = None
        for port in [self.preferred_port, *range(self.preferred_port + 1, self.preferred_port + 30)]:
            try:
                server = ThreadingHTTPServer(("0.0.0.0", port), handler)
                server.daemon_threads = True
                self._server = server
                self.url = f"http://{local_lan_ip()}:{port}/"
                break
            except OSError as exc:
                last_error = exc
        if self._server is None:
            raise OSError(f"Could not start Web Lesson server: {last_error}")
        self._thread = Thread(target=self._server.serve_forever, name="ONCardWebLessonServer", daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None
        self.url = ""

    @staticmethod
    def _handler_class(backend: WebLessonBackend):
        class Handler(BaseHTTPRequestHandler):
            server_version = "ONCardWebLesson/1.0"

            def log_message(self, _format: str, *args) -> None:
                return

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                try:
                    if parsed.path in {"", "/"}:
                        self._send_text(WEB_LESSON_HTML, content_type="text/html; charset=utf-8")
                    elif parsed.path == "/api/bootstrap":
                        self._send_json(backend.bootstrap())
                    elif parsed.path == "/api/cards":
                        self._send_json(backend.cards(parse_qs(parsed.query)))
                    elif parsed.path == "/api/health":
                        self._send_json(backend.health())
                    else:
                        self._send_error(404, "Not found")
                except Exception as exc:
                    self._send_exception(exc)

            def do_POST(self) -> None:
                parsed = urlparse(self.path)
                try:
                    payload = self._read_json()
                    if parsed.path == "/api/session/start":
                        self._send_json(backend.start_session(payload))
                    elif parsed.path == "/api/session/next":
                        self._send_json(backend.next_card(payload))
                    elif parsed.path == "/api/grade":
                        self._send_json(backend.grade(payload))
                    elif parsed.path == "/api/followup":
                        self._send_json(backend.followup(payload))
                    else:
                        self._send_error(404, "Not found")
                except Exception as exc:
                    self._send_exception(exc)

            def _read_json(self) -> dict:
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length) if length > 0 else b"{}"
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    raise ValueError("Invalid JSON request.") from exc
                if not isinstance(payload, dict):
                    raise ValueError("JSON request must be an object.")
                return payload

            def _send_json(self, payload: dict, status: int = 200) -> None:
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _send_text(self, text: str, *, content_type: str) -> None:
                data = text.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _send_error(self, status: int, message: str) -> None:
                self._send_json({"error": message}, status=status)

            def _send_exception(self, exc: Exception) -> None:
                if isinstance(exc, (ValueError, OllamaError)):
                    self._send_error(400, str(exc))
                else:
                    self._send_error(500, str(exc))

        return Handler


def _first_query_value(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key, [])
    if not values:
        return ""
    return _normalize_text(values[0])


WEB_LESSON_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ONCard MCQ Lesson</title>
  <style>
    :root { color-scheme: light; --ink:#172033; --muted:#667085; --line:rgba(25,34,54,.12); --blue:#2357d7; --green:#0f8a65; --red:#b42318; --paper:rgba(255,255,255,.78); }
    * { box-sizing:border-box; }
    body { margin:0; min-height:100vh; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color:var(--ink); background: radial-gradient(circle at 20% 10%, #f8fbff 0, transparent 34%), linear-gradient(135deg,#dfe8f5,#f7f9fc 42%,#edf4f1); }
    .app { width:min(1440px, 100%); margin:0 auto; padding:18px; min-height:100vh; display:grid; gap:14px; grid-template-rows:auto 1fr; }
    header { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:14px 16px; border:1px solid var(--line); border-radius:22px; background:rgba(255,255,255,.62); backdrop-filter:blur(22px) saturate(1.25); box-shadow:0 18px 60px rgba(31,43,65,.10); }
    h1 { font-size:18px; margin:0; letter-spacing:0; }
    .meta { color:var(--muted); font-size:13px; }
    .grid { display:grid; grid-template-columns:320px 1fr; gap:14px; min-height:0; }
    .panel { border:1px solid var(--line); border-radius:24px; background:var(--paper); backdrop-filter:blur(26px) saturate(1.2); box-shadow:0 20px 70px rgba(31,43,65,.12); min-height:0; }
    aside { padding:14px; display:flex; flex-direction:column; gap:12px; }
    main { padding:16px; display:grid; grid-template-columns:minmax(0,1fr) minmax(300px,430px); gap:16px; }
    input, textarea, select { width:100%; border:1px solid var(--line); border-radius:14px; background:rgba(255,255,255,.72); color:var(--ink); font:inherit; padding:11px 12px; outline:none; }
    textarea { resize:vertical; min-height:104px; }
    button { border:1px solid transparent; border-radius:14px; background:#111827; color:white; font:600 14px inherit; padding:11px 14px; cursor:pointer; }
    button.secondary { background:rgba(255,255,255,.76); color:var(--ink); border-color:var(--line); }
    button:disabled { opacity:.5; cursor:not-allowed; }
    .filters { display:grid; gap:8px; }
    .cards { overflow:auto; display:grid; gap:8px; padding-right:2px; }
    .card-row { text-align:left; border:1px solid var(--line); background:rgba(255,255,255,.62); color:var(--ink); border-radius:16px; padding:10px 12px; }
    .card-row strong { display:block; font-size:14px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .card-row span { display:block; color:var(--muted); font-size:12px; margin-top:3px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .study { display:flex; flex-direction:column; gap:14px; min-width:0; }
    .question { min-height:210px; display:flex; flex-direction:column; justify-content:center; gap:10px; padding:20px; border-radius:22px; background:rgba(255,255,255,.64); border:1px solid var(--line); }
    .question h2 { margin:0; font-size:clamp(22px, 3vw, 34px); line-height:1.1; letter-spacing:0; }
    .question p { margin:0; color:var(--muted); line-height:1.55; }
    .actions { display:flex; flex-wrap:wrap; gap:8px; }
    .feedback { overflow:auto; padding:16px; border-radius:22px; background:rgba(255,255,255,.62); border:1px solid var(--line); line-height:1.55; }
    .feedback h3 { margin-top:0; }
    .score { color:var(--green); font-weight:800; }
    .side-study { display:flex; flex-direction:column; gap:12px; min-width:0; }
    .choices { display:grid; gap:10px; }
    .choice { width:100%; min-height:54px; text-align:left; background:rgba(255,255,255,.76); color:var(--ink); border:1px solid var(--line); border-radius:16px; padding:13px 14px; line-height:1.35; }
    .choice:hover { border-color:rgba(35,87,215,.35); }
    .choice.selected { border-color:var(--blue); box-shadow:0 0 0 3px rgba(35,87,215,.12); }
    .choice.correct { background:rgba(15,138,101,.12); border-color:rgba(15,138,101,.55); color:#075f48; }
    .choice.wrong { background:rgba(180,35,24,.10); border-color:rgba(180,35,24,.45); color:#7a271a; }
    .status { color:var(--muted); font-size:13px; min-height:18px; }
    .hint { padding:10px 12px; border-radius:14px; background:rgba(35,87,215,.08); color:#24406b; }
    @media (max-width: 1100px) { .grid { grid-template-columns:1fr; } aside { max-height:315px; } main { grid-template-columns:1fr; } .choices { grid-template-columns:repeat(2,minmax(0,1fr)); } }
    @media (max-width: 700px) { .app { padding:10px; } header { border-radius:18px; align-items:flex-start; flex-direction:column; } .panel { border-radius:20px; } main, aside { padding:12px; } .choices { grid-template-columns:1fr; } .actions { position:sticky; bottom:0; padding:10px 0 0; background:linear-gradient(transparent, rgba(247,249,252,.96) 24%); } button { flex:1; min-width:128px; } .question { min-height:168px; padding:16px; } .cards { max-height:190px; } }
  </style>
</head>
<body>
  <div class="app">
    <header>
      <div><h1>ONCard MCQ Lesson</h1><div class="meta" id="profile">Studying from your desktop app</div></div>
      <div class="status" id="status">Connecting...</div>
    </header>
    <div class="grid">
      <aside class="panel">
        <div class="filters">
          <input id="search" placeholder="Search cards">
          <select id="subject"><option>All Subjects</option></select>
          <input id="category" placeholder="Category, or All" value="All">
          <input id="subtopic" placeholder="Subtopic, or All" value="All">
          <button id="start">Start MCQ Lesson</button>
        </div>
        <div class="meta" id="count"></div>
        <div class="cards" id="cards"></div>
      </aside>
      <main class="panel">
        <section class="study">
          <div class="question">
            <div class="meta" id="cardMeta">No lesson started</div>
            <h2 id="cardTitle">Pick a filter and start</h2>
            <p id="question">Choose the correct answer. Your score saves back to ONCard.</p>
          </div>
          <div id="hints"></div>
          <div class="feedback" id="feedback">Results and follow-up help will appear here.</div>
        </section>
        <section class="side-study">
          <div class="choices" id="choices"></div>
          <div class="actions">
            <button class="secondary" id="hint">Hint</button>
            <button id="submit">Submit</button>
            <button class="secondary" id="next">Next</button>
          </div>
          <textarea id="followPrompt" placeholder="Ask a follow-up after grading"></textarea>
          <button class="secondary" id="follow">Ask Follow-up</button>
        </section>
      </main>
    </div>
  </div>
<script>
const state = { sessionId:"", current:null, cards:[], hintsUsed:0, shownHints:[], selectedIndex:-1, presentedAt:0, answered:false };
const $ = id => document.getElementById(id);
async function api(path, options={}) {
  const res = await fetch(path, { headers:{ "Content-Type":"application/json" }, ...options });
  const data = await res.json();
  if (!res.ok || data.error) throw new Error(data.error || "Request failed");
  return data;
}
function filters() { return { subject:$("subject").value, category:$("category").value || "All", subtopic:$("subtopic").value || "All", q:$("search").value || "" }; }
function setStatus(text) { $("status").textContent = text; }
function renderCards(cards) {
  $("cards").innerHTML = "";
  for (const card of cards) {
    const btn = document.createElement("button");
    btn.className = "card-row";
    btn.innerHTML = `<strong>${escapeHtml(card.title)}</strong><span>${escapeHtml(card.subject)} / ${escapeHtml(card.category)} / ${escapeHtml(card.subtopic)}</span>`;
    btn.onclick = () => setStatus("Press Start MCQ Lesson to study this filtered set.");
    $("cards").appendChild(btn);
  }
}
function showCard(card, clear=true) {
  state.current = card; state.hintsUsed = 0; state.shownHints = []; state.selectedIndex = -1; state.presentedAt = performance.now(); state.answered = false;
  $("cardMeta").textContent = `${card.subject} / ${card.category} / ${card.subtopic}`;
  $("cardTitle").textContent = card.title;
  $("question").textContent = card.question;
  $("hints").innerHTML = "";
  renderChoices(card.mcq?.choices || []);
  if (clear) { $("feedback").textContent = "Choose an answer, then submit it."; }
}
function renderChoices(choices) {
  $("choices").innerHTML = "";
  choices.forEach((choice, index) => {
    const btn = document.createElement("button");
    btn.className = "choice";
    btn.textContent = choice;
    btn.onclick = () => selectChoice(index);
    $("choices").appendChild(btn);
  });
}
function selectChoice(index) {
  if (state.answered) return;
  state.selectedIndex = index;
  [...$("choices").children].forEach((el, i) => el.classList.toggle("selected", i === index));
}
async function refreshCards() {
  const params = new URLSearchParams(filters());
  const data = await api(`/api/cards?${params}`);
  state.cards = data.cards; $("count").textContent = `${data.total_cards} cards available`; renderCards(data.cards);
}
async function startLesson() {
  setStatus("Starting lesson...");
  const data = await api("/api/session/start", { method:"POST", body:JSON.stringify(filters()) });
  state.sessionId = data.session_id; showCard(data.card); setStatus("Lesson running");
}
async function nextCard() {
  if (!state.sessionId) return startLesson();
  const data = await api("/api/session/next", { method:"POST", body:JSON.stringify({ session_id:state.sessionId }) });
  if (data.done) { $("feedback").textContent = "Lesson complete. Start again when ready."; setStatus("Lesson complete"); return; }
  showCard(data.card); setStatus(`${data.remaining} cards left in this queue`);
}
function showHint() {
  if (!state.current) return;
  const hints = state.current.hints || [];
  if (state.hintsUsed >= hints.length) { setStatus("No more hints for this card."); return; }
  state.shownHints.push(hints[state.hintsUsed]); state.hintsUsed += 1;
  $("hints").innerHTML = state.shownHints.map((h,i)=>`<div class="hint">${i+1}. ${escapeHtml(h)}</div>`).join("");
}
async function submitAnswer() {
  if (!state.sessionId) await startLesson();
  if (!state.current) return;
  if (state.selectedIndex < 0) { setStatus("Choose an answer before submitting."); return; }
  setStatus("Checking...");
  const responseSeconds = Math.max(0.2, (performance.now() - state.presentedAt) / 1000);
  const data = await api("/api/grade", { method:"POST", body:JSON.stringify({ session_id:state.sessionId, card_id:state.current.id, selected_index:state.selectedIndex, response_seconds:responseSeconds, hints_used:state.hintsUsed }) });
  const report = data.report;
  state.answered = true;
  [...$("choices").children].forEach((el, i) => {
    el.disabled = true;
    if (i === data.mcq.correct_index) el.classList.add("correct");
    if (i === state.selectedIndex && i !== data.mcq.correct_index) el.classList.add("wrong");
  });
  $("feedback").innerHTML = `<div class="score">${escapeHtml(report.state)} · ${Number(report.marks_out_of_10).toFixed(1)}/10 saved</div>${markdownish(report.review_markdown || "")}`;
  setStatus("Score saved to ONCard");
}
async function followup() {
  if (!state.sessionId || !state.current) return;
  setStatus("Asking ONCard...");
  const data = await api("/api/followup", { method:"POST", body:JSON.stringify({ session_id:state.sessionId, card_id:state.current.id, prompt:$("followPrompt").value }) });
  $("feedback").innerHTML = markdownish(data.markdown || "");
  setStatus("Follow-up ready");
}
function markdownish(text) {
  return escapeHtml(text).replace(/^### (.*)$/gm, "<h3>$1</h3>").replace(/^- (.*)$/gm, "<div>• $1</div>").replace(/\n/g, "<br>");
}
function escapeHtml(text) { return String(text ?? "").replace(/[&<>"']/g, ch => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[ch])); }
async function init() {
  try {
    const boot = await api("/api/bootstrap");
    $("profile").textContent = `${boot.profile?.name || "Student"} studying from ONCard`;
    for (const subject of boot.subjects || []) { const opt=document.createElement("option"); opt.textContent=subject; $("subject").appendChild(opt); }
    state.cards = boot.cards || []; $("count").textContent = `${boot.total_cards} cards available`; renderCards(state.cards); setStatus("Ready");
  } catch (err) { setStatus(err.message); }
}
$("start").onclick = startLesson; $("next").onclick = nextCard; $("hint").onclick = showHint; $("submit").onclick = submitAnswer; $("follow").onclick = followup;
["search","subject","category","subtopic"].forEach(id => $(id).addEventListener("change", () => refreshCards().catch(err => setStatus(err.message))));
$("search").addEventListener("input", () => { clearTimeout(window._searchTimer); window._searchTimer=setTimeout(()=>refreshCards().catch(err=>setStatus(err.message)), 250); });
init();
</script>
</body>
</html>"""
