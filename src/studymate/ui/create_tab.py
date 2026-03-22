from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from studymate.services.data_store import DataStore
from studymate.services.ollama_service import OllamaService
from studymate.ui.icon_helper import IconHelper
from studymate.workers.autofill_worker import AutofillWorker


class QuestionInputEdit(QTextEdit):
    submitted = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
            event.accept()
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class CreateTab(QWidget):
    card_saved = Signal()

    def __init__(self, datastore: DataStore, ollama: OllamaService, icons: IconHelper) -> None:
        super().__init__()
        self.datastore = datastore
        self.ollama = ollama
        self.icons = icons
        self.autofill_worker: AutofillWorker | None = None
        self.pending_jobs: list[dict] = []
        self.active_job: dict | None = None

        self._build_ui()

    def _surface(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Surface")
        return frame

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(20)

        editor_surface = self._surface()
        editor_layout = QVBoxLayout(editor_surface)
        editor_layout.setContentsMargins(24, 24, 24, 24)
        editor_layout.setSpacing(18)

        header = QLabel("Create card")
        header.setObjectName("PageTitle")
        intro = QLabel("Write a question and press Enter or Add question. ONCards will save them one by one.")
        intro.setObjectName("SectionText")
        intro.setWordWrap(True)
        editor_layout.addWidget(header)
        editor_layout.addWidget(intro)

        self.question_input = QuestionInputEdit()
        self.question_input.setPlaceholderText("Write your question here. Press Enter to queue it, or Shift+Enter for a new line.")
        self.question_input.setMinimumHeight(360)
        self.question_input.submitted.connect(self._enqueue_question)
        editor_layout.addWidget(self.question_input)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        self.add_btn = QPushButton("Add question")
        self.add_btn.clicked.connect(self._enqueue_question)
        action_row.addWidget(self.add_btn)
        editor_layout.addLayout(action_row)
        editor_layout.addStretch(1)

        queue_surface = self._surface()
        queue_layout = QVBoxLayout(queue_surface)
        queue_layout.setContentsMargins(24, 24, 24, 24)
        queue_layout.setSpacing(16)

        queue_title = QLabel("Save queue")
        queue_title.setObjectName("PageTitle")
        queue_sub = QLabel("Queued questions are processed in order. You can keep adding more while ONCards works.")
        queue_sub.setObjectName("SectionText")
        queue_sub.setWordWrap(True)
        queue_layout.addWidget(queue_title)
        queue_layout.addWidget(queue_sub)

        self.queue_list = QListWidget()
        queue_layout.addWidget(self.queue_list, 1)

        self.queue_message = QTextEdit()
        self.queue_message.setReadOnly(True)
        self.queue_message.setMinimumHeight(180)
        self.queue_message.setPlaceholderText("Autofill progress appears here.")
        queue_layout.addWidget(self.queue_message)

        root.addWidget(editor_surface, 2)
        root.addWidget(queue_surface, 1)

    def has_pending_work(self) -> bool:
        return bool(self.pending_jobs) or bool(self.active_job) or bool(self.autofill_worker and self.autofill_worker.isRunning())

    def _enqueue_question(self) -> None:
        question = self.question_input.toPlainText().strip()
        if not question:
            return
        item = QListWidgetItem(f"Queued  |  {self._short_label(question)}")
        self.queue_list.addItem(item)
        self.pending_jobs.append({"question": question, "item": item})
        self.queue_message.append("Queued a new question.")
        self.question_input.clear()
        self._process_next_question()

    def _process_next_question(self) -> None:
        if self.active_job is not None:
            return
        if not self.pending_jobs:
            return

        self.active_job = self.pending_jobs.pop(0)
        question = self.active_job["question"]
        item = self.active_job["item"]
        item.setText(f"Saving  |  {self._short_label(question)}")
        self.queue_message.append(f"Saving question: {self._short_label(question)}")

        self.autofill_worker = AutofillWorker(
            question,
            self.ollama,
            profile_context=self.datastore.load_profile(),
        )
        self.autofill_worker.progress.connect(self.queue_message.append)
        self.autofill_worker.field.connect(self._on_field_ready)
        self.autofill_worker.done.connect(self._on_autofill_done)
        self.autofill_worker.failed.connect(self._on_autofill_failed)
        self.autofill_worker.start()

    def _on_field_ready(self, name: str, value) -> None:
        if name == "response_to_user":
            self.queue_message.append(str(value))

    def _on_autofill_done(self, payload: dict) -> None:
        if self.active_job is None:
            return
        payload = dict(payload)
        payload["question"] = self.active_job["question"]
        saved = self.datastore.save_card(payload)
        self.active_job["item"].setText(f"Saved  |  {self._short_label(saved.get('question', ''))}")
        self.queue_message.append("Question saved.")
        self.card_saved.emit()
        self.active_job = None
        self._process_next_question()

    def _on_autofill_failed(self, message: str) -> None:
        if self.active_job is not None:
            self.active_job["item"].setText(f"Failed  |  {self._short_label(self.active_job['question'])}")
        self.queue_message.append(message)
        self.active_job = None
        self._process_next_question()

    @staticmethod
    def _short_label(text: str, limit: int = 56) -> str:
        compact = " ".join(text.split())
        return compact if len(compact) <= limit else f"{compact[:limit - 1]}..."
