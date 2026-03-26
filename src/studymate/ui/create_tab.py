from __future__ import annotations

from dataclasses import dataclass
import html
from pathlib import Path
import shutil
import uuid

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QMouseEvent, QPixmap, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from studymate.services.data_store import DataStore
from studymate.services.embedding_service import EmbeddingService
from studymate.services.files_to_cards_service import (
    SelectedSourceFile,
    create_source_preview,
    describe_source_file,
    detect_source_family,
    files_to_cards_limit,
    files_to_cards_question_cap,
)
from studymate.services.ollama_service import OllamaService
from studymate.ui.icon_helper import IconHelper
from studymate.workers.autofill_worker import AutofillWorker
from studymate.workers.embedding_worker import EmbeddingWorker
from studymate.workers.files_to_cards_worker import FilesToCardsJob, FilesToCardsWorker


@dataclass
class FilesToCardsRunState:
    run_id: str
    phase: str
    question_entries: list[dict]


class QuestionInputEdit(QTextEdit):
    submitted = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
            event.accept()
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class LimitedTextEdit(QTextEdit):
    limited_text_changed = Signal(str)

    def __init__(self, max_chars: int, parent=None) -> None:
        super().__init__(parent)
        self.max_chars = max_chars
        self.textChanged.connect(self._enforce_limit)

    def _enforce_limit(self) -> None:
        text = self.toPlainText()
        if len(text) > self.max_chars:
            cursor = self.textCursor()
            position = min(cursor.position(), self.max_chars)
            self.blockSignals(True)
            self.setPlainText(text[: self.max_chars])
            cursor = self.textCursor()
            cursor.setPosition(position)
            self.setTextCursor(cursor)
            self.blockSignals(False)
            text = self.toPlainText()
        self.limited_text_changed.emit(text)


class FileDropZone(QFrame):
    files_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self._locked = False
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(6)

        self.title = QLabel("Drop files here")
        self.title.setObjectName("SectionTitle")
        self.subtitle = QLabel("Supports images, PDF, and PPTX.")
        self.subtitle.setObjectName("SmallMeta")
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self.setEnabled(not locked)

    def set_subtitle(self, text: str) -> None:
        self.subtitle.setText(text)

    def dragEnterEvent(self, event) -> None:
        if self._locked:
            event.ignore()
            return
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        if self._locked:
            event.ignore()
            return
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event) -> None:
        if self._locked:
            event.ignore()
            return
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
            return
        event.ignore()


class ElidedLabel(QLabel):
    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self.setMinimumHeight(24)
        self.setToolTip(text)
        self._refresh_text()

    def setText(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        self._refresh_text()

    def text(self) -> str:
        return self._full_text

    def resizeEvent(self, event) -> None:
        self._refresh_text()
        super().resizeEvent(event)

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(0, hint.height())

    def _refresh_text(self) -> None:
        width = max(self.contentsRect().width(), 8)
        elided = self.fontMetrics().elidedText(self._full_text, Qt.TextElideMode.ElideRight, width)
        super().setText(elided)


class PannablePreviewArea(QScrollArea):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._dragging = False
        self._last_pos = QPoint()
        self._content = QLabel()
        self._content.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._content.setObjectName("FTCPreviewDialog")
        self.setWidget(self._content)
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._content.setPixmap(pixmap)
        self._content.resize(pixmap.size())

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._last_pos = event.position().toPoint()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging:
            current = event.position().toPoint()
            delta = current - self._last_pos
            self._last_pos = current
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)


class SelectedFileRow(QWidget):
    remove_requested = Signal(str)
    preview_requested = Signal(str)

    def __init__(self, source: SelectedSourceFile) -> None:
        super().__init__()
        self.setObjectName("FTCFileRow")
        self.setMinimumHeight(86)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.path = str(source.path)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        self.preview_thumb = QLabel()
        self.preview_thumb.setObjectName("FTCPreviewThumb")
        self.preview_thumb.setFixedSize(56, 56)
        self.preview_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        try:
            preview = create_source_preview(source.path, max_width=56, max_height=56)
            pixmap = QPixmap.fromImage(preview)
            self.preview_thumb.setPixmap(pixmap)
        except Exception:
            self.preview_thumb.setText(source.family.upper())

        details_widget = QWidget()
        details_widget.setObjectName("FTCFileBody")
        details_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        details_widget.setMinimumWidth(0)
        copy_col = QVBoxLayout(details_widget)
        copy_col.setContentsMargins(0, 0, 0, 0)
        copy_col.setSpacing(2)
        self.name_label = ElidedLabel(source.path.name)
        self.name_label.setObjectName("FTCFileName")
        self.meta_label = QLabel(source.label)
        self.meta_label.setObjectName("SmallMeta")

        copy_col.addWidget(self.name_label)
        copy_col.addWidget(self.meta_label)

        actions_widget = QWidget()
        actions_widget.setObjectName("FTCFileActions")
        actions_widget.setFixedWidth(82)
        actions_col = QVBoxLayout(actions_widget)
        actions_col.setContentsMargins(0, 0, 0, 0)
        actions_col.setSpacing(6)

        self.preview_btn = QPushButton("Preview")
        self.preview_btn.setObjectName("CompactGhostButton")
        self.preview_btn.setFixedSize(82, 28)
        self.preview_btn.clicked.connect(lambda: self.preview_requested.emit(self.path))
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.setObjectName("CompactGhostButton")
        self.remove_btn.setFixedSize(82, 28)
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self.path))
        actions_col.addWidget(self.preview_btn)
        actions_col.addWidget(self.remove_btn)
        actions_col.addStretch(1)

        layout.addWidget(self.preview_thumb)
        layout.addWidget(details_widget, 1)
        layout.addWidget(actions_widget, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_locked(self, locked: bool) -> None:
        self.preview_btn.setEnabled(not locked)
        self.remove_btn.setEnabled(not locked)

    def sizeHint(self) -> QSize:
        return QSize(0, 86)


class ActivityLogBrowser(QTextBrowser):
    def __init__(self) -> None:
        super().__init__()
        self.entries: list[dict] = []
        self.setOpenExternalLinks(False)

    def add_entry(self, *, kind: str, title: str, text: str, key: str = "") -> None:
        if key:
            for entry in self.entries:
                if entry["key"] == key:
                    entry["kind"] = kind
                    entry["title"] = title
                    entry["text"] = text
                    self._render()
                    return
        self.entries.append({"key": key, "kind": kind, "title": title, "text": text})
        self._render()

    def clear_log(self) -> None:
        self.entries = []
        self.clear()

    def _render(self) -> None:
        blocks: list[str] = []
        for entry in self.entries:
            body = self._plainify(entry["text"], entry["kind"])
            color = "#7b7b7b" if entry["kind"] == "reasoning" else "#3d3d3d"
            title_color = "#5b5b5b" if entry["kind"] == "status" else "#232323"
            blocks.append(
                "<div style='margin-bottom:12px;'>"
                f"<div style='font-weight:700; color:{title_color}; margin-bottom:4px;'>{html.escape(entry['title'])}</div>"
                f"<div style='color:{color}; white-space:pre-wrap; line-height:1.45;'>{html.escape(body).replace(chr(10), '<br>')}</div>"
                "</div>"
            )
        self.setHtml("<html><body style='font-family: Nunito Sans;'>" + "".join(blocks) + "</body></html>")
        self.moveCursor(QTextCursor.MoveOperation.End)

    @staticmethod
    def _plainify(text: str, kind: str) -> str:
        if kind == "status":
            return text
        document = QTextDocument()
        document.setMarkdown(text or "")
        value = document.toPlainText().strip()
        return value or (text or "")


class CreateTab(QWidget):
    card_saved = Signal()

    def __init__(self, datastore: DataStore, ollama: OllamaService, icons: IconHelper) -> None:
        super().__init__()
        self.datastore = datastore
        self.ollama = ollama
        self.icons = icons
        self.embedding_service = EmbeddingService(datastore, ollama)

        self.autofill_worker: AutofillWorker | None = None
        self.pending_jobs: list[dict] = []
        self.active_job: dict | None = None
        self.embedding_worker: EmbeddingWorker | None = None
        self.pending_embedding_cards: list[dict] = []

        self.ftc_worker: FilesToCardsWorker | None = None
        self.ftc_run: FilesToCardsRunState | None = None
        self.selected_source_files: list[SelectedSourceFile] = []
        self.use_ocr = True

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
        intro = QLabel("Write a question and press Enter or Add question. ONCard will save them one by one.")
        intro.setObjectName("SectionText")
        intro.setWordWrap(True)
        editor_layout.addWidget(header)
        editor_layout.addWidget(intro)

        self.question_input = QuestionInputEdit()
        self.question_input.setPlaceholderText("Write your question here. Press Enter to queue it, or Shift+Enter for a new line.")
        self.question_input.setMinimumHeight(220)
        self.question_input.submitted.connect(self._enqueue_question)
        editor_layout.addWidget(self.question_input)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        self.add_btn = QPushButton("Add question")
        self.add_btn.clicked.connect(self._enqueue_question)
        action_row.addWidget(self.add_btn)
        editor_layout.addLayout(action_row)

        files_frame = QFrame()
        files_frame.setObjectName("QueueRow")
        files_layout = QHBoxLayout(files_frame)
        files_layout.setContentsMargins(18, 18, 18, 18)
        files_layout.setSpacing(18)

        files_left = QVBoxLayout()
        files_left.setContentsMargins(0, 0, 0, 0)
        files_left.setSpacing(16)

        files_right = QVBoxLayout()
        files_right.setContentsMargins(0, 0, 0, 0)
        files_right.setSpacing(12)

        files_title_row = QHBoxLayout()
        files_title_row.setSpacing(10)
        files_beta = QLabel("BETA")
        files_beta.setObjectName("FTCBetaBadge")
        files_title = QLabel("Files To Cards")
        files_title.setObjectName("SectionTitle")
        files_title_row.addWidget(files_beta, 0, Qt.AlignmentFlag.AlignLeft)
        files_title_row.addWidget(files_title, 0, Qt.AlignmentFlag.AlignLeft)
        files_title_row.addStretch(1)
        files_subtitle = QLabel("Drop notes or import files to turn them into queued questions.")
        files_subtitle.setObjectName("SectionText")
        files_subtitle.setWordWrap(True)
        files_left.addLayout(files_title_row)
        files_left.addWidget(files_subtitle)

        self.drop_zone = FileDropZone()
        self.drop_zone.files_dropped.connect(self._import_files)
        files_left.addWidget(self.drop_zone)

        controls_surface = QFrame()
        controls_surface.setObjectName("FTCControlsSurface")
        controls_layout = QVBoxLayout(controls_surface)
        controls_layout.setContentsMargins(14, 14, 14, 14)
        controls_layout.setSpacing(12)

        labels_row = QHBoxLayout()
        labels_row.setSpacing(12)

        import_spacer = QLabel("")
        import_spacer.setMinimumWidth(210)
        labels_row.addWidget(import_spacer)

        mode_label = QLabel("Mode")
        mode_label.setObjectName("SmallMeta")
        labels_row.addWidget(mode_label, 2)

        question_label = QLabel("Questions")
        question_label.setObjectName("SmallMeta")
        labels_row.addWidget(question_label, 1)

        action_spacer = QLabel("")
        labels_row.addWidget(action_spacer, 4)
        controls_layout.addLayout(labels_row)

        controls_row = QHBoxLayout()
        controls_row.setSpacing(12)
        self.import_btn = QPushButton("Import files")
        self.import_btn.clicked.connect(self._browse_files)
        self.import_btn.setMinimumWidth(210)
        controls_row.addWidget(self.import_btn, 2)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Standard", "standard")
        self.mode_combo.addItem("Force", "force")
        self.mode_combo.setItemData(
            1,
            "This feature uses extra compute for smarter answers. This may result in slower, but high quality results",
            Qt.ItemDataRole.ToolTipRole,
        )
        self.mode_combo.currentIndexChanged.connect(self._refresh_files_to_cards_state)
        self.mode_combo.setMinimumWidth(180)
        controls_row.addWidget(self.mode_combo, 2)

        self.question_count = QSpinBox()
        self.question_count.setRange(0, 0)
        self.question_count.setEnabled(False)
        self.question_count.setMinimumWidth(120)
        controls_row.addWidget(self.question_count, 1)

        self.generate_btn = QPushButton("Generate")
        self.generate_btn.setObjectName("PrimaryButton")
        self.generate_btn.clicked.connect(self._start_files_to_cards)
        self.generate_btn.setEnabled(False)
        self.generate_btn.setMinimumWidth(180)
        controls_row.addWidget(self.generate_btn, 2)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._stop_files_to_cards)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setMinimumWidth(140)
        controls_row.addWidget(self.stop_btn, 2)
        controls_layout.addLayout(controls_row)
        files_left.addWidget(controls_surface)

        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(12)
        self.ocr_toggle = QPushButton("Use OCR (improves accuracy)")
        self.ocr_toggle.setObjectName("FTCToggle")
        self.ocr_toggle.setCheckable(True)
        self.ocr_toggle.setChecked(True)
        self.ocr_toggle.toggled.connect(self._on_ocr_toggled)
        toggle_row.addWidget(self.ocr_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.ocr_toggle_hint = QLabel("Reads pages more literally, but can be slower.")
        self.ocr_toggle_hint.setObjectName("SmallMeta")
        toggle_row.addWidget(self.ocr_toggle_hint)
        toggle_row.addStretch(1)
        files_left.addLayout(toggle_row)

        instructions_head = QHBoxLayout()
        instructions_head.setSpacing(10)
        instructions_title = QLabel("Custom instructions")
        instructions_title.setObjectName("SectionTitle")
        instructions_hint = QLabel("Optional tone or teacher-style guidance")
        instructions_hint.setObjectName("SmallMeta")
        instructions_head.addWidget(instructions_title)
        instructions_head.addWidget(instructions_hint)
        instructions_head.addStretch(1)
        self.instructions_count = QLabel("0 / 180")
        self.instructions_count.setObjectName("SmallMeta")
        instructions_head.addWidget(self.instructions_count)
        files_left.addLayout(instructions_head)

        self.instructions_edit = LimitedTextEdit(180)
        self.instructions_edit.setPlaceholderText("Optional instructions")
        self.instructions_edit.setMinimumHeight(68)
        self.instructions_edit.setMaximumHeight(84)
        self.instructions_edit.limited_text_changed.connect(self._on_instructions_changed)
        files_left.addWidget(self.instructions_edit)

        instructions_note = QLabel("(Optional) Give me instructions on how the questions should be like. eg: questions should sound like if it was given by a strict teacher")
        instructions_note.setObjectName("SmallMeta")
        instructions_note.setWordWrap(True)
        files_left.addWidget(instructions_note)

        files_sidebar = QFrame()
        files_sidebar.setObjectName("FTCControlsSurface")
        files_sidebar_layout = QVBoxLayout(files_sidebar)
        files_sidebar_layout.setContentsMargins(14, 14, 14, 14)
        files_sidebar_layout.setSpacing(12)

        sidebar_title = QLabel("Selected files")
        sidebar_title.setObjectName("SectionTitle")
        files_sidebar_layout.addWidget(sidebar_title)

        self.files_summary = QLabel("No files selected yet.")
        self.files_summary.setObjectName("SmallMeta")
        self.files_summary.setWordWrap(True)
        files_sidebar_layout.addWidget(self.files_summary)

        self.selected_files_list = QListWidget()
        self.selected_files_list.setObjectName("FTCFileList")
        self.selected_files_list.setMinimumWidth(320)
        self.selected_files_list.setMaximumWidth(360)
        self.selected_files_list.setSpacing(8)
        self.selected_files_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.selected_files_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.selected_files_list.hide()
        files_sidebar_layout.addWidget(self.selected_files_list, 1)

        files_right.addWidget(files_sidebar, 1)

        files_layout.addLayout(files_left, 3)
        files_layout.addLayout(files_right, 1)

        editor_layout.addWidget(files_frame)
        editor_layout.addStretch(1)

        queue_surface = self._surface()
        queue_layout = QVBoxLayout(queue_surface)
        queue_layout.setContentsMargins(24, 24, 24, 24)
        queue_layout.setSpacing(16)

        queue_title = QLabel("Save queue")
        queue_title.setObjectName("PageTitle")
        queue_sub = QLabel("Queued questions are processed in order. Files To Cards activity also streams here in real time.")
        queue_sub.setObjectName("SectionText")
        queue_sub.setWordWrap(True)
        queue_layout.addWidget(queue_title)
        queue_layout.addWidget(queue_sub)

        self.queue_list = QListWidget()
        queue_layout.addWidget(self.queue_list, 1)

        self.queue_message = ActivityLogBrowser()
        self.queue_message.setMinimumHeight(220)
        self.queue_message.setPlaceholderText("Live activity appears here.")
        queue_layout.addWidget(self.queue_message)

        root.addWidget(editor_surface, 2)
        root.addWidget(queue_surface, 1)

        self._on_ocr_toggled(self.ocr_toggle.isChecked())
        self._refresh_files_to_cards_state()

    def has_pending_work(self) -> bool:
        if self.ftc_worker and self.ftc_worker.isRunning():
            return True
        if self.ftc_run is not None:
            return True
        return bool(self.pending_jobs) or bool(self.active_job) or bool(self.autofill_worker and self.autofill_worker.isRunning())

    def _enqueue_question(self) -> None:
        question = self.question_input.toPlainText().strip()
        if not question:
            return
        item = QListWidgetItem(f"Queued  |  {self._short_label(question)}")
        item.setData(Qt.ItemDataRole.UserRole, {"run_id": "", "source": "manual"})
        self.queue_list.addItem(item)
        self.pending_jobs.append({"question": question, "item": item, "run_id": "", "source": "manual"})
        self._add_activity(kind="status", title="Queue", text="Queued a new question.")
        self.question_input.clear()
        self._process_next_question()

    def _process_next_question(self) -> None:
        if self.active_job is not None or not self.pending_jobs:
            return

        self.active_job = self.pending_jobs.pop(0)
        question = self.active_job["question"]
        item = self.active_job["item"]
        item.setText(f"Saving  |  {self._short_label(question)}")
        self._add_activity(kind="status", title="Queue", text=f"Saving question: {self._short_label(question)}")

        self.autofill_worker = AutofillWorker(
            question,
            self.ollama,
            profile_context=self.datastore.load_profile(),
        )
        self.autofill_worker.progress.connect(lambda message: self._add_activity(kind="status", title="Autofill", text=message))
        self.autofill_worker.field.connect(self._on_field_ready)
        self.autofill_worker.done.connect(self._on_autofill_done)
        self.autofill_worker.failed.connect(self._on_autofill_failed)
        self.autofill_worker.start()

    def _on_field_ready(self, name: str, value) -> None:
        if name == "response_to_user":
            self._add_activity(kind="status", title="Autofill", text=str(value))

    def _on_autofill_done(self, payload: dict) -> None:
        if self.active_job is None:
            return

        job = self.active_job
        run_id = str(job.get("run_id", ""))
        question = job["question"]
        item = job["item"]

        if self._run_is_stopping(run_id):
            item.setText(f"Cancelled  |  {self._short_label(question)}")
            self._add_activity(kind="status", title="Files To Cards", text="Skipped a cancelled queued question.")
            self.active_job = None
            self._finalize_run_if_ready(run_id)
            self._process_next_question()
            return

        payload = dict(payload)
        payload["question"] = question
        if run_id:
            payload["run_id"] = run_id
        saved = self.datastore.save_card(payload)
        item.setText(f"Saved  |  {self._short_label(saved.get('question', ''))}")
        self._add_activity(kind="status", title="Queue", text="Question saved.")
        self._enqueue_embedding(saved)
        self.card_saved.emit()
        self.active_job = None
        self._finalize_run_if_ready(run_id)
        self._process_next_question()

    def _on_autofill_failed(self, message: str) -> None:
        if self.active_job is None:
            return

        job = self.active_job
        item = job["item"]
        run_id = str(job.get("run_id", ""))
        question = job["question"]

        if self._run_is_stopping(run_id):
            item.setText(f"Cancelled  |  {self._short_label(question)}")
            self._add_activity(kind="status", title="Files To Cards", text="Cancelled an in-flight Files To Cards save.")
        else:
            item.setText(f"Failed  |  {self._short_label(question)}")
            self._add_activity(kind="status", title="Autofill", text=message)

        self.active_job = None
        self._finalize_run_if_ready(run_id)
        self._process_next_question()

    def _browse_files(self) -> None:
        paths, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            "Import files",
            "",
            self._file_dialog_filter(),
        )
        if paths:
            self._import_files(paths)

    def _import_files(self, raw_paths: list[str]) -> None:
        if self.ftc_run is not None:
            return

        paths = [Path(path) for path in raw_paths if path]
        if not paths:
            return

        existing_paths = {source.path.resolve() for source in self.selected_source_files}
        target_family = self._current_source_family()
        staged: list[SelectedSourceFile] = list(self.selected_source_files)

        for path in paths:
            if not path.exists():
                continue
            family = detect_source_family(path)
            if family is None:
                continue
            if target_family is None:
                target_family = family
            if not self._family_matches(target_family, family):
                continue
            if path.resolve() in existing_paths:
                continue
            try:
                source = describe_source_file(path)
            except Exception as exc:
                self._add_activity(kind="status", title="Files To Cards", text=f"Skipped {path.name}: {exc}")
                continue
            staged.append(source)
            existing_paths.add(path.resolve())

        if staged == self.selected_source_files:
            self._refresh_files_to_cards_state()
            return

        total_units = sum(source.unit_count for source in staged)
        standard_limit = files_to_cards_limit("standard")
        force_limit = files_to_cards_limit("force")
        current_mode = self._current_mode()
        staged_family = staged[0].family if staged else ""

        if staged_family in {"pdf", "pptx"} and total_units > force_limit:
            QMessageBox.information(
                self,
                "Files To Cards limit",
                "The app can't accept this PDF or slide set because it will put too much stress on the pipeline and may generate incorrect cards.",
            )
            return

        if staged_family in {"pdf", "pptx"} and current_mode == "standard" and total_units > standard_limit:
            prompt = QMessageBox(self)
            prompt.setWindowTitle("Use force mode?")
            prompt.setText(
                'Your file(s) may stress the pipeline. You could use "force" mode which slows down the process by 15-25% but increase capacity?'
            )
            yes_button = prompt.addButton("Yes! use force.", QMessageBox.ButtonRole.YesRole)
            prompt.addButton("No", QMessageBox.ButtonRole.NoRole)
            prompt.exec()
            if prompt.clickedButton() is yes_button:
                self.mode_combo.setCurrentIndex(self.mode_combo.findData("force"))
            else:
                return

        self.selected_source_files = staged
        self.selected_files_list.clear()
        for source in self.selected_source_files:
            self._append_source_row(source)
        self._refresh_files_to_cards_state()

    def _append_source_row(self, source: SelectedSourceFile) -> None:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, str(source.path))
        row = SelectedFileRow(source)
        row.remove_requested.connect(self._remove_source_file)
        row.preview_requested.connect(self._preview_source_file)
        item.setSizeHint(QSize(0, row.sizeHint().height()))
        self.selected_files_list.addItem(item)
        self.selected_files_list.setItemWidget(item, row)

    def _remove_source_file(self, path_str: str) -> None:
        if self.ftc_run is not None:
            return
        self.selected_source_files = [source for source in self.selected_source_files if str(source.path) != path_str]
        for index in range(self.selected_files_list.count() - 1, -1, -1):
            item = self.selected_files_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == path_str:
                self.selected_files_list.takeItem(index)
        self._refresh_files_to_cards_state()

    def _refresh_files_to_cards_state(self) -> None:
        family = self._current_source_family()
        total_units = sum(source.unit_count for source in self.selected_source_files)
        mode = self._current_mode()
        limit = files_to_cards_limit(mode)
        question_cap = files_to_cards_question_cap(total_units, mode)
        locked = self.ftc_run is not None

        if family == "pdf":
            self.drop_zone.set_subtitle("PDF mode is active. Additional imports stay PDF-only.")
        elif family == "pptx":
            self.drop_zone.set_subtitle("PPTX mode is active. Additional imports stay PPTX-only.")
        elif family == "images":
            self.drop_zone.set_subtitle("Image mode is active. You can mix PNG, JPG, JPEG, WEBP, BMP, and TIFF.")
        else:
            self.drop_zone.set_subtitle("Supports images, PDF, and PPTX.")

        if total_units == 0:
            self.files_summary.setText("No files selected yet.")
            self.selected_files_list.hide()
        else:
            self.files_summary.setText(
                f"Selected units: {total_units} / {limit}  |  Max questions now: {question_cap}"
            )
            self.selected_files_list.show()

        self.question_count.setEnabled(total_units > 0 and not locked)
        self.question_count.setMaximum(max(question_cap, 0))
        self.question_count.setMinimum(1 if question_cap else 0)
        if question_cap and self.question_count.value() == 0:
            self.question_count.setValue(1)
        if question_cap and self.question_count.value() > question_cap:
            self.question_count.setValue(question_cap)

        can_generate = total_units > 0 and total_units <= limit and question_cap > 0 and not locked
        self.generate_btn.setEnabled(can_generate)
        self.import_btn.setEnabled(not locked)
        self.mode_combo.setEnabled(not locked)
        self.drop_zone.set_locked(locked)
        self.ocr_toggle.setEnabled(not locked)
        self.ocr_toggle_hint.setEnabled(not locked)
        self.instructions_edit.setReadOnly(locked)
        self.instructions_edit.setEnabled(not locked)
        self.selected_files_list.setEnabled(not locked)
        self.stop_btn.setEnabled(locked)

        for index in range(self.selected_files_list.count()):
            row = self.selected_files_list.itemWidget(self.selected_files_list.item(index))
            if isinstance(row, SelectedFileRow):
                row.set_locked(locked)

    def _on_instructions_changed(self, text: str) -> None:
        self.instructions_count.setText(f"{len(text)} / 180")

    def _on_ocr_toggled(self, checked: bool) -> None:
        self.use_ocr = checked
        self.ocr_toggle.setText("Use OCR (improves accuracy): On" if checked else "Use OCR (improves accuracy): Off")
        self.ocr_toggle_hint.setText(
            "Reads pages more literally, but can be slower."
            if checked
            else "OCR is off. Gemma will read the page visually instead."
        )

    def _preview_source_file(self, path_str: str) -> None:
        source = next((item for item in self.selected_source_files if str(item.path) == path_str), None)
        if source is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Preview - {source.path.name}")
        dialog.resize(860, 640)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        preview_area = PannablePreviewArea()
        preview_area.setMinimumHeight(460)
        try:
            preview = create_source_preview(source.path, max_width=1400, max_height=1800)
            preview_area.set_pixmap(QPixmap.fromImage(preview))
            preview_area.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        except Exception:
            fallback = QLabel(source.path.name)
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback.setObjectName("FTCPreviewDialog")
            preview_area.setWidget(fallback)
        meta = QLabel(f"{source.path.name}\n{source.label}")
        meta.setObjectName("SmallMeta")
        meta.setWordWrap(True)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)

        layout.addWidget(preview_area, 1)
        layout.addWidget(meta)
        layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignRight)
        dialog.exec()

    def _start_files_to_cards(self) -> None:
        if not self.selected_source_files or self.ftc_run is not None:
            return

        total_units = sum(source.unit_count for source in self.selected_source_files)
        limit = files_to_cards_limit(self._current_mode())
        if total_units <= 0 or total_units > limit:
            return

        run_id = str(uuid.uuid4())
        self.ftc_run = FilesToCardsRunState(run_id=run_id, phase="generating", question_entries=[])
        self._refresh_files_to_cards_state()
        self._add_activity(kind="status", title="Files To Cards", text="Started a new Files To Cards run.")

        job = FilesToCardsJob(
            run_id=run_id,
            mode=self._current_mode(),
            source_family=self._current_source_family() or "images",
            file_paths=[source.path for source in self.selected_source_files],
            requested_questions=self.question_count.value(),
            custom_instructions=self.instructions_edit.toPlainText().strip(),
            use_ocr=self.use_ocr,
        )
        self.ftc_worker = FilesToCardsWorker(
            job=job,
            ollama=self.ollama,
            runtime_root=self.datastore.paths.runtime,
        )
        self.ftc_worker.activity.connect(self._handle_ftc_activity)
        self.ftc_worker.question_generated.connect(self._handle_ftc_question_generated)
        self.ftc_worker.completed.connect(self._handle_ftc_completed)
        self.ftc_worker.cancelled.connect(self._handle_ftc_cancelled)
        self.ftc_worker.failed.connect(self._handle_ftc_failed)
        self.ftc_worker.start()

    def _stop_files_to_cards(self) -> None:
        if self.ftc_run is None:
            return
        run_id = self.ftc_run.run_id
        if self.ftc_run.phase == "stopping":
            return

        self.ftc_run.phase = "stopping"
        self._add_activity(kind="status", title="Files To Cards", text="Stopping Files To Cards and removing generated cards...")
        self.datastore.delete_cards_by_run(run_id)
        self.card_saved.emit()
        self._remove_pending_jobs_for_run(run_id)
        if self.ftc_worker and self.ftc_worker.isRunning():
            self.ftc_worker.requestInterruption()
        self._finalize_run_if_ready(run_id)
        self._refresh_files_to_cards_state()

    def _handle_ftc_activity(self, event: dict) -> None:
        if self.ftc_run is None or event.get("run_id") != self.ftc_run.run_id:
            return
        self._add_activity(
            kind=str(event.get("kind", "status")),
            title=str(event.get("title", "Files To Cards")),
            text=str(event.get("text", "")),
            key=str(event.get("key", "")),
        )

    def _handle_ftc_question_generated(self, run_id: str, question: str) -> None:
        if self.ftc_run is None or run_id != self.ftc_run.run_id:
            return
        item = QListWidgetItem(f"Prepared  |  {self._short_label(question)}")
        item.setData(Qt.ItemDataRole.UserRole, {"run_id": run_id, "source": "ftc"})
        self.queue_list.addItem(item)
        self.ftc_run.question_entries.append({"question": question, "item": item})

    def _handle_ftc_completed(self, run_id: str, questions: list[str]) -> None:
        if self.ftc_run is None or run_id != self.ftc_run.run_id:
            return
        self.ftc_worker = None
        if self.ftc_run.phase == "stopping":
            self._finalize_run_if_ready(run_id)
            return

        self.ftc_run.phase = "autofill"
        jobs: list[dict] = []
        for index, question in enumerate(questions):
            if index < len(self.ftc_run.question_entries):
                item = self.ftc_run.question_entries[index]["item"]
            else:
                item = QListWidgetItem(f"Prepared  |  {self._short_label(question)}")
                item.setData(Qt.ItemDataRole.UserRole, {"run_id": run_id, "source": "ftc"})
                self.queue_list.addItem(item)
            item.setText(f"Queued  |  {self._short_label(question)}")
            jobs.append({"question": question, "item": item, "run_id": run_id, "source": "ftc"})

        self.pending_jobs = jobs + self.pending_jobs
        self._add_activity(kind="status", title="Files To Cards", text="Question generation finished. Autofill is starting...")
        self._process_next_question()
        self._finalize_run_if_ready(run_id)

    def _handle_ftc_cancelled(self, run_id: str, message: str) -> None:
        if self.ftc_run is None or run_id != self.ftc_run.run_id:
            return
        self.ftc_worker = None
        self._add_activity(kind="status", title="Files To Cards", text=message)
        self._finalize_run_if_ready(run_id)

    def _handle_ftc_failed(self, run_id: str, message: str) -> None:
        if self.ftc_run is None or run_id != self.ftc_run.run_id:
            return
        self.ftc_worker = None
        if "Gemma could not generate enough unique questions" in message:
            generated_count = len(self.ftc_run.question_entries)
            if generated_count > 0:
                answer = QMessageBox.question(
                    self,
                    "Accept partial questions?",
                    f"FTC pipeline is experiencing extreme stress. would you like to accept {generated_count} questions?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if answer == QMessageBox.Yes:
                    self._add_activity(
                        kind="status",
                        title="Files To Cards",
                        text=f"Gemma stalled, but accepting the {generated_count} generated question(s).",
                    )
                    self._handle_ftc_completed(
                        run_id,
                        [entry["question"] for entry in self.ftc_run.question_entries],
                    )
                    return

        self._add_activity(kind="status", title="Files To Cards", text=f"Files To Cards failed: {message}")
        self.datastore.delete_cards_by_run(run_id)
        self._remove_pending_jobs_for_run(run_id)
        self._remove_queue_items_for_run(run_id)
        self._cleanup_run_runtime(run_id)
        self.ftc_run = None
        self._refresh_files_to_cards_state()

    def _remove_pending_jobs_for_run(self, run_id: str) -> None:
        self.pending_jobs = [job for job in self.pending_jobs if str(job.get("run_id", "")) != run_id]

    def _finalize_run_if_ready(self, run_id: str) -> None:
        if not run_id or self.ftc_run is None or self.ftc_run.run_id != run_id:
            return
        worker_busy = bool(self.ftc_worker and self.ftc_worker.isRunning())
        active_busy = bool(self.active_job and str(self.active_job.get("run_id", "")) == run_id)
        pending_busy = any(str(job.get("run_id", "")) == run_id for job in self.pending_jobs)
        if worker_busy or active_busy or pending_busy:
            return

        if self.ftc_run.phase == "stopping":
            self.datastore.delete_cards_by_run(run_id)
            self.card_saved.emit()
            self._remove_queue_items_for_run(run_id)
            self._add_activity(kind="status", title="Files To Cards", text="Files To Cards stopped. Generated cards were removed.")
        elif self.ftc_run.phase == "autofill":
            self._add_activity(kind="status", title="Files To Cards", text="Files To Cards finished successfully.")

        self._cleanup_run_runtime(run_id)
        self.ftc_run = None
        self._refresh_files_to_cards_state()

    def _remove_queue_items_for_run(self, run_id: str) -> None:
        for index in range(self.queue_list.count() - 1, -1, -1):
            item = self.queue_list.item(index)
            data = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, dict) and data.get("run_id") == run_id:
                self.queue_list.takeItem(index)

    def _run_is_stopping(self, run_id: str) -> bool:
        return bool(self.ftc_run and run_id and self.ftc_run.run_id == run_id and self.ftc_run.phase == "stopping")

    def _current_mode(self) -> str:
        return str(self.mode_combo.currentData() or "standard")

    def _current_source_family(self) -> str | None:
        if not self.selected_source_files:
            return None
        return self.selected_source_files[0].family

    def _file_dialog_filter(self) -> str:
        family = self._current_source_family()
        if family == "pdf":
            return "PDF Files (*.pdf)"
        if family == "pptx":
            return "PowerPoint Files (*.pptx)"
        if family == "images":
            return "Image Files (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)"
        return "Supported Files (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.pdf *.pptx)"

    @staticmethod
    def _family_matches(target_family: str, family: str) -> bool:
        return target_family == family

    def _add_activity(self, *, kind: str, title: str, text: str, key: str = "") -> None:
        self.queue_message.add_entry(kind=kind, title=title, text=text, key=key)

    def _cleanup_run_runtime(self, run_id: str) -> None:
        run_dir = self.datastore.paths.runtime / "files_to_cards" / run_id
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)

    def _enqueue_embedding(self, card: dict) -> None:
        card_id = str(card.get("id", "")).strip()
        if not card_id:
            return
        if self.embedding_service.is_card_cached(card):
            return
        if any(str(item.get("id", "")).strip() == card_id for item in self.pending_embedding_cards):
            return
        self.pending_embedding_cards.append(card)
        self._start_embedding_worker()

    def _start_embedding_worker(self) -> None:
        if self.embedding_worker is not None or not self.pending_embedding_cards:
            return
        card = self.pending_embedding_cards.pop(0)
        self.embedding_worker = EmbeddingWorker(cards=[card], embedding_service=self.embedding_service)
        self.embedding_worker.finished.connect(self._on_embedding_finished)
        self.embedding_worker.failed.connect(self._on_embedding_failed)
        self.embedding_worker.start()

    def _on_embedding_finished(self, _cards: list[dict]) -> None:
        self.embedding_worker = None
        self._start_embedding_worker()

    def _on_embedding_failed(self, _message: str) -> None:
        self.embedding_worker = None
        self._start_embedding_worker()

    @staticmethod
    def _short_label(text: str, limit: int = 56) -> str:
        compact = " ".join(text.split())
        return compact if len(compact) <= limit else f"{compact[:limit - 1]}..."
