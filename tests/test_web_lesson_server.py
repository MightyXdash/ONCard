from __future__ import annotations

import json
import socket
import sys
import tempfile
from pathlib import Path
from urllib import request
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from studymate.services.data_store import DataStore
from studymate.services.web_lesson_server import WebLessonBackend, WebLessonServer
from studymate.utils.prompt_files import follow_up_study_mode_prompt
from studymate.utils.paths import AppPaths


class FakeOllama:
    def __init__(self) -> None:
        self.last_stream_chat_kwargs: dict | None = None

    def structured_chat(self, **_kwargs):
        return {
            "marks_out_of_10": 8.5,
            "how_good": 96.0,
            "state": "correct",
            "what_went_good": "The core idea was correct.",
            "what_went_bad": "",
            "what_to_improve": "Add one specific detail next time.",
        }

    def stream_chat(self, **_kwargs):
        self.last_stream_chat_kwargs = dict(_kwargs)
        yield "### Follow-up\nUse the definition, then apply it to the example."


class WebLessonServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = AppPaths(self.root)
        self.paths.ensure()
        self.store = DataStore(self.paths)
        self.store.save_profile({"name": "Ava", "age": "15", "grade": "Grade 10"})
        self.store.save_card(
            {
                "id": "card-1",
                "title": "Photosynthesis",
                "question": "What does photosynthesis do?",
                "answer": "It turns light energy into chemical energy.",
                "subject": "Science",
                "category": "Biology",
                "subtopic": "Plants",
                "hints": ["Think about light."],
                "natural_difficulty": 4,
                "mcq_answers": [
                    "Chemical energy from light",
                    "Mechanical energy from soil",
                    "Thermal energy from roots",
                    "Sound energy from leaves",
                ],
            }
        )

    def tearDown(self) -> None:
        self.store.close()
        self.tempdir.cleanup()

    def test_backend_grading_saves_attempt_with_web_lesson_source(self) -> None:
        backend = WebLessonBackend(self.store, FakeOllama())
        session = backend.start_session({"subject": "Science", "category": "Biology", "subtopic": "Plants"})

        result = backend.grade(
            {
                "session_id": session["session_id"],
                "card_id": session["card"]["id"],
                "selected_index": session["card"]["mcq"]["correct_index"],
                "response_seconds": 4.0,
                "hints_used": 1,
            }
        )

        attempts = self.store.load_attempts()
        self.assertEqual(1, len(attempts))
        self.assertEqual("web_lesson", attempts[0]["source"])
        self.assertEqual("card-1", attempts[0]["card_id"])
        self.assertGreaterEqual(attempts[0]["marks_out_of_10"], 6.0)
        self.assertEqual("correct", attempts[0]["state"])
        self.assertTrue(attempts[0]["mcq"])
        self.assertEqual(result["attempt"]["session_id"], session["session_id"])

    def test_server_uses_next_available_port_and_serves_health(self) -> None:
        occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        occupied.bind(("0.0.0.0", 0))
        occupied.listen(1)
        preferred_port = occupied.getsockname()[1]
        server = WebLessonServer(self.store, FakeOllama(), preferred_port=preferred_port)
        try:
            url = server.start()
            self.assertNotIn(f":{preferred_port}/", url)
            health_url = f"http://127.0.0.1:{server._server.server_port}/api/health"
            with request.urlopen(health_url, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(1, payload["cards"])
        finally:
            server.stop()
            occupied.close()

    def test_session_start_validates_empty_filters(self) -> None:
        backend = WebLessonBackend(self.store, FakeOllama())
        with self.assertRaises(ValueError):
            backend.start_session({"subject": "Mathematics", "category": "Algebra"})

    def test_followup_uses_file_backed_system_prompt(self) -> None:
        ollama = FakeOllama()
        backend = WebLessonBackend(self.store, ollama)
        session = backend.start_session({"subject": "Science", "category": "Biology", "subtopic": "Plants"})

        backend.followup(
            {
                "session_id": session["session_id"],
                "card_id": session["card"]["id"],
                "prompt": "Explain it again in simpler terms.",
            }
        )

        self.assertIsNotNone(ollama.last_stream_chat_kwargs)
        self.assertEqual(follow_up_study_mode_prompt(), ollama.last_stream_chat_kwargs["system_prompt"])


if __name__ == "__main__":
    unittest.main()
