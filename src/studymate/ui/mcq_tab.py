from __future__ import annotations

import textwrap

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QTextBrowser, QVBoxLayout, QWidget

from studymate.services.data_store import DataStore
from studymate.services.model_preflight import ModelPreflightService
from studymate.services.ollama_service import OllamaService
from studymate.services.study_intelligence import mark_card_completed
from studymate.ui.animated import AnimatedButton
from studymate.ui.icon_helper import IconHelper
from studymate.ui.study_tab import PromptTextEdit, SessionCardEntry, StudyTab
from studymate.workers.mcq_worker import MCQBulkWorker, MCQWorker, build_mcq_payload, cached_mcq_payload, save_mcq_payload


class MCQTab(StudyTab):
    def __init__(
        self,
        datastore: DataStore,
        ollama: OllamaService,
        icons: IconHelper,
        preflight: ModelPreflightService | None = None,
    ) -> None:
        self.mcq_worker: MCQWorker | None = None
        self.mcq_background_worker: MCQBulkWorker | None = None
        super().__init__(datastore, ollama, icons, preflight)

    def _build_study_view(self) -> QWidget:
        container = QWidget()
        root = QHBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        left_surface = self._surface()
        left_surface.setStyleSheet(
            """
            QPushButton#MCQChoiceButton {
                background-color: rgba(255, 255, 255, 0.98);
                border: 1px solid rgba(166, 182, 198, 0.58);
                border-radius: 8px;
                padding: 18px;
                color: #132232;
                font-size: 16px;
                font-weight: 800;
                text-align: left;
            }
            QPushButton#MCQChoiceButton:hover {
                background-color: rgba(255, 255, 255, 0.98);
                border-color: rgba(166, 182, 198, 0.58);
            }
            QPushButton#MCQChoiceButton[result="correct"] {
                background-color: #d9f4df;
                border-color: #58b66f;
                color: #123d20;
            }
            QPushButton#MCQChoiceButton[result="correct-red"] {
                background-color: #ffe1e1;
                border-color: #d95c5c;
                color: #6c1818;
            }
            QPushButton#MCQChoiceButton[result="selected"] {
                background-color: rgba(255, 255, 255, 0.98);
                border-color: #9aa6b2;
            }
            QWidget#MCQChoiceHost {
                background: transparent;
            }
            QPushButton#MCQChoiceButton[result="skeleton"] {
                background-color: #f2f5f8;
                border-color: #dfe6ee;
                color: transparent;
            }
            QPushButton#MCQChoiceButton[result="skeleton"]:hover {
                background-color: #f2f5f8;
                border-color: #dfe6ee;
            }
            """
        )
        left_layout = QVBoxLayout(left_surface)
        left_layout.setContentsMargins(18, 18, 18, 18)
        left_layout.setSpacing(12)

        actions = QHBoxLayout()
        self.start_btn = AnimatedButton("Start")
        self.start_btn.setProperty("skipClickSfx", True)
        self.start_btn.clicked.connect(self._open_start_dialog)
        self.refresh_study_btn = AnimatedButton("Refresh")
        self.refresh_study_btn.clicked.connect(lambda: self.reload_cards(force=True))
        actions.addStretch(1)
        actions.addWidget(self.start_btn)
        actions.addWidget(self.refresh_study_btn)
        left_layout.addLayout(actions)

        self.session_title = QLabel("Pick a card to start")
        self.session_title.setObjectName("PageTitle")
        self.session_meta = QLabel("")
        self.session_meta.setObjectName("SmallMeta")
        self.session_question = QLabel("Use the Cards subtab or press Start for the current section.")
        self.session_question.setObjectName("SectionText")
        self.session_question.setWordWrap(True)
        self.session_question.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.choice_host = QWidget()
        self.choice_host.setObjectName("MCQChoiceHost")
        self.choice_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.choice_grid = QGridLayout(self.choice_host)
        self.choice_grid.setContentsMargins(0, 0, 0, 0)
        self.choice_grid.setHorizontalSpacing(14)
        self.choice_grid.setVerticalSpacing(14)
        self.choice_buttons: list[AnimatedButton] = []
        for index in range(4):
            button = AnimatedButton("")
            button.setObjectName("MCQChoiceButton")
            button.setMinimumHeight(96)
            button.setProperty("result", "")
            button.setProperty("skipClickSfx", True)
            button.setProperty("disablePressMotion", True)
            button.set_motion_scale_range(0.0)
            button.set_motion_lift(0.0)
            button.set_motion_press_scale(0.0)
            button.clicked.connect(lambda _checked=False, idx=index: self._select_choice(idx))
            self.choice_buttons.append(button)
            self.choice_grid.addWidget(button, index // 2, index % 2)

        self.mcq_result = QLabel("")
        self.mcq_result.setObjectName("SectionText")
        self.mcq_result.setWordWrap(True)

        hint_row = QHBoxLayout()
        self.hint_btn = AnimatedButton("Show hint")
        self.hint_btn.clicked.connect(self._show_hint)
        self.hint_status = QLabel("Hints stay hidden until you press Show hint.")
        self.hint_status.setObjectName("SmallMeta")
        hint_row.addWidget(self.hint_btn)
        hint_row.addWidget(self.hint_status, 1)

        self.hints_text = QTextBrowser()
        self.hints_text.setFixedHeight(96)
        self.hints_text.setPlaceholderText("Hints will appear one by one.")

        button_row = QHBoxLayout()
        self.prev_card_btn = AnimatedButton("Back")
        self.prev_card_btn.clicked.connect(self._previous_card)
        self.next_btn = AnimatedButton("Next")
        self.next_btn.clicked.connect(self._next_card)
        self.skip_btn = AnimatedButton("Skip")
        self.skip_btn.clicked.connect(self._skip_card)
        button_row.addWidget(self.prev_card_btn)
        button_row.addStretch(1)
        button_row.addWidget(self.skip_btn)
        button_row.addWidget(self.next_btn)

        left_layout.addWidget(self.session_title)
        left_layout.addWidget(self.session_meta)
        left_layout.addWidget(self.session_question)
        left_layout.addStretch(1)
        left_layout.addWidget(self.choice_host)
        left_layout.addWidget(self.mcq_result)
        left_layout.addLayout(hint_row)
        left_layout.addWidget(self.hints_text)
        left_layout.addLayout(button_row)

        right_surface = self._surface()
        right_surface.setMinimumWidth(360)
        right_surface.setMaximumWidth(420)
        right_layout = QVBoxLayout(right_surface)
        right_layout.setContentsMargins(18, 18, 18, 18)
        right_layout.setSpacing(12)

        self.grade_summary = QLabel("Follow up on this card")
        self.grade_summary.setObjectName("PageTitle")
        self.grade_feedback = QTextBrowser()
        self.grade_feedback.setMinimumHeight(280)
        self.followup_title = QLabel("Follow up on this card")
        self.followup_title.setObjectName("SectionTitle")
        self.followup_title.hide()
        self.followup_input = PromptTextEdit()
        self.followup_input.setPlaceholderText("Ask about your question")
        self.followup_input.setMinimumHeight(120)
        self.followup_input.submitted.connect(self._run_followup)
        self.followup_btn = AnimatedButton("Ask follow up")
        self.followup_btn.clicked.connect(self._run_followup)

        right_layout.addWidget(self.grade_summary)
        right_layout.addWidget(self.grade_feedback, 1)
        right_layout.addWidget(self.followup_input)
        right_layout.addWidget(self.followup_btn)

        root.addWidget(left_surface, 2)
        root.addWidget(right_surface, 1)
        return container

    def _switch_mode(self, index: int) -> None:
        super()._switch_mode(index)
        if index == 1:
            self._layout_choice_buttons()
            self._fill_missing_mcqs_in_background()

    def activate_view(self) -> None:
        super().activate_view()
        self._fill_missing_mcqs_in_background()

    def _run_post_reload_tasks(self, generation: int) -> None:
        super()._run_post_reload_tasks(generation)
        if generation == self._post_reload_generation and not self.cards_dirty:
            self._fill_missing_mcqs_in_background()

    def _fill_missing_mcqs_in_background(self) -> None:
        if self.mcq_background_worker is not None and self.mcq_background_worker.isRunning():
            return
        model_spec = self._active_text_llm_spec()
        if not self.preflight.has_model(model_spec.key):
            return
        model_tag = self._active_text_model_tag()
        missing: list[dict] = []
        for card in self._filtered_cards():
            if not str(card.get("question", "")).strip():
                continue
            if cached_mcq_payload(self.datastore, card, model_tag) is None:
                missing.append(card)
        if not missing:
            return
        worker = MCQBulkWorker(
            cards=missing,
            datastore=self.datastore,
            ollama=self.ollama,
            model=model_tag,
            profile_context=self.datastore.load_profile(),
        )
        self.mcq_background_worker = worker
        worker.finished.connect(lambda *_args, current=worker: self._on_background_mcqs_finished(current))
        worker.failed.connect(lambda _message, current=worker: self._on_background_mcqs_finished(current))
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.start()

    def _on_background_mcqs_finished(self, worker: MCQBulkWorker) -> None:
        if self.mcq_background_worker is worker:
            self.mcq_background_worker = None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_choice_buttons()

    def _layout_choice_buttons(self) -> None:
        if not hasattr(self, "choice_grid"):
            return
        columns = self._choice_columns()
        for index, button in enumerate(self.choice_buttons):
            self.choice_grid.removeWidget(button)
            self.choice_grid.addWidget(button, index // columns, index % columns)
        entry = self._current_history_entry()
        if entry is not None and entry.get("mcq_payload"):
            self._apply_choice_heights(list((entry.get("mcq_payload") or {}).get("choices", [])))

    def _choice_columns(self) -> int:
        return 1 if self.width() < 980 else 2

    def _choice_wrap_width(self) -> int:
        columns = self._choice_columns()
        available_width = max(self.choice_host.width() or self.width(), 360)
        spacing = self.choice_grid.horizontalSpacing() or 0
        button_width = max(220, int((available_width - spacing * max(0, columns - 1)) / columns))
        return max(24, min(64, int((button_width - 44) / 8.4)))

    def _wrapped_choice_text(self, text: str) -> str:
        cleaned = " ".join(str(text or "").split())
        if not cleaned:
            return ""
        wrapped = textwrap.wrap(
            cleaned,
            width=self._choice_wrap_width(),
            break_long_words=False,
            break_on_hyphens=False,
        )
        return "\n".join(wrapped) if wrapped else cleaned

    def _apply_choice_heights(self, choices: list[object] | None = None, *, skeleton: bool = False) -> None:
        if skeleton:
            line_count = 2
        else:
            wrapped = [self._wrapped_choice_text(str(choice)).splitlines() for choice in (choices or [])]
            line_count = max((len(lines) for lines in wrapped if lines), default=1)
        button_height = max(96, min(248, 58 + (line_count * 30)))
        rows = 4 if self._choice_columns() == 1 else 2
        host_height = (button_height * rows) + ((self.choice_grid.verticalSpacing() or 0) * max(0, rows - 1))
        self.choice_host.setMinimumHeight(host_height)
        for button in self.choice_buttons:
            button.setMinimumHeight(button_height)
            button.setMaximumHeight(button_height)

    def _sync_current_entry_snapshot(self) -> None:
        entry = self._current_history_entry()
        if entry is None:
            return
        entry["hints_used"] = self.revealed_hints

    def _start_session(self, card: dict) -> None:
        session_entry = SessionCardEntry(card=card) if self.study_state and self.study_state.nna_enabled else None
        if session_entry is not None:
            self.study_state.shown_entries.append(session_entry)
        entry = {
            "card": card,
            "answer_text": "",
            "selected_index": -1,
            "mcq_payload": None,
            "hints_used": 0,
            "grade_report": None,
            "review_markdown": "",
            "status": "fresh",
            "attempt_logged": False,
            "session_entry": session_entry,
        }
        self.session_history.append(entry)
        self._show_history_entry(len(self.session_history) - 1)

    def _show_history_entry(self, index: int) -> None:
        entry = self._history_entry(index)
        if entry is None:
            return
        self.current_history_index = index
        self.current_card = entry["card"]
        self.last_grade_report = entry.get("grade_report")
        self.current_attempt_logged = bool(entry.get("attempt_logged", False))
        self.revealed_hints = int(entry.get("hints_used", 0))
        self.hint_cooldown = 0
        self.cooldown_timer.stop()

        card = entry["card"]
        title = card.get("title", "Untitled")
        if card.get("temporary"):
            title = f"{title} [TEMP]"
        self.session_title.setText(title)
        self.session_meta.setText(
            f"{card.get('subject', 'General')}  |  {card.get('category', 'All')}  |  Difficulty {card.get('natural_difficulty', 5)}/10"
        )
        self.session_question.setText(card.get("question", ""))
        visible_hints = card.get("hints", [])[: self.revealed_hints]
        self.hints_text.setPlainText("\n".join(f"{idx + 1}. {hint}" for idx, hint in enumerate(visible_hints)))
        if self.revealed_hints <= 0:
            self.hint_status.setText("Hints stay hidden until you press Show hint.")
        elif self.revealed_hints >= len(card.get("hints", [])):
            self.hint_status.setText("All hints revealed.")
        else:
            self.hint_status.setText("Previously revealed hints are shown here.")

        self.grade_summary.setText("Follow up on this card")
        if str(entry.get("status", "")) == "fresh":
            self.grade_feedback.clear()
        if entry.get("mcq_payload") is None:
            self._load_mcq_for_entry(entry)
        else:
            self._render_mcq_entry(entry)
        self._update_study_controls()

    def _load_mcq_for_entry(self, entry: dict) -> None:
        card = entry.get("card")
        if not isinstance(card, dict):
            return
        self._set_choices_busy("Preparing choices...")
        model_tag = self._active_text_model_tag()
        cached = cached_mcq_payload(self.datastore, card, model_tag)
        if cached is None and card.get("mcq_answers"):
            try:
                cached = build_mcq_payload(card, list(card.get("mcq_answers", [])), model_tag)
                save_mcq_payload(self.datastore, card, cached)
            except Exception:
                cached = None
        if cached is not None:
            entry["mcq_payload"] = cached
            self._render_mcq_entry(entry)
            return
        model_spec = self._active_text_llm_spec()
        if not self.preflight.require_model(model_spec.key, parent=self, feature_name="MCQ generation"):
            self.mcq_result.setText("MCQ choices could not be generated until the model is ready.")
            return
        worker = MCQWorker(
            card=card,
            ollama=self.ollama,
            model=model_tag,
            profile_context=self.datastore.load_profile(),
        )
        self.mcq_worker = worker
        worker.status.connect(self.mcq_result.setText)
        worker.finished.connect(lambda payload, idx=self.current_history_index: self._on_mcq_ready(idx, payload))
        worker.failed.connect(self._on_mcq_failed)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.start()

    def _on_mcq_ready(self, entry_index: int, payload: dict) -> None:
        self.mcq_worker = None
        entry = self._history_entry(entry_index)
        if entry is None:
            return
        entry["mcq_payload"] = payload
        save_mcq_payload(self.datastore, entry["card"], payload)
        if entry_index == self.current_history_index:
            self._render_mcq_entry(entry)

    def _on_mcq_failed(self, message: str) -> None:
        self.mcq_worker = None
        self.mcq_result.setText(f"MCQ generation failed: {message}")
        for button in self.choice_buttons:
            button.setText("")
            self._set_choice_result(button, "")
        self._update_study_controls()

    def _set_choices_busy(self, message: str) -> None:
        self.mcq_result.setText(message)
        self._apply_choice_heights(skeleton=True)
        for button in self.choice_buttons:
            button.setText("")
            button.setEnabled(False)
            self._set_choice_result(button, "skeleton")

    def _render_mcq_entry(self, entry: dict) -> None:
        payload = entry.get("mcq_payload") or {}
        choices = payload.get("choices", [])
        selected_index = int(entry.get("selected_index", -1))
        self.mcq_result.setText("")
        self._apply_choice_heights(list(choices))
        for index, button in enumerate(self.choice_buttons):
            button.setText(self._wrapped_choice_text(str(choices[index])) if index < len(choices) else "")
            button.setEnabled(selected_index < 0 and index < len(choices) and self.mcq_worker is None)
            result = ""
            if selected_index >= 0:
                correct_index = int(payload.get("correct_index", -1))
                if selected_index == correct_index and index == selected_index:
                    result = "correct"
                elif selected_index != correct_index and index == correct_index:
                    result = "correct-red"
                elif index == selected_index:
                    result = "selected"
            self._set_choice_result(button, result)
        if selected_index >= 0:
            correct_answer = str(payload.get("correct_answer", "")).strip()
            if selected_index == int(payload.get("correct_index", -1)):
                self.mcq_result.setText("Correct. Press Next when you are ready.")
            else:
                self.mcq_result.setText(f"Answer: {correct_answer}. Press Next when you are ready.")
        self._update_study_controls()

    def _set_choice_result(self, button: AnimatedButton, result: str) -> None:
        button.setProperty("result", result)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _select_choice(self, index: int) -> None:
        entry = self._current_history_entry()
        if entry is None or entry.get("attempt_logged") or not entry.get("mcq_payload"):
            return
        payload = entry["mcq_payload"]
        choices = list(payload.get("choices", []))
        correct_index = int(payload.get("correct_index", -1))
        if not (0 <= index < len(choices)) or not (0 <= correct_index < len(choices)):
            return
        selected_answer = str(choices[index])
        correct = index == correct_index
        entry["answer_text"] = selected_answer
        entry["selected_index"] = index
        report = {
            "marks_out_of_10": 10.0 if correct else 0.0,
            "how_good": 120.0 if correct else 0.0,
            "state": "correct" if correct else "wrong",
            "what_went_good": "Correct MCQ choice." if correct else "",
            "what_went_bad": "" if correct else "Selected the wrong MCQ choice.",
            "what_to_improve": "" if correct else f"Review the correct answer: {payload.get('correct_answer', '')}",
            "mcq": True,
            "selected_answer": selected_answer,
            "correct_answer": payload.get("correct_answer", ""),
        }
        self._apply_grade_result(entry, report)
        self._render_mcq_entry(entry)

    def _update_study_controls(self) -> None:
        entry = self._current_history_entry()
        is_latest = self.current_history_index == len(self.session_history) - 1
        pending_current = entry is not None and entry.get("status") in {"queued", "grading"}
        can_choose = bool(entry) and is_latest and not pending_current and not entry.get("attempt_logged") and self.mcq_worker is None
        self.prev_card_btn.setEnabled(self.current_history_index > 0)
        self.next_btn.setEnabled(bool(entry and entry.get("attempt_logged")) and self.mcq_worker is None)
        self.skip_btn.setEnabled(can_choose)
        self._set_hint_button_state(allow_editing=bool(entry) and self.mcq_worker is None)
        payload = entry.get("mcq_payload") if entry else None
        for button in self.choice_buttons:
            button.setEnabled(can_choose and bool(payload))

    def _skip_card(self) -> None:
        if self.mcq_worker and self.mcq_worker.isRunning():
            return
        entry = self._current_history_entry()
        if entry is None or entry.get("attempt_logged", False):
            return
        self._sync_current_entry_snapshot()
        entry["status"] = "skipped"
        entry["attempt_logged"] = True
        if self.study_state and self.current_card:
            mark_card_completed(self.study_state, self.current_card)
        self._advance_session()

    def _next_card(self) -> None:
        if self.mcq_worker and self.mcq_worker.isRunning():
            return
        entry = self._current_history_entry()
        if entry is not None and not entry.get("attempt_logged", False):
            return
        self._advance_session()

    def _finish_session(self) -> None:
        for batch_id in list(self.session_temp_batches.keys()):
            self._finalize_temp_batch(batch_id)
        avg_marks = sum(self.session_scores) / len(self.session_scores) if self.session_scores else 0.0
        avg_difficulty = (
            sum(int(card.get("natural_difficulty", 5)) for card in self.session_cards) / len(self.session_cards)
            if self.session_cards
            else 0.0
        )
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.information(
            self,
            "MCQ session complete",
            f"Average marks: {avg_marks:.1f}/10\nAverage difficulty: {avg_difficulty:.1f}/10",
        )
        self._cancel_session_prep()
        self.current_card = None
        self.study_state = None
        self.session_id = ""
        self.session_queue = []
        self.session_cards = []
        self.session_scores = []
        self.session_history = []
        self.current_history_index = -1
        self.queued_grade_indexes = []
        self.active_queue_entry_index = -1
        self.session_end_requested = False
        self.session_temp_batches = {}
        self.session_title.setText("Pick a card to start")
        self.session_meta.setText("")
        self.session_question.setText("Use the Cards subtab or press Start for the current section.")
        self.mcq_result.clear()
        self.hints_text.clear()
        self.grade_feedback.clear()
        self.grade_summary.setText("Follow up on this card")
        self.prev_card_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        self.hint_btn.setEnabled(False)
        for button in self.choice_buttons:
            button.setText("")
            button.setEnabled(False)
            self._set_choice_result(button, "")
            button.setMaximumHeight(16777215)

    def _build_followup_context(self) -> str:
        if not self.current_card:
            return ""
        entry = self._current_history_entry() or {}
        payload = entry.get("mcq_payload") or {}
        parts = [
            f"Question: {self.current_card.get('question', '')}",
            f"Correct answer: {payload.get('correct_answer', '')}",
            f"Hints: {', '.join(self.current_card.get('hints', []))}",
        ]
        return "\n".join(parts) + "\n"
