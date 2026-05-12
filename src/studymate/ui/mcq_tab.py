from __future__ import annotations

from datetime import datetime, timezone
import textwrap
import time

from PySide6.QtCore import QEvent, QPropertyAnimation, Qt, QEasingCurve
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QGraphicsDropShadowEffect, QSizePolicy, QStackedLayout, QTextBrowser, QVBoxLayout, QWidget

from studymate.services.data_store import DataStore
from studymate.services.model_preflight import ModelPreflightService
from studymate.services.ollama_service import OllamaService
from studymate.services.study_intelligence import mark_card_completed
from studymate.theme import is_dark_theme
from studymate.ui.animated import AnimatedButton
from studymate.ui.icon_helper import IconHelper
from studymate.ui.study_tab import FollowUpThinkingPanel, PromptTextEdit, SessionCardEntry, StudyTab
from studymate.workers.mcq_worker import MCQBulkWorker, MCQWorker, build_mcq_payload, cached_mcq_payload, save_mcq_payload


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


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
        self._shadow_animations: list[QPropertyAnimation] = []
        super().__init__(datastore, ollama, icons, preflight)

    def _build_study_view(self) -> QWidget:
        container = QWidget()
        root = QHBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        left_surface = self._surface()
        dark = is_dark_theme()
        choice_bg = "rgba(26, 35, 46, 0.98)" if dark else "rgba(255, 255, 255, 0.98)"
        choice_border = "rgba(122, 142, 164, 0.34)" if dark else "rgba(166, 182, 198, 0.58)"
        choice_text = "#e7edf4" if dark else "#3d4f5f"
        selected_border = "#79b7ff" if dark else "#9aa6b2"
        skeleton = (
            "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #263443, stop:0.5 #344253, stop:1 #263443)"
            if dark
            else "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #e8ecf1, stop:0.5 #f5f7fa, stop:1 #e8ecf1)"
        )
        skeleton_border = "rgba(122, 142, 164, 0.34)" if dark else "#dfe6ee"
        left_surface.setStyleSheet(
            f"""
            QLabel#MCQCardTitle {{
                font-family: "Nunito Sans", "Segoe UI Variable Text", "Segoe UI", sans-serif;
                font-size: 15px;
                font-weight: 800;
                color: {"#33465a" if dark else "#46596d"};
            }}
            QLabel#MCQQuestionLead {{
                font-family: "Nunito Sans", "Segoe UI Variable Text", "Segoe UI", sans-serif;
                font-size: 24px;
                font-weight: 700;
                color: {"#c6d1dc" if dark else "#4f6478"};
                line-height: 1.35;
            }}
            QPushButton#MCQChoiceButton {{
                background-color: {choice_bg};
                border: 1px solid {choice_border};
                border-radius: 8px;
                padding: 18px;
                color: {choice_text};
                font-size: 16px;
                font-weight: 500;
                text-align: left;
            }}
            QPushButton#MCQChoiceButton:hover {{
                background-color: {choice_bg};
                border-color: {choice_border};
            }}
            QPushButton#MCQChoiceButton[result="correct"] {{
                background-color: #d9f4df;
                border-color: #58b66f;
                color: #123d20;
            }}
            QPushButton#MCQChoiceButton[result="correct-red"] {{
                background-color: #ffe1e1;
                border-color: #d95c5c;
                color: #6c1818;
            }}
            QPushButton#MCQChoiceButton[result="selected"] {{
                background-color: {choice_bg};
                border-color: {selected_border};
            }}
            QWidget#MCQChoiceHost {{
                background: transparent;
            }}
            QPushButton#MCQChoiceButton[result="skeleton"] {{
                background-color: {skeleton};
                border-color: {skeleton_border};
                color: transparent;
            }}
            QPushButton#MCQChoiceButton[result="skeleton"]:hover {{
                background-color: {skeleton};
                border-color: {skeleton_border};
            }}
            """
        )
        left_layout = QVBoxLayout(left_surface)
        left_layout.setContentsMargins(18, 18, 18, 18)
        left_layout.setSpacing(12)

        actions = QHBoxLayout()
        self.start_btn = AnimatedButton("Start")
        self.start_btn.setProperty("skipClickSfx", True)
        self.start_btn.clicked.connect(self._handle_study_primary_action)
        self.refresh_study_btn = AnimatedButton("Refresh")
        self.refresh_study_btn.clicked.connect(lambda: self.reload_cards(force=True))
        actions.addStretch(1)
        actions.addWidget(self.start_btn)
        actions.addWidget(self.refresh_study_btn)
        left_layout.addLayout(actions)

        self.session_title = QLabel("Pick a card to start")
        self.session_title.setObjectName("MCQCardTitle")
        self.session_meta = QLabel("")
        self.session_meta.setObjectName("SmallMeta")
        self.session_question = QLabel("Use the Cards subtab or press Start for the current section.")
        self.session_question.setObjectName("MCQQuestionLead")
        self.session_question.setWordWrap(True)
        self.session_question.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.session_question.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.session_question.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.question_shell = QWidget()
        self.question_shell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        question_layout = QVBoxLayout(self.question_shell)
        question_layout.setContentsMargins(40, 0, 40, 0)
        question_layout.setSpacing(0)
        question_layout.addStretch(1)
        question_layout.addWidget(self.session_question)
        question_layout.addStretch(1)
        self.question_shell.setMinimumHeight(210)

        self.choice_host = QWidget()
        self.choice_host.setObjectName("MCQChoiceHost")
        self.choice_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.choice_grid = QGridLayout(self.choice_host)
        self.choice_grid.setContentsMargins(16, 16, 16, 16)
        self.choice_grid.setHorizontalSpacing(18)
        self.choice_grid.setVerticalSpacing(18)
        self.choice_buttons: list[AnimatedButton] = []
        self._choice_shadows: list[QGraphicsDropShadowEffect] = []
        for index in range(4):
            button = AnimatedButton("")
            button.setObjectName("MCQChoiceButton")
            button.setMinimumHeight(96)
            button.setProperty("result", "")
            button.setProperty("disablePressMotion", False)
            button.set_motion_scale_range(0.015)
            button.set_motion_hover_grow(0, 0)
            button.set_motion_lift(0.0)
            button.set_motion_press_scale(0.04)

            shadow = QGraphicsDropShadowEffect(button)
            shadow.setBlurRadius(0)
            shadow.setXOffset(0)
            shadow.setYOffset(0)
            shadow.setColor(QColor(0, 0, 0, 0))
            button.setGraphicsEffect(shadow)
            self._choice_shadows.append(shadow)

            button.installEventFilter(self)
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
        left_layout.addWidget(self.question_shell, 1)
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
        self._init_followup_feedback_browser(self.grade_feedback)
        self.followup_thinking_panel = FollowUpThinkingPanel()
        self.followup_response_host = QWidget()
        self.followup_response_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.followup_response_host.setAutoFillBackground(False)
        self.followup_response_host.setStyleSheet("background: transparent; border: none;")
        self.followup_response_stack = QStackedLayout(self.followup_response_host)
        self.followup_response_stack.setContentsMargins(0, 0, 0, 0)
        self.followup_response_stack.setStackingMode(QStackedLayout.StackOne)
        self.followup_response_stack.addWidget(self.grade_feedback)
        self.followup_response_stack.addWidget(self.followup_thinking_panel)
        self.followup_response_stack.setCurrentWidget(self.grade_feedback)
        right_layout.addWidget(self.grade_summary)
        right_layout.addWidget(self.followup_response_host, 1)
        self._build_followup_controls(right_layout, hidden=False)

        root.addWidget(left_surface, 2)
        root.addWidget(right_surface, 1)
        return container

    def _switch_mode(self, index: int) -> None:
        super()._switch_mode(index)
        if index == 1:
            self._layout_choice_buttons()

    def activate_view(self) -> None:
        super().activate_view()

    def _run_post_reload_tasks(self, generation: int) -> None:
        super()._run_post_reload_tasks(generation)

    def _fill_missing_mcqs_in_background(self) -> None:
        if self.mcq_background_worker is not None and self.mcq_background_worker.isRunning():
            return
        model_spec = self._feature_text_llm_spec("mcq_context_length")
        if not self.preflight.has_model(model_spec.key):
            return
        model_tag = self._feature_text_model_tag("mcq_context_length")
        missing: list[dict] = []
        for card in self._filtered_cards():
            if not str(card.get("question", "")).strip():
                continue
            if cached_mcq_payload(self.datastore, card, model_tag) is None:
                missing.append(card)
        if not missing:
            return
        mcq_difficulty = self._mcq_difficulty()
        ai_settings = self.datastore.load_ai_settings()
        worker = MCQBulkWorker(
            cards=missing,
            datastore=self.datastore,
            ollama=self.ollama,
            model=model_tag,
            profile_context=self.datastore.load_profile(),
            context_length=int(ai_settings.get("mcq_context_length", 8192) or 8192),
            difficulty=mcq_difficulty,
        )
        self.mcq_background_worker = worker
        worker.finished.connect(lambda *_args, current=worker: self._on_background_mcqs_finished(current))
        worker.failed.connect(lambda _message, current=worker: self._on_background_mcqs_finished(current))
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.start()

    def _mcq_difficulty(self) -> str:
        setup = self.datastore.load_setup()
        mcq_setup = dict(setup.get("mcq", {}))
        return str(mcq_setup.get("difficulty", "slightly_harder")).strip() or "slightly_harder"

    def _on_background_mcqs_finished(self, worker: MCQBulkWorker) -> None:
        if self.mcq_background_worker is worker:
            self.mcq_background_worker = None

    def eventFilter(self, obj, event) -> bool:
        if hasattr(self, "choice_buttons") and obj in self.choice_buttons:
            if event.type() == QEvent.Type.Enter:
                self._animate_choice_shadow(obj, True)
            elif event.type() == QEvent.Type.Leave:
                self._animate_choice_shadow(obj, False)
        return super().eventFilter(obj, event)

    def _animate_choice_shadow(self, button, hovered: bool) -> None:
        if not button or not button.graphicsEffect():
            return
        shadow = button.graphicsEffect()
        if not isinstance(shadow, QGraphicsDropShadowEffect):
            return
        
        target_blur = 28 if hovered else 0
        target_opacity = 0.35 if hovered else 0.0
        target_x = 0
        target_y = 8 if hovered else 0
        
        blur_animation = QPropertyAnimation(shadow, b"blurRadius")
        blur_animation.setDuration(220)
        blur_animation.setStartValue(shadow.blurRadius())
        blur_animation.setEndValue(target_blur)
        blur_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        blur_animation.start()
        self._shadow_animations = getattr(self, '_shadow_animations', [])
        self._shadow_animations.append(blur_animation)
        blur_animation.finished.connect(lambda: self._cleanup_shadow_animation(blur_animation))
        
        opacity_animation = QPropertyAnimation(shadow, b"color")
        opacity_animation.setDuration(220)
        start_color = shadow.color()
        end_color = QColor(0, 0, 0, int(255 * target_opacity))
        opacity_animation.setStartValue(start_color)
        opacity_animation.setEndValue(end_color)
        opacity_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        opacity_animation.start()
        self._shadow_animations.append(opacity_animation)
        opacity_animation.finished.connect(lambda: self._cleanup_shadow_animation(opacity_animation))
        
        x_animation = QPropertyAnimation(shadow, b"xOffset")
        x_animation.setDuration(220)
        x_animation.setStartValue(shadow.xOffset())
        x_animation.setEndValue(target_x)
        x_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        x_animation.start()
        self._shadow_animations.append(x_animation)
        x_animation.finished.connect(lambda: self._cleanup_shadow_animation(x_animation))
        
        y_animation = QPropertyAnimation(shadow, b"yOffset")
        y_animation.setDuration(220)
        y_animation.setStartValue(shadow.yOffset())
        y_animation.setEndValue(target_y)
        y_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        y_animation.start()
        self._shadow_animations.append(y_animation)
        y_animation.finished.connect(lambda: self._cleanup_shadow_animation(y_animation))

    def _cleanup_shadow_animation(self, animation):
        if hasattr(self, '_shadow_animations') and animation in self._shadow_animations:
            self._shadow_animations.remove(animation)

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
            "mcq_started_monotonic": None,
            "mcq_presented_at": "",
            "mcq_response_seconds": None,
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
        model_tag = self._feature_text_model_tag("mcq_context_length")
        cached = cached_mcq_payload(self.datastore, card, model_tag)
        if cached is None and card.get("mcq_answers"):
            try:
                cached = build_mcq_payload(card, list(card.get("mcq_answers", [])), model_tag)
                save_mcq_payload(self.datastore, card, cached)
            except Exception:
                cached = None
        if cached is not None:
            entry["mcq_payload"] = cached
            self._apply_mcq_payload_to_card_answer(entry, cached)
            self._render_mcq_entry(entry)
            return
        model_spec = self._feature_text_llm_spec("mcq_context_length")
        if not self.preflight.require_model(model_spec.key, parent=self, feature_name="MCQ generation"):
            self.mcq_result.setText("MCQ choices could not be generated until the model is ready.")
            return
        ai_settings = self.datastore.load_ai_settings()
        worker = MCQWorker(
            card=card,
            ollama=self.ollama,
            model=model_tag,
            profile_context=self.datastore.load_profile(),
            context_length=int(ai_settings.get("mcq_context_length", 8192) or 8192),
            difficulty=self._mcq_difficulty(),
        )
        self.mcq_worker = worker
        worker.status.connect(self.mcq_result.setText)
        worker.finished.connect(lambda payload, idx=self.current_history_index: self._on_mcq_ready(idx, payload))
        worker.failed.connect(self._on_mcq_failed)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.start()

    def _on_mcq_ready(self, entry_index: int, payload: dict) -> None:
        self._stop_skeleton_animation()
        self.mcq_worker = None
        entry = self._history_entry(entry_index)
        if entry is None:
            return
        entry["mcq_payload"] = payload
        save_mcq_payload(self.datastore, entry["card"], payload)
        self._apply_mcq_payload_to_card_answer(entry, payload)
        if entry_index == self.current_history_index:
            self._render_mcq_entry(entry)

    def _on_mcq_failed(self, message: str) -> None:
        self._stop_skeleton_animation()
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
        self._start_skeleton_animation()

    def _start_skeleton_animation(self) -> None:
        self._stop_skeleton_animation()
        from PySide6.QtCore import QTimer
        self._skeleton_timer = QTimer(self)
        self._skeleton_timer.setInterval(600)
        self._skeleton_timer.timeout.connect(self._on_skeleton_timer_tick)
        self._skeleton_timer.start()

    def _stop_skeleton_animation(self) -> None:
        if hasattr(self, '_skeleton_timer') and self._skeleton_timer is not None:
            self._skeleton_timer.stop()
            self._skeleton_timer = None

    def _on_skeleton_timer_tick(self) -> None:
        for button in self.choice_buttons:
            if button.property("result") == "skeleton":
                button.style().unpolish(button)
                button.style().polish(button)
                button.update()

    def _render_mcq_entry(self, entry: dict) -> None:
        payload = entry.get("mcq_payload") or {}
        choices = payload.get("choices", [])
        selected_index = int(entry.get("selected_index", -1))
        self.mcq_result.setText("")
        self._apply_choice_heights(list(choices))
        can_answer = not entry.get("attempt_logged") and self.mcq_worker is None
        if can_answer and selected_index < 0 and choices:
            self._ensure_mcq_timer_started(entry)
        for index, button in enumerate(self.choice_buttons):
            button.setText(self._wrapped_choice_text(str(choices[index])) if index < len(choices) else "")
            button.setEnabled(can_answer and index < len(choices))
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

    def _ensure_mcq_timer_started(self, entry: dict) -> None:
        if entry.get("mcq_started_monotonic") is not None:
            return
        entry["mcq_started_monotonic"] = time.monotonic()
        entry["mcq_presented_at"] = datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _mcq_target_seconds(card: dict, hints_used: int) -> float:
        question_words = len(str(card.get("question", "")).split())
        difficulty = _clamp(float(card.get("natural_difficulty", 5) or 5), 1.0, 10.0)
        base_seconds = 6.0 + (difficulty * 1.55) + min(question_words, 28) * 0.33
        hint_adjustment = min(max(hints_used, 0), 3) * 2.2
        return _clamp(base_seconds + hint_adjustment, 7.5, 36.0)

    @staticmethod
    def _mcq_speed_factor(response_seconds: float, target_seconds: float) -> float:
        if target_seconds <= 0:
            return 0.5
        ratio = response_seconds / target_seconds
        if ratio <= 0.55:
            return 1.0
        if ratio <= 1.0:
            return _clamp(1.0 - ((ratio - 0.55) / 0.45) * 0.18, 0.82, 1.0)
        if ratio <= 1.6:
            return _clamp(0.82 - ((ratio - 1.0) / 0.6) * 0.27, 0.55, 0.82)
        if ratio <= 2.4:
            return _clamp(0.55 - ((ratio - 1.6) / 0.8) * 0.35, 0.20, 0.55)
        return max(0.0, 0.20 - min(0.20, (ratio - 2.4) * 0.08))

    def _build_mcq_grade_report(self, entry: dict, payload: dict, selected_answer: str, correct: bool) -> dict:
        card = entry.get("card") or {}
        started_monotonic = entry.get("mcq_started_monotonic")
        response_seconds = 0.0
        if isinstance(started_monotonic, (int, float)):
            response_seconds = max(0.2, time.monotonic() - float(started_monotonic))
        hints_used = int(entry.get("hints_used", 0) or 0)
        target_seconds = self._mcq_target_seconds(card, hints_used)
        speed_factor = self._mcq_speed_factor(response_seconds, target_seconds)
        hint_multiplier = max(0.55, 1.0 - (min(hints_used, 4) * 0.12))
        difficulty = _clamp(float(card.get("natural_difficulty", 5) or 5), 1.0, 10.0)
        difficulty_bonus = ((difficulty - 5.0) / 5.0) * 0.4

        if correct:
            marks = (5.6 + (4.1 * speed_factor) + difficulty_bonus) * hint_multiplier
            how_good = _clamp((89.0 + (11.0 * speed_factor) + (difficulty_bonus * 4.0)) - (hints_used * 2.5), 0.0, 100.0)
        else:
            marks = max(0.0, (0.4 + (3.0 * speed_factor) + max(0.0, difficulty_bonus * 0.5)) * (hint_multiplier - 0.08))
            how_good = _clamp((10.0 + (34.0 * speed_factor) + (difficulty_bonus * 3.0)) - (hints_used * 3.5), 0.0, 55.0)

        marks = round(_clamp(marks, 0.0, 10.0), 1)
        response_seconds = round(response_seconds, 2)
        entry["mcq_response_seconds"] = response_seconds

        return {
            "marks_out_of_10": marks,
            "how_good": round(how_good, 4),
            "state": "correct" if correct else "wrong",
            "what_went_good": "Correct MCQ choice." if correct else "",
            "what_went_bad": "" if correct else "Selected the wrong MCQ choice.",
            "what_to_improve": "" if correct else f"Review the correct answer: {payload.get('correct_answer', '')}",
            "mcq": True,
            "hide_score": True,
            "selected_answer": selected_answer,
            "correct_answer": payload.get("correct_answer", ""),
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

    def _select_choice(self, index: int) -> None:
        entry = self._current_history_entry()
        if entry is None or entry.get("attempt_logged") or not entry.get("mcq_payload"):
            return
        is_latest = self.current_history_index == len(self.session_history) - 1
        if not is_latest:
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
        report = self._build_mcq_grade_report(entry, payload, selected_answer, correct)
        self._apply_grade_result(entry, report)
        self._show_history_entry(self.current_history_index)

    def _update_study_controls(self) -> None:
        entry = self._current_history_entry()
        is_latest = self.current_history_index == len(self.session_history) - 1
        pending_current = entry is not None and entry.get("status") in {"queued", "grading"}
        can_choose = bool(entry) and not pending_current and not entry.get("attempt_logged") and self.mcq_worker is None
        self._update_study_primary_action()
        self.prev_card_btn.setEnabled(self.current_history_index > 0)
        self.next_btn.setEnabled(bool(entry and entry.get("attempt_logged")) and self.mcq_worker is None)
        self.skip_btn.setEnabled(can_choose and is_latest)
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
        avg_difficulty = (
            sum(int(card.get("natural_difficulty", 5)) for card in self.session_cards) / len(self.session_cards)
            if self.session_cards
            else 0.0
        )
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.information(
            self,
            "MCQ session complete",
            f"Cards completed: {len(self.session_scores)}\nAverage difficulty: {avg_difficulty:.1f}/10",
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
        self._update_study_primary_action()
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
