from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from studymate.ui.create_tab import (
    CREATE_SESSION_FTC,
    CREATE_SESSION_IDLE,
    CREATE_SESSION_QUESTION,
    resolve_create_session_kind,
    resolve_ftc_primary_action,
    should_show_create_selector,
)


class CreateTabStateTests(unittest.TestCase):
    def test_selector_only_shows_for_idle_session(self) -> None:
        self.assertTrue(should_show_create_selector(CREATE_SESSION_IDLE))
        self.assertFalse(should_show_create_selector(CREATE_SESSION_QUESTION))
        self.assertFalse(should_show_create_selector(CREATE_SESSION_FTC))

    def test_ftc_work_reopens_ftc_session(self) -> None:
        session = resolve_create_session_kind(
            preferred_kind=CREATE_SESSION_IDLE,
            has_manual_work=False,
            has_ftc_work=True,
            has_question_draft=False,
            has_ftc_draft=False,
        )
        self.assertEqual(CREATE_SESSION_FTC, session)

    def test_manual_work_reopens_question_session(self) -> None:
        session = resolve_create_session_kind(
            preferred_kind=CREATE_SESSION_IDLE,
            has_manual_work=True,
            has_ftc_work=False,
            has_question_draft=False,
            has_ftc_draft=False,
        )
        self.assertEqual(CREATE_SESSION_QUESTION, session)

    def test_preferred_kind_breaks_tie_when_both_workflows_have_state(self) -> None:
        question_session = resolve_create_session_kind(
            preferred_kind=CREATE_SESSION_QUESTION,
            has_manual_work=True,
            has_ftc_work=True,
            has_question_draft=False,
            has_ftc_draft=False,
        )
        ftc_session = resolve_create_session_kind(
            preferred_kind=CREATE_SESSION_FTC,
            has_manual_work=True,
            has_ftc_work=True,
            has_question_draft=False,
            has_ftc_draft=False,
        )
        self.assertEqual(CREATE_SESSION_QUESTION, question_session)
        self.assertEqual(CREATE_SESSION_FTC, ftc_session)

    def test_ftc_primary_action_switches_from_generate_to_queue(self) -> None:
        self.assertEqual("generate", resolve_ftc_primary_action(has_active_run=False, staged_job_ready=True))
        self.assertEqual("queue", resolve_ftc_primary_action(has_active_run=True, staged_job_ready=True))
        self.assertEqual("busy", resolve_ftc_primary_action(has_active_run=True, staged_job_ready=False))
        self.assertEqual("disabled", resolve_ftc_primary_action(has_active_run=False, staged_job_ready=False))


if __name__ == "__main__":
    unittest.main()
