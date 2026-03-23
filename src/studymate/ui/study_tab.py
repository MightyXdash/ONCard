from __future__ import annotations

from datetime import datetime, timezone
import random

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from studymate.constants import SUBJECT_TAXONOMY
from studymate.services.data_store import DataStore
from studymate.services.ollama_service import OllamaService
from studymate.ui.icon_helper import IconHelper
from studymate.ui.widgets.card_tile import CardTile
from studymate.workers.followup_worker import FollowUpWorker
from studymate.workers.grade_worker import GradeWorker


class PromptTextEdit(QTextEdit):
    submitted = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
            event.accept()
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class StartStudyDialog(QDialog):
    def __init__(self, path_label: str, count: int) -> None:
        super().__init__()
        self.setWindowTitle("Start study")
        self.setFixedSize(420, 220)

        layout = QVBoxLayout(self)
        title = QLabel("Start studying from this section?")
        title.setObjectName("SectionTitle")
        text = QLabel(f"Path: {path_label}\nCards available: {count}")
        text.setObjectName("SectionText")
        text.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(text, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancel")
        start = QPushButton("Start")
        start.setObjectName("PrimaryButton")
        cancel.clicked.connect(self.reject)
        start.clicked.connect(self.accept)
        actions.addWidget(cancel)
        actions.addWidget(start)
        layout.addLayout(actions)


class MoveCardDialog(QDialog):
    def __init__(self, card: dict, datastore: DataStore) -> None:
        super().__init__()
        self.card = card
        self.datastore = datastore
        self.selected_path = {
            "subject": card.get("subject", "Mathematics"),
            "category": card.get("category", "All"),
            "subtopic": card.get("subtopic", "All"),
        }

        self.setWindowTitle("Move card")
        self.setFixedSize(520, 620)

        layout = QVBoxLayout(self)
        title = QLabel("Choose the new subject path for this card.")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Subject path"])
        self.tree.itemClicked.connect(self._select_path)
        layout.addWidget(self.tree, 1)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        cancel = QPushButton("Cancel")
        move = QPushButton("Move")
        move.setObjectName("PrimaryButton")
        cancel.clicked.connect(self.reject)
        move.clicked.connect(self._move)
        action_row.addWidget(cancel)
        action_row.addWidget(move)
        layout.addLayout(action_row)

        self._build_tree()

    def _build_tree(self) -> None:
        for subject, details in SUBJECT_TAXONOMY.items():
            subject_item = QTreeWidgetItem([subject])
            subject_item.setData(0, Qt.UserRole, {"subject": subject, "category": "All", "subtopic": "All"})
            self.tree.addTopLevelItem(subject_item)

            all_item = QTreeWidgetItem([f"{subject} / All"])
            all_item.setData(0, Qt.UserRole, {"subject": subject, "category": "All", "subtopic": "All"})
            subject_item.addChild(all_item)

            for category in details.get("core", []):
                category_item = QTreeWidgetItem([f"{subject} / {category}"])
                category_item.setData(0, Qt.UserRole, {"subject": subject, "category": category, "subtopic": "All"})
                subject_item.addChild(category_item)
                for subtopic in details.get("subtopics", []):
                    sub_item = QTreeWidgetItem([f"{subject} / {category} / {subtopic}"])
                    sub_item.setData(
                        0,
                        Qt.UserRole,
                        {"subject": subject, "category": category, "subtopic": subtopic},
                    )
                    category_item.addChild(sub_item)
        self.tree.collapseAll()

    def _select_path(self, item: QTreeWidgetItem) -> None:
        self.selected_path = item.data(0, Qt.UserRole)

    def _move(self) -> None:
        result = self.datastore.move_card(
            self.card["id"],
            self.card.get("subject", "Mathematics"),
            self.selected_path["subject"],
            self.selected_path,
        )
        if result is None:
            QMessageBox.warning(self, "Move failed", "Could not move that card.")
            return
        self.accept()


class StudyTab(QWidget):
    def __init__(self, datastore: DataStore, ollama: OllamaService, icons: IconHelper) -> None:
        super().__init__()
        self.datastore = datastore
        self.ollama = ollama
        self.icons = icons
        self.current_subject = "All Subjects"
        self.current_category = "All"
        self.current_subtopic = "All"
        self.cards: list[dict] = []
        self.current_card: dict | None = None
        self.session_queue: list[dict] = []
        self.session_cards: list[dict] = []
        self.session_scores: list[float] = []
        self.current_attempt_logged = False
        self.revealed_hints = 0
        self.hint_cooldown = 0
        self.sidebar_expanded = True
        self.grade_worker: GradeWorker | None = None
        self.followup_worker: FollowUpWorker | None = None
        self.last_grade_report: dict | None = None

        self.cooldown_timer = QTimer(self)
        self.cooldown_timer.timeout.connect(self._tick_hint_cooldown)

        self._build_ui()
        self.reload_cards()

    def _surface(self, sidebar: bool = False) -> QFrame:
        frame = QFrame()
        frame.setObjectName("SidebarSurface" if sidebar else "Surface")
        return frame

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)

        self.sidebar = self._surface(sidebar=True)
        self.sidebar.setMinimumWidth(280)
        self.sidebar.setMaximumWidth(280)
        side_layout = QVBoxLayout(self.sidebar)
        side_layout.setContentsMargins(16, 18, 16, 18)
        side_layout.setSpacing(12)

        side_head = QHBoxLayout()
        title = QLabel("Subjects")
        title.setObjectName("SectionTitle")
        self.collapse_btn = QToolButton()
        self.collapse_btn.setObjectName("CollapseButton")
        self.collapse_btn.setText("<")
        self.collapse_btn.clicked.connect(self._toggle_sidebar)
        side_head.addWidget(title)
        side_head.addStretch(1)
        side_head.addWidget(self.collapse_btn)
        side_layout.addLayout(side_head)

        self.subject_tree = QTreeWidget()
        self.subject_tree.setHeaderHidden(True)
        self.subject_tree.itemClicked.connect(self._subject_clicked)
        side_layout.addWidget(self.subject_tree, 1)
        root.addWidget(self.sidebar)

        content = QVBoxLayout()
        content.setSpacing(14)

        subnav = QHBoxLayout()
        self.cards_sub_btn = QPushButton("Cards")
        self.cards_sub_btn.setObjectName("TopNavButton")
        self.cards_sub_btn.setCheckable(True)
        self.cards_sub_btn.setChecked(True)
        self.study_sub_btn = QPushButton("Study")
        self.study_sub_btn.setObjectName("TopNavButton")
        self.study_sub_btn.setCheckable(True)
        self.cards_sub_btn.clicked.connect(lambda: self._switch_mode(0))
        self.study_sub_btn.clicked.connect(lambda: self._switch_mode(1))
        subnav.addWidget(self.cards_sub_btn)
        subnav.addWidget(self.study_sub_btn)
        subnav.addStretch(1)
        content.addLayout(subnav)

        self.mode_stack = QStackedWidget()
        self.cards_view = self._build_cards_view()
        self.study_view = self._build_study_view()
        self.mode_stack.addWidget(self.cards_view)
        self.mode_stack.addWidget(self.study_view)
        content.addWidget(self.mode_stack, 1)

        root.addLayout(content, 1)

    def _build_cards_view(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        header = self._surface()
        head_layout = QHBoxLayout(header)
        head_layout.setContentsMargins(18, 18, 18, 18)
        title = QLabel("Cards")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Browse, move, and choose where to begin.")
        subtitle.setObjectName("SectionText")
        subtitle.setWordWrap(True)
        left = QVBoxLayout()
        left.addWidget(title)
        left.addWidget(subtitle)
        head_layout.addLayout(left)
        head_layout.addStretch(1)
        self.start_cards_btn = QPushButton("Start")
        self.start_cards_btn.clicked.connect(self._open_start_dialog)
        head_layout.addWidget(self.start_cards_btn)
        self.refresh_cards_btn = QPushButton("Refresh")
        self.refresh_cards_btn.clicked.connect(self.reload_cards)
        head_layout.addWidget(self.refresh_cards_btn)
        layout.addWidget(header)

        self.cards_surface = self._surface()
        cards_layout = QVBoxLayout(self.cards_surface)
        cards_layout.setContentsMargins(18, 18, 18, 18)
        self.card_scroll = QScrollArea()
        self.card_scroll.setWidgetResizable(True)
        self.card_host = QWidget()
        self.card_grid = QGridLayout(self.card_host)
        self.card_grid.setContentsMargins(0, 0, 0, 0)
        self.card_grid.setSpacing(14)
        self.card_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.card_scroll.setWidget(self.card_host)
        cards_layout.addWidget(self.card_scroll)
        layout.addWidget(self.cards_surface, 1)
        return container

    def _build_study_view(self) -> QWidget:
        container = QWidget()
        root = QHBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        left_surface = self._surface()
        left_layout = QVBoxLayout(left_surface)
        left_layout.setContentsMargins(18, 18, 18, 18)
        left_layout.setSpacing(12)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self._open_start_dialog)
        self.refresh_study_btn = QPushButton("Refresh")
        self.refresh_study_btn.clicked.connect(self.reload_cards)
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

        self.answer_input = QTextEdit()
        self.answer_input.setPlaceholderText("Write your answer here...")
        self.answer_input.setMinimumHeight(180)

        hint_row = QHBoxLayout()
        self.hint_btn = QPushButton("Show hint")
        self.hint_btn.clicked.connect(self._show_hint)
        self.hint_status = QLabel("Hints stay hidden until you press Show hint.")
        self.hint_status.setObjectName("SmallMeta")
        hint_row.addWidget(self.hint_btn)
        hint_row.addWidget(self.hint_status, 1)

        self.hints_text = QTextEdit()
        self.hints_text.setReadOnly(True)
        self.hints_text.setFixedHeight(96)
        self.hints_text.setPlaceholderText("Hints will appear one by one.")

        button_row = QHBoxLayout()
        self.idk_btn = QPushButton("I don't know")
        self.idk_btn.clicked.connect(self._ask_i_dont_know)
        self.grade_btn = QPushButton("Grade")
        self.grade_btn.clicked.connect(self._grade)
        self.next_btn = QPushButton("Next")
        self.next_btn.clicked.connect(self._next_card)
        button_row.addWidget(self.idk_btn)
        button_row.addWidget(self.grade_btn)
        button_row.addWidget(self.next_btn)

        left_layout.addWidget(self.session_title)
        left_layout.addWidget(self.session_meta)
        left_layout.addWidget(self.session_question)
        left_layout.addWidget(self.answer_input, 1)
        left_layout.addLayout(hint_row)
        left_layout.addWidget(self.hints_text)
        left_layout.addLayout(button_row)

        right_surface = self._surface()
        right_surface.setMinimumWidth(360)
        right_surface.setMaximumWidth(420)
        right_layout = QVBoxLayout(right_surface)
        right_layout.setContentsMargins(18, 18, 18, 18)
        right_layout.setSpacing(12)

        self.grade_summary = QLabel("AI grader")
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
        self.followup_input.hide()
        self.followup_btn = QPushButton("Ask follow up")
        self.followup_btn.clicked.connect(self._run_followup)
        self.followup_btn.hide()

        right_layout.addWidget(self.grade_summary)
        right_layout.addWidget(self.grade_feedback, 1)
        right_layout.addWidget(self.followup_title)
        right_layout.addWidget(self.followup_input)
        right_layout.addWidget(self.followup_btn)

        root.addWidget(left_surface, 2)
        root.addWidget(right_surface, 1)
        return container

    def _switch_mode(self, index: int) -> None:
        self.mode_stack.setCurrentIndex(index)
        self.cards_sub_btn.setChecked(index == 0)
        self.study_sub_btn.setChecked(index == 1)

    def _toggle_sidebar(self) -> None:
        self.sidebar_expanded = not self.sidebar_expanded
        width = 280 if self.sidebar_expanded else 88
        self.sidebar.setMinimumWidth(width)
        self.sidebar.setMaximumWidth(width)
        self.subject_tree.setVisible(self.sidebar_expanded)
        self.collapse_btn.setText("<" if self.sidebar_expanded else ">")

    def reload_cards(self) -> None:
        self.cards = self.datastore.list_all_cards()
        self._refresh_subjects()
        self._render_cards()

    def _refresh_subjects(self) -> None:
        counts = self.datastore.card_counts_by_subject()
        self.subject_tree.clear()

        all_item = QTreeWidgetItem(["All Subjects"])
        all_item.setData(0, Qt.UserRole, {"subject": "All Subjects", "category": "All", "subtopic": "All"})
        self.subject_tree.addTopLevelItem(all_item)

        for subject, details in SUBJECT_TAXONOMY.items():
            subject_item = QTreeWidgetItem([f"{subject} ({counts.get(subject, 0)})"])
            subject_item.setData(0, Qt.UserRole, {"subject": subject, "category": "All", "subtopic": "All"})
            if counts.get(subject, 0) == 0:
                subject_item.setForeground(0, QColor("#9b9387"))
            self.subject_tree.addTopLevelItem(subject_item)
            for category in details.get("core", []):
                category_item = QTreeWidgetItem([category])
                category_item.setData(
                    0,
                    Qt.UserRole,
                    {"subject": subject, "category": category, "subtopic": "All"},
                )
                subject_item.addChild(category_item)
                for subtopic in details.get("subtopics", []):
                    subtopic_item = QTreeWidgetItem([subtopic])
                    subtopic_item.setData(
                        0,
                        Qt.UserRole,
                        {"subject": subject, "category": category, "subtopic": subtopic},
                    )
                    category_item.addChild(subtopic_item)
        self.subject_tree.collapseAll()
        self.subject_tree.setCurrentItem(all_item)

    def _current_path_label(self) -> str:
        parts = []
        if self.current_subject != "All Subjects":
            parts.append(self.current_subject)
        if self.current_category != "All":
            parts.append(self.current_category)
        if self.current_subtopic != "All":
            parts.append(self.current_subtopic)
        return " / ".join(parts) if parts else "All Subjects"

    def _subject_clicked(self, item: QTreeWidgetItem) -> None:
        payload = item.data(0, Qt.UserRole) or {"subject": "All Subjects", "category": "All", "subtopic": "All"}
        self.current_subject = payload["subject"]
        self.current_category = payload["category"]
        self.current_subtopic = payload.get("subtopic", "All")
        self._render_cards()

    def _clear_grid(self) -> None:
        while self.card_grid.count():
            child = self.card_grid.takeAt(0)
            widget = child.widget()
            if widget:
                widget.deleteLater()

    def _filtered_cards(self) -> list[dict]:
        filtered = list(self.cards)
        if self.current_subject != "All Subjects":
            filtered = [card for card in filtered if card.get("subject") == self.current_subject]
        if self.current_category != "All":
            filtered = [card for card in filtered if card.get("category") == self.current_category]
        if self.current_subtopic != "All":
            filtered = [card for card in filtered if card.get("subtopic") == self.current_subtopic]
        return filtered

    def _render_cards(self) -> None:
        self._clear_grid()
        cards = self._filtered_cards()
        if not cards:
            empty = QLabel("No cards in this section yet.")
            empty.setObjectName("SectionText")
            empty.setAlignment(Qt.AlignCenter)
            self.card_grid.addWidget(empty, 0, 0, 1, 4)
            return

        for idx, card in enumerate(cards):
            tile = CardTile(card)
            tile.selected.connect(self._card_selected)
            tile.move_requested.connect(self._move_card)
            tile.remove_requested.connect(self._remove_card)
            row = idx // 4
            col = idx % 4
            self.card_grid.addWidget(tile, row, col)

    def _move_card(self, card: dict) -> None:
        dialog = MoveCardDialog(card, self.datastore)
        if dialog.exec():
            self.reload_cards()

    def _remove_card(self, card: dict) -> None:
        answer = QMessageBox.question(
            self,
            "Remove card",
            "Remove this card permanently?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        deleted = self.datastore.delete_card(
            str(card.get("id", "")),
            str(card.get("subject", "Mathematics")),
        )
        if not deleted:
            QMessageBox.warning(self, "Remove failed", "Could not remove that card.")
            return
        self._remove_card_from_session(card)
        self.reload_cards()

    def _card_selected(self, card: dict) -> None:
        answer = QMessageBox.question(
            self,
            "Start from here",
            "Do you want to start from here?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._begin_session_pool(self._filtered_cards(), first_card=card)

    def _open_start_dialog(self) -> None:
        pool = self._filtered_cards()
        if not pool:
            return
        dialog = StartStudyDialog(self._current_path_label(), len(pool))
        if dialog.exec():
            self._begin_session_pool(pool)

    def _begin_session_pool(self, pool: list[dict], first_card: dict | None = None) -> None:
        if not pool:
            return
        cards = list(pool)
        random.shuffle(cards)
        if first_card is not None:
            cards = [card for card in cards if card.get("id") != first_card.get("id")]
            cards.insert(0, first_card)
        self.session_queue = cards
        self.session_cards = list(cards)
        self.session_scores = []
        self._switch_mode(1)
        self._advance_session()

    def _advance_session(self) -> None:
        if not self.session_queue:
            self._finish_session()
            return
        self._start_session(self.session_queue.pop(0))

    def _start_session(self, card: dict) -> None:
        self.current_card = card
        self.revealed_hints = 0
        self.hint_cooldown = 0
        self.last_grade_report = None
        self.current_attempt_logged = False
        self.cooldown_timer.stop()
        self.answer_input.clear()
        self.hints_text.clear()
        self.grade_feedback.clear()
        self.grade_summary.setText("AI grader")
        self.session_title.setText(card.get("title", "Untitled"))
        self.session_meta.setText(
            f"{card.get('subject', 'General')}  |  {card.get('category', 'All')}  |  Difficulty {card.get('natural_difficulty', 5)}/10"
        )
        self.session_question.setText(card.get("question", ""))
        self.hint_status.setText("Hints stay hidden until you press Show hint.")
        self.hint_btn.setEnabled(True)
        self._set_followup_visible(False)

    def _set_followup_visible(self, visible: bool) -> None:
        self.followup_title.setVisible(visible)
        self.followup_input.setVisible(visible)
        self.followup_btn.setVisible(visible)

    def _build_followup_context(self) -> str:
        if not self.current_card:
            return ""
        parts = [
            f"Question: {self.current_card.get('question', '')}",
            f"Expected answer: {self.current_card.get('answer', '')}",
            f"Hints: {', '.join(self.current_card.get('hints', []))}",
        ]
        if self.last_grade_report:
            parts.extend(
                [
                    f"Score: {self.last_grade_report.get('marks_out_of_10', '')}",
                    f"Summary: {self.last_grade_report.get('answer_summary', '')}",
                    f"What went good: {self.last_grade_report.get('what_went_good', '')}",
                    f"What went bad: {self.last_grade_report.get('what_went_bad', '')}",
                    f"What to improve: {self.last_grade_report.get('what_to_improve', '')}",
                ]
            )
        return "\n".join(parts) + "\n"

    def _ask_i_dont_know(self) -> None:
        if not self.current_card:
            QMessageBox.information(self, "No card", "Start a card first.")
            return
        self._set_followup_visible(True)
        self.followup_title.setText("Follow up on this card")
        self.followup_input.setPlainText("Thoroughly explain this to me step by step")
        self.grade_summary.setText("Study help")
        self.grade_feedback.setMarkdown("### Study help\nWorking on a step-by-step explanation...")
        self._run_followup(auto_prompt="Thoroughly explain this to me step by step")

    def _show_hint(self) -> None:
        if not self.current_card:
            return
        hints = self.current_card.get("hints", [])
        if self.hint_cooldown > 0:
            return
        if self.revealed_hints >= len(hints):
            self.hint_status.setText("No more hints for this card.")
            self.hint_btn.setEnabled(False)
            return
        self.revealed_hints += 1
        visible = hints[: self.revealed_hints]
        self.hints_text.setPlainText("\n".join(f"{idx + 1}. {hint}" for idx, hint in enumerate(visible)))
        if self.revealed_hints < len(hints):
            self.hint_cooldown = 30
            self.hint_btn.setEnabled(False)
            self.hint_status.setText("Next hint in 30s.")
            self.cooldown_timer.start(1000)
        else:
            self.hint_status.setText("All hints revealed.")
            self.hint_btn.setEnabled(False)

    def _tick_hint_cooldown(self) -> None:
        if self.hint_cooldown <= 0:
            self.cooldown_timer.stop()
            self.hint_btn.setEnabled(True)
            self.hint_status.setText("You can reveal the next hint now.")
            return
        self.hint_cooldown -= 1
        self.hint_status.setText(f"Next hint in {self.hint_cooldown}s.")

    def _save_attempt(self, graded: bool, grade_payload: dict | None = None) -> None:
        if not self.current_card:
            return
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "card_id": self.current_card.get("id"),
            "subject": self.current_card.get("subject"),
            "question": self.current_card.get("question"),
            "answer_text": self.answer_input.toPlainText().strip(),
            "hints_used": self.revealed_hints,
            "graded": graded,
        }
        if grade_payload:
            payload.update(grade_payload)
        self.datastore.save_attempt(payload)

    def _grade(self) -> None:
        if not self.current_card:
            QMessageBox.information(self, "No card", "Start a card first.")
            return
        user_answer = self.answer_input.toPlainText().strip()
        if not user_answer:
            QMessageBox.warning(self, "Missing answer", "Write an answer before grading.")
            return
        if self.grade_worker and self.grade_worker.isRunning():
            return

        self.grade_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        self.grade_summary.setText("Grading...")
        self.grade_feedback.clear()
        self._set_followup_visible(False)

        self.grade_worker = GradeWorker(
            question=self.current_card.get("question", ""),
            expected_answer=self.current_card.get("answer", ""),
            user_answer=user_answer,
            difficulty=int(self.current_card.get("natural_difficulty", 5)),
            ollama=self.ollama,
            profile_context=self.datastore.load_profile(),
        )
        self.grade_worker.stream.connect(self._on_grade_stream)
        self.grade_worker.status.connect(self.grade_summary.setText)
        self.grade_worker.finished.connect(self._on_grade_done)
        self.grade_worker.failed.connect(self._on_grade_failed)
        self.grade_worker.start()

    def _on_grade_stream(self, markdown_text: str) -> None:
        self.grade_feedback.setMarkdown(markdown_text)

    def _on_grade_done(self, report: dict) -> None:
        score = report.get("marks_out_of_10", 0)
        self.last_grade_report = report
        state = str(report.get("state", "wrong")).title()
        self.grade_summary.setText(f"Score: {score}/10  |  {state}")
        self._save_attempt(graded=True, grade_payload=report)
        self.current_attempt_logged = True
        self.session_scores.append(float(score))
        extra = [
            f"Summary: {report.get('answer_summary', '')}",
            f"Good: {report.get('what_went_good', '')}",
            f"Bad: {report.get('what_went_bad', '')}",
        ]
        if report.get("what_to_improve"):
            extra.append(f"Improve: {report.get('what_to_improve')}")
        if float(score) >= 9:
            extra.append("Coach: Great work. You got the core meaning right, and that matters most.")
        elif float(score) <= 5:
            extra.append("Coach: Keep going. Use the follow up feature to ask more questions and work through it step by step.")
        self.grade_feedback.append("<hr>")
        self.grade_feedback.append("<br>".join(extra))
        self._set_followup_visible(True)
        self.grade_btn.setEnabled(True)
        self.next_btn.setEnabled(True)

    def _on_grade_failed(self, message: str) -> None:
        self.grade_summary.setText("Grading failed.")
        self.grade_feedback.setPlainText(message)
        self.grade_btn.setEnabled(True)
        self.next_btn.setEnabled(True)

    def _run_followup(self, auto_prompt: str | None = None) -> None:
        if self.followup_worker and self.followup_worker.isRunning():
            return
        if not self.current_card:
            return
        prompt = (auto_prompt or self.followup_input.toPlainText()).strip()
        if not prompt:
            QMessageBox.information(self, "Follow up", "Write a follow-up prompt first.")
            return
        context = self._build_followup_context()
        self.followup_btn.setEnabled(False)
        if auto_prompt is None:
            self.followup_input.clear()
        self.followup_worker = FollowUpWorker(
            ollama=self.ollama,
            model="gemma3:4b",
            prompt=prompt,
            context=context,
        )
        self.followup_worker.chunk.connect(self.grade_feedback.setMarkdown)
        self.followup_worker.finished.connect(lambda: self.followup_btn.setEnabled(True))
        self.followup_worker.failed.connect(self._on_followup_failed)
        self.followup_worker.start()

    def _on_followup_failed(self, message: str) -> None:
        self.followup_btn.setEnabled(True)
        self.grade_feedback.append("<hr>")
        self.grade_feedback.append(message)

    def _next_card(self) -> None:
        if self.current_card and self.answer_input.toPlainText().strip() and not self.current_attempt_logged:
            self._save_attempt(graded=False, grade_payload={"marks_out_of_10": None})
            self.current_attempt_logged = True
        self._advance_session()

    def _finish_session(self) -> None:
        avg_marks = sum(self.session_scores) / len(self.session_scores) if self.session_scores else 0.0
        avg_difficulty = (
            sum(int(card.get("natural_difficulty", 5)) for card in self.session_cards) / len(self.session_cards)
            if self.session_cards
            else 0.0
        )
        QMessageBox.information(
            self,
            "Session complete",
            f"Average marks: {avg_marks:.1f}/10\nAverage difficulty: {avg_difficulty:.1f}/10",
        )
        self.current_card = None
        self.session_queue = []
        self.session_cards = []
        self.session_scores = []
        self.session_title.setText("Pick a card to start")
        self.session_meta.setText("")
        self.session_question.setText("Use the Cards subtab or press Start for the current section.")
        self.answer_input.clear()
        self.hints_text.clear()
        self.grade_feedback.clear()
        self.grade_summary.setText("AI grader")
        self._set_followup_visible(False)

    def _remove_card_from_session(self, card: dict) -> None:
        card_id = str(card.get("id", ""))
        self.session_queue = [item for item in self.session_queue if str(item.get("id", "")) != card_id]
        self.session_cards = [item for item in self.session_cards if str(item.get("id", "")) != card_id]
        if self.current_card and str(self.current_card.get("id", "")) == card_id:
            if self.session_queue:
                self._start_session(self.session_queue.pop(0))
            else:
                self.current_card = None
                self.session_title.setText("Pick a card to start")
                self.session_meta.setText("")
                self.session_question.setText("Use the Cards subtab or press Start for the current section.")
                self.answer_input.clear()
                self.hints_text.clear()
                self.grade_feedback.clear()
                self.grade_summary.setText("AI grader")
                self._set_followup_visible(False)
