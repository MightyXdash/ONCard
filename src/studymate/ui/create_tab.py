from __future__ import annotations

from dataclasses import dataclass
import html
from pathlib import Path
import shutil
import uuid

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QIcon, QMouseEvent, QPixmap, QTextCursor, QTextDocument, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QBoxLayout,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsBlurEffect,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTextBrowser,
    QTextEdit,
    QToolButton,
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
from studymate.services.model_registry import resolve_active_text_llm_spec, resolve_active_text_model_tag
from studymate.services.model_preflight import ModelPreflightService
from studymate.services.ollama_service import OllamaService
from studymate.ui.animated import AnimatedButton, AnimatedComboBox, polish_surface
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


class ProtectedInstructionEdit(LimitedTextEdit):
    def __init__(self, max_chars: int, parent=None) -> None:
        self._locked_prefix = ""
        self._extra_text = ""
        self._syncing_text = False
        super().__init__(max_chars, parent)
        self.cursorPositionChanged.connect(self._keep_cursor_after_prefix)

    def set_locked_prefix(self, text: str) -> None:
        self._locked_prefix = (text or "").strip()
        self._apply_text(self._extra_text)

    def set_extra_text(self, text: str) -> None:
        self._extra_text = (text or "").strip()
        self._apply_text(self._extra_text)

    def extra_text(self) -> str:
        return self._extra_text

    def combined_text(self) -> str:
        return self._compose_text(self._extra_text)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        QTimer.singleShot(0, self._keep_cursor_after_prefix)

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        QTimer.singleShot(0, self._keep_cursor_after_prefix)

    def keyPressEvent(self, event) -> None:
        super().keyPressEvent(event)
        self._keep_cursor_after_prefix()

    def _compose_text(self, extra_text: str) -> str:
        prefix = self._locked_prefix.strip()
        extra = (extra_text or "").strip()
        if prefix and extra:
            return f"{prefix}\n\n{extra}"
        return prefix or extra

    def _extract_extra_text(self, text: str) -> str:
        compact = (text or "").strip()
        prefix = self._locked_prefix.strip()
        if not prefix:
            return compact
        if compact.startswith(prefix):
            return compact[len(prefix) :].lstrip("\n").strip()
        return compact

    def _apply_text(self, extra_text: str) -> None:
        combined = self._compose_text(extra_text)
        self._syncing_text = True
        self.setPlainText(combined)
        cursor = self.textCursor()
        cursor.setPosition(len(combined))
        self.setTextCursor(cursor)
        self._syncing_text = False
        self.limited_text_changed.emit(combined)

    def _keep_cursor_after_prefix(self) -> None:
        prefix_length = len(self._locked_prefix.strip())
        if prefix_length <= 0:
            return
        document_length = len(self.toPlainText())
        if document_length <= 0:
            return
        cursor = self.textCursor()
        if cursor.position() < prefix_length:
            target_position = min(max(prefix_length, cursor.position()), document_length)
            cursor.setPosition(target_position)
            self.setTextCursor(cursor)

    def _enforce_limit(self) -> None:
        if self._syncing_text:
            return
        extra_text = self._extract_extra_text(self.toPlainText())
        combined = self._compose_text(extra_text)
        if len(combined) > self.max_chars:
            empty_prefix_length = len(self._compose_text(""))
            available_extra = max(0, self.max_chars - empty_prefix_length)
            extra_text = extra_text[:available_extra].rstrip()
            combined = self._compose_text(extra_text)
        self._extra_text = extra_text
        if self.toPlainText() != combined:
            self._syncing_text = True
            self.setPlainText(combined)
            cursor = self.textCursor()
            cursor.setPosition(len(combined))
            self.setTextCursor(cursor)
            self._syncing_text = False
        self.limited_text_changed.emit(combined)


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


class HorizontalGalleryScrollArea(QScrollArea):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setObjectName("FTCHorizontalRail")

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            delta = event.angleDelta().y() or event.pixelDelta().y()
            if delta:
                self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta)
                event.accept()
                return
        super().wheelEvent(event)


class UploadTileButton(QFrame):
    clicked = Signal()

    def __init__(self, icon: QIcon, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("FTCUploadTile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(168, 156)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(10)
        layout.addStretch(5)

        self.icon_label = QLabel()
        self.icon_label.setObjectName("FTCUploadTileIcon")
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setPixmap(icon.pixmap(QSize(34, 34)))
        layout.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignCenter)

        self.text_label = QLabel("Or drag & drop")
        self.text_label.setObjectName("FTCUploadTileText")
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.text_label, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(3)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.setProperty("hovered", True)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.setProperty("hovered", False)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()) and self.isEnabled():
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class FileSkeletonCard(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("FTCSkeletonCard")
        self.setFixedSize(168, 156)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        thumb = QFrame()
        thumb.setObjectName("FTCSkeletonThumb")
        thumb.setFixedSize(52, 52)
        layout.addWidget(thumb, 0, Qt.AlignmentFlag.AlignCenter)

        bar_one = QFrame()
        bar_one.setObjectName("FTCSkeletonBar")
        bar_one.setFixedHeight(12)
        layout.addWidget(bar_one)

        bar_two = QFrame()
        bar_two.setObjectName("FTCSkeletonBarSoft")
        bar_two.setFixedHeight(10)
        layout.addWidget(bar_two)
        layout.addStretch(1)


class SelectedFileCard(QFrame):
    remove_requested = Signal(str)
    preview_requested = Signal(str)

    def __init__(self, source: SelectedSourceFile, *, remove_icon: QIcon) -> None:
        super().__init__()
        self.setObjectName("FTCFileCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(168, 156)
        self.path = str(source.path)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(6)
        top_row.addStretch(1)

        self.remove_btn = QToolButton()
        self.remove_btn.setObjectName("FTCFileRemove")
        self.remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_btn.setIcon(remove_icon)
        self.remove_btn.setIconSize(QSize(12, 12))
        self.remove_btn.setAutoRaise(True)
        self.remove_btn.clicked.connect(lambda _checked=False: self.remove_requested.emit(self.path))
        top_row.addWidget(self.remove_btn, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(top_row)

        self.preview_thumb = QLabel()
        self.preview_thumb.setObjectName("FTCFileCardThumb")
        self.preview_thumb.setFixedSize(56, 56)
        self.preview_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        try:
            preview = create_source_preview(source.path, max_width=56, max_height=56)
            self.preview_thumb.setPixmap(QPixmap.fromImage(preview))
        except Exception:
            self.preview_thumb.setText(source.family.upper())
        layout.addWidget(self.preview_thumb, 0, Qt.AlignmentFlag.AlignCenter)

        self.name_label = QLabel(self._trim_title(source.path.name))
        self.name_label.setObjectName("FTCFileCardName")
        self.name_label.setWordWrap(False)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setFixedHeight(22)
        layout.addWidget(self.name_label)
        layout.addStretch(1)

    def set_locked(self, locked: bool) -> None:
        self.remove_btn.setVisible(not locked)
        self.remove_btn.setEnabled(not locked)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self.remove_btn.geometry().contains(event.position().toPoint()):
            self.preview_requested.emit(self.path)
            event.accept()
            return
        super().mousePressEvent(event)

    def _trim_title(self, text: str) -> str:
        available_width = 126
        metrics = self.fontMetrics()
        compact = (text or "").strip()
        if metrics.horizontalAdvance(compact) <= available_width:
            return compact
        trimmed = compact
        while len(trimmed) > 3 and metrics.horizontalAdvance(f"{trimmed}...") > available_width:
            trimmed = trimmed[:-3]
        return f"{trimmed}..." if trimmed else "..."


class FTCUploadGallery(QFrame):
    files_dropped = Signal(list)
    browse_requested = Signal()
    preview_requested = Signal(str)
    remove_requested = Signal(str)

    def __init__(self, icons: IconHelper) -> None:
        super().__init__()
        self._locked = False
        self._icons = icons
        self.setObjectName("FTCUploadSurface")
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)

        self.scroll_area = HorizontalGalleryScrollArea()
        self.scroll_area.setFixedHeight(182)
        self.cards_host = QWidget()
        self.cards_host.setObjectName("FTCRailCanvas")
        self.cards_host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.cards_layout = QHBoxLayout(self.cards_host)
        self.cards_layout.setContentsMargins(0, 0, 30, 0)
        self.cards_layout.setSpacing(14)
        self.scroll_area.setWidget(self.cards_host)
        layout.addWidget(self.scroll_area)

        self.summary_label = QLabel("No files selected yet.")
        self.summary_label.setObjectName("SmallMeta")
        self.summary_label.setWordWrap(True)
        self.summary_label.hide()

        self.hint_label = QLabel("Supports images, PDF, and PPTX.")
        self.hint_label.setObjectName("SmallMeta")
        self.hint_label.setWordWrap(True)
        self.hint_label.hide()

        self.upload_tile = UploadTileButton(self._icons.icon("common", "upload", "U"))
        self.upload_tile.clicked.connect(lambda _checked=False: self.browse_requested.emit())
        self.cards_layout.addWidget(self.upload_tile)
        self._dynamic_cards: list[QWidget] = []

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self.upload_tile.setEnabled(not locked)
        for card in self._dynamic_cards:
            if hasattr(card, "set_locked"):
                card.set_locked(locked)

    def set_summary(self, summary_text: str, hint_text: str) -> None:
        tooltip_lines = [line for line in [summary_text.strip(), hint_text.strip()] if line]
        self.setToolTip("\n".join(tooltip_lines))

    def set_sources(self, sources: list[SelectedSourceFile]) -> None:
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(1)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._dynamic_cards.clear()

        remove_icon = self._icons.icon("common", "cross_two", "X")
        for source in sources:
            card = SelectedFileCard(source, remove_icon=remove_icon)
            card.set_locked(self._locked)
            card.preview_requested.connect(self.preview_requested.emit)
            card.remove_requested.connect(self.remove_requested.emit)
            self.cards_layout.addWidget(card)
            self._dynamic_cards.append(card)

        placeholder_count = max(2, 4 - len(sources))
        for _ in range(placeholder_count):
            card = FileSkeletonCard()
            self.cards_layout.addWidget(card)
            self._dynamic_cards.append(card)

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


class FTCControlsDialog(QDialog):
    def __init__(
        self,
        *,
        parent: QWidget,
        blur_target: QWidget | None,
        current_mode: str,
        question_value: int,
        question_caps: dict[str, int],
        default_counts: dict[str, int],
        model_label: str,
    ) -> None:
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._blur_target = blur_target or parent
        self._overlay_target = parent
        self._overlay: QWidget | None = None
        self._previous_effect = None
        self._question_caps = question_caps
        self._default_counts = default_counts
        self._mode_value = current_mode
        self._question_value = int(question_value)
        self._popup_question_limits = {
            "standard": 14,
            "force": 29,
        }

        root = QVBoxLayout(self)
        root.setContentsMargins(44, 44, 44, 44)
        root.setSpacing(0)
        root.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)

        self.card = QFrame(self)
        self.card.setObjectName("FTCControlsPopupCard")
        card_shadow = QGraphicsDropShadowEffect(self.card)
        card_shadow.setBlurRadius(44)
        card_shadow.setOffset(0, 0)
        card_shadow.setColor(QColor(13, 26, 39, 105))
        self.card.setGraphicsEffect(card_shadow)
        root.addWidget(self.card)

        body = QVBoxLayout(self.card)
        body.setContentsMargins(24, 22, 24, 20)
        body.setSpacing(16)
        body.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title = QLabel("FTC controls")
        title.setObjectName("SectionTitle")
        header.addWidget(title)
        header.addStretch(1)

        check_icon = parent.icons.icon("common", "check", "C") if hasattr(parent, "icons") else QIcon()
        close_icon = parent.icons.icon("common", "cross_two", "X") if hasattr(parent, "icons") else QIcon()

        self.save_btn = QToolButton()
        self.save_btn.setObjectName("FTCPopupIconButton")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setIcon(check_icon)
        self.save_btn.setIconSize(QSize(15, 15))
        self.save_btn.setFixedSize(34, 34)
        self.save_btn.clicked.connect(self._save_and_accept)
        header.addWidget(self.save_btn)

        self.close_btn = QToolButton()
        self.close_btn.setObjectName("FTCPopupIconButton")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setIcon(close_icon)
        self.close_btn.setIconSize(QSize(15, 15))
        self.close_btn.setFixedSize(34, 34)
        self.close_btn.clicked.connect(self.reject)
        header.addWidget(self.close_btn)
        body.addLayout(header)

        subtitle = QLabel("These change the current run. FTC uses the model already selected in Settings.")
        subtitle.setObjectName("SmallMeta")
        subtitle.setWordWrap(True)
        body.addWidget(subtitle)

        model_shell = QFrame()
        model_shell.setObjectName("FTCPopupValueShell")
        model_layout = QVBoxLayout(model_shell)
        model_layout.setContentsMargins(14, 12, 14, 12)
        model_layout.setSpacing(4)
        model_title = QLabel("Model")
        model_title.setObjectName("SmallMeta")
        model_value = QLabel(model_label)
        model_value.setObjectName("FTCPopupValueText")
        model_value.setWordWrap(True)
        model_layout.addWidget(model_title)
        model_layout.addWidget(model_value)
        body.addWidget(model_shell)

        fields_layout = QVBoxLayout()
        fields_layout.setContentsMargins(0, 0, 0, 0)
        fields_layout.setSpacing(10)

        mode_title = QLabel("Mode")
        mode_title.setObjectName("SmallMeta")
        fields_layout.addWidget(mode_title)

        mode_shell = QFrame()
        mode_shell.setObjectName("FTCPopupFieldShell")
        mode_shell_layout = QHBoxLayout(mode_shell)
        mode_shell_layout.setContentsMargins(8, 8, 8, 8)
        mode_shell_layout.setSpacing(8)
        self._mode_buttons: dict[str, AnimatedButton] = {}
        for label, value in (("Standard", "standard"), ("Force", "force")):
            button = AnimatedButton(label)
            button.setObjectName("FTCPopupChoiceButton")
            button.setCheckable(True)
            button.setProperty("disablePressMotion", True)
            button.set_motion_scale_range(0.0)
            button.clicked.connect(lambda _checked=False, selected=value: self._set_mode_value(selected))
            mode_shell_layout.addWidget(button, 1)
            self._mode_buttons[value] = button
        fields_layout.addWidget(mode_shell)

        question_title = QLabel("Questions")
        question_title.setObjectName("SmallMeta")
        fields_layout.addWidget(question_title)

        question_shell = QFrame()
        question_shell.setObjectName("FTCPopupFieldShell")
        question_shell_layout = QHBoxLayout(question_shell)
        question_shell_layout.setContentsMargins(8, 8, 8, 8)
        question_shell_layout.setSpacing(10)

        self.question_minus_btn = AnimatedButton("-")
        self.question_minus_btn.setObjectName("FTCPopupStepButton")
        self.question_minus_btn.setProperty("disablePressMotion", True)
        self.question_minus_btn.set_motion_scale_range(0.0)
        self.question_minus_btn.clicked.connect(lambda: self._step_question_value(-1))
        question_shell_layout.addWidget(self.question_minus_btn, 0)

        self.question_value_label = QLabel()
        self.question_value_label.setObjectName("FTCPopupQuestionValue")
        self.question_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        question_shell_layout.addWidget(self.question_value_label, 1)

        self.question_plus_btn = AnimatedButton("+")
        self.question_plus_btn.setObjectName("FTCPopupStepButton")
        self.question_plus_btn.setProperty("disablePressMotion", True)
        self.question_plus_btn.set_motion_scale_range(0.0)
        self.question_plus_btn.clicked.connect(lambda: self._step_question_value(1))
        question_shell_layout.addWidget(self.question_plus_btn, 0)
        fields_layout.addWidget(question_shell)
        body.addLayout(fields_layout)

        self._sync_question_bounds(initial_value=question_value)
        self._refresh_mode_buttons()
        self._refresh_question_controls()
        self.setMinimumWidth(500)

    def current_mode(self) -> str:
        return str(self._mode_value or "standard")

    def current_question_count(self) -> int:
        return int(self._question_value)

    def exec_with_backdrop(self) -> int:
        self._apply_backdrop()
        try:
            self._resize_for_available_space()
            self._center_on_parent()
            return self.exec()
        finally:
            self._clear_backdrop()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self.card.geometry().contains(event.position().toPoint()):
            self.reject()
            event.accept()
            return
        super().mousePressEvent(event)

    def _sync_question_bounds(self, _index: int | None = None, *, initial_value: int | None = None) -> None:
        mode = self.current_mode()
        fallback = max(1, int(self._default_counts.get(mode, 4)))
        max_value = max(1, int(self._popup_question_limits.get(mode, fallback)))
        if initial_value is not None:
            target_value = max(1, min(int(initial_value), max_value))
            self._question_value = target_value
        else:
            target_value = min(fallback, max_value)
            self._question_value = max(1, min(int(self._question_value), max_value))
        if initial_value is None:
            self._question_value = target_value
        self._question_value = max(1, min(int(self._question_value), max_value))
        self._refresh_question_controls()

    def _current_question_limit(self) -> int:
        mode = self.current_mode()
        fallback = max(1, int(self._default_counts.get(mode, 4)))
        return max(1, int(self._popup_question_limits.get(mode, fallback)))

    def _set_mode_value(self, mode: str) -> None:
        if mode == self._mode_value:
            return
        self._mode_value = mode
        self._refresh_mode_buttons()
        self._sync_question_bounds()

    def _refresh_mode_buttons(self) -> None:
        for mode, button in self._mode_buttons.items():
            checked = mode == self._mode_value
            button.setChecked(checked)
            button.setProperty("selected", checked)
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()

    def _step_question_value(self, delta: int) -> None:
        limit = self._current_question_limit()
        self._question_value = max(1, min(limit, int(self._question_value) + int(delta)))
        self._refresh_question_controls()

    def _refresh_question_controls(self) -> None:
        limit = self._current_question_limit()
        self.question_value_label.setText(str(self._question_value))
        self.question_minus_btn.setEnabled(self._question_value > 1)
        self.question_plus_btn.setEnabled(self._question_value < limit)

    def _save_and_accept(self) -> None:
        self.done(QDialog.DialogCode.Accepted)

    def _center_on_parent(self) -> None:
        parent_widget = self.parentWidget()
        if parent_widget is None:
            return
        parent_rect = parent_widget.frameGeometry()
        self.move(
            int(parent_rect.center().x() - (self.width() / 2)),
            int(parent_rect.center().y() - (self.height() / 2)),
        )

    def _resize_for_available_space(self) -> None:
        layout = self.layout()
        if layout is not None:
            layout.activate()
        card_layout = self.card.layout()
        if card_layout is not None:
            card_layout.activate()
        reference = self.parentWidget()
        screen = reference.screen() if reference is not None else self.screen()
        content_hint = self.sizeHint()
        if screen is None:
            self.resize(max(self.minimumWidth(), content_hint.width()), content_hint.height())
            return
        available = screen.availableGeometry()
        target_width = min(max(self.minimumWidth(), content_hint.width()), max(420, available.width() - 96))
        target_height = min(content_hint.height(), max(360, available.height() - 120))
        self.resize(target_width, target_height)

    def _apply_backdrop(self) -> None:
        if self._blur_target is None:
            return
        self._previous_effect = self._blur_target.graphicsEffect()
        blur = QGraphicsBlurEffect(self._blur_target)
        blur.setBlurRadius(8.0)
        self._blur_target.setGraphicsEffect(blur)

        overlay = QWidget(self._overlay_target)
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        overlay.setStyleSheet("background: rgba(255, 255, 255, 0.10);")
        top_left = self._blur_target.mapTo(self._overlay_target, QPoint(0, 0))
        overlay.setGeometry(QRect(top_left, self._blur_target.size()))
        overlay.show()
        overlay.raise_()
        self._overlay = overlay

    def _clear_backdrop(self) -> None:
        if self._overlay is not None:
            self._overlay.hide()
            self._overlay.deleteLater()
            self._overlay = None
        if self._blur_target is not None:
            self._blur_target.setGraphicsEffect(self._previous_effect)
        self._previous_effect = None


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

        self.preview_btn = AnimatedButton("Preview")
        self.preview_btn.setObjectName("CompactGhostButton")
        self.preview_btn.setFixedSize(82, 28)
        self.preview_btn.clicked.connect(lambda: self.preview_requested.emit(self.path))
        self.remove_btn = AnimatedButton("Remove")
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
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render)

    def add_entry(self, *, kind: str, title: str, text: str, key: str = "") -> None:
        if key:
            for entry in self.entries:
                if entry["key"] == key:
                    entry["kind"] = kind
                    entry["title"] = title
                    entry["text"] = text
                    self._schedule_render()
                    return
        self.entries.append({"key": key, "kind": kind, "title": title, "text": text})
        self._schedule_render()

    def clear_log(self) -> None:
        self.entries = []
        self.clear()

    def _schedule_render(self) -> None:
        if not self._render_timer.isActive():
            self._render_timer.start(60)

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
    ftc_completed = Signal(str)

    def __init__(
        self,
        datastore: DataStore,
        ollama: OllamaService,
        icons: IconHelper,
        preflight: ModelPreflightService | None = None,
    ) -> None:
        super().__init__()
        self.datastore = datastore
        self.ollama = ollama
        self.icons = icons
        self.embedding_service = EmbeddingService(datastore, ollama)
        self.preflight = preflight or ModelPreflightService(datastore, ollama)

        self.autofill_worker: AutofillWorker | None = None
        self.pending_jobs: list[dict] = []
        self.active_job: dict | None = None
        self.embedding_worker: EmbeddingWorker | None = None
        self.pending_embedding_cards: list[dict] = []

        self.ftc_worker: FilesToCardsWorker | None = None
        self.ftc_run: FilesToCardsRunState | None = None
        self.selected_source_files: list[SelectedSourceFile] = []
        self._ftc_stashed_source_files: list[SelectedSourceFile] = []
        self.use_ocr = True
        self._ftc_default_instruction = ""
        self._ftc_defaults = self._load_ftc_defaults()
        self._last_ftc_mode = str(self._ftc_defaults.get("default_mode", "standard"))
        self._ftc_question_preferences = {
            "standard": int(self._ftc_defaults.get("question_count_standard", 4)),
            "force": int(self._ftc_defaults.get("question_count_force", 8)),
        }

        self._build_ui()
        self.refresh_ftc_defaults(force=True)

    def _play_sound(self, name: str) -> None:
        parent = self.window()
        sounds = getattr(parent, "sounds", None)
        if sounds is not None:
            sounds.play(name)

    def _active_text_llm_spec(self):
        return resolve_active_text_llm_spec(self.datastore.load_ai_settings())

    def _active_text_model_tag(self) -> str:
        return resolve_active_text_model_tag(self.datastore.load_ai_settings())

    def _surface(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Surface")
        polish_surface(frame)
        return frame

    def _apply_soft_shadow(self, widget: QWidget, *, blur: int = 26, alpha: int = 28, y_offset: int = 8) -> None:
        shadow = QGraphicsDropShadowEffect(widget)
        shadow.setBlurRadius(blur)
        shadow.setOffset(0, y_offset)
        shadow.setColor(QColor(15, 37, 57, alpha))
        widget.setGraphicsEffect(shadow)

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
        self.add_btn = AnimatedButton("Add question")
        self.add_btn.setProperty("skipClickSfx", True)
        self.add_btn.clicked.connect(self._enqueue_question)
        action_row.addWidget(self.add_btn)
        editor_layout.addLayout(action_row)

        files_frame = QFrame()
        files_frame.setObjectName("QueueRow")
        files_layout = QVBoxLayout(files_frame)
        files_layout.setContentsMargins(18, 18, 18, 18)
        files_layout.setSpacing(18)

        files_title_row = QVBoxLayout()
        files_title_row.setSpacing(6)
        files_title = QLabel("Files To Cards")
        files_title.setObjectName("SectionTitle")
        files_subtitle = QLabel("Turn notes, slides, or images into queued questions with a cleaner FTC workflow.")
        files_subtitle.setObjectName("SectionText")
        files_subtitle.setWordWrap(True)
        files_title_row.addWidget(files_title, 0, Qt.AlignmentFlag.AlignLeft)
        files_title_row.addWidget(files_subtitle)
        files_layout.addLayout(files_title_row)

        self.mode_combo = AnimatedComboBox(self)
        self.mode_combo.addItem("Standard", "standard")
        self.mode_combo.addItem("Force", "force")
        self.mode_combo.setItemData(
            1,
            "This feature uses extra compute for smarter answers. This may result in slower, but high quality results",
            Qt.ItemDataRole.ToolTipRole,
        )
        self.mode_combo.currentIndexChanged.connect(self._refresh_files_to_cards_state)
        self.mode_combo.hide()

        self.question_count = QSpinBox(self)
        self.question_count.setRange(0, 0)
        self.question_count.setEnabled(False)
        self.question_count.valueChanged.connect(lambda _value: self._sync_ftc_summary())
        self.question_count.hide()

        top_host = QFrame()
        top_host.setObjectName("FTCSharedCanvas")
        polish_surface(top_host)
        self._apply_soft_shadow(top_host, blur=30, alpha=22, y_offset=8)
        self._ftc_top_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, top_host)
        self._ftc_top_layout.setContentsMargins(18, 18, 18, 18)
        self._ftc_top_layout.setSpacing(18)

        summary_surface = QFrame()
        summary_surface.setObjectName("FTCInfoSurface")
        polish_surface(summary_surface)
        summary_layout = QVBoxLayout(summary_surface)
        summary_layout.setContentsMargins(18, 18, 18, 18)
        summary_layout.setSpacing(14)

        summary_meta = QLabel("These are the live FTC controls for this run.")
        summary_meta.setObjectName("SmallMeta")
        summary_meta.setWordWrap(True)
        summary_layout.addWidget(summary_meta)

        overview_card = QFrame()
        overview_card.setObjectName("FTCControlsSurface")
        polish_surface(overview_card)
        self._apply_soft_shadow(overview_card, blur=22, alpha=18, y_offset=5)
        overview_layout = QHBoxLayout(overview_card)
        overview_layout.setContentsMargins(18, 14, 18, 14)
        overview_layout.setSpacing(18)

        self.ftc_mode_value = QLabel()
        self.ftc_mode_value.setObjectName("FTCStatValue")
        self.ftc_mode_value.setTextFormat(Qt.TextFormat.RichText)
        self.ftc_mode_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ftc_mode_value.setMinimumHeight(32)

        self.ftc_questions_value = QLabel()
        self.ftc_questions_value.setObjectName("FTCStatValue")
        self.ftc_questions_value.setTextFormat(Qt.TextFormat.RichText)
        self.ftc_questions_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ftc_questions_value.setMinimumHeight(32)

        overview_divider = QFrame()
        overview_divider.setObjectName("FTCInnerDivider")
        overview_divider.setFixedWidth(1)
        overview_divider.setFixedHeight(56)

        overview_layout.addWidget(self.ftc_mode_value, 1)
        overview_layout.addWidget(overview_divider, 0, Qt.AlignmentFlag.AlignVCenter)
        overview_layout.addWidget(self.ftc_questions_value, 1)
        summary_layout.addWidget(overview_card)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(10)

        self.ftc_menu_btn = QToolButton()
        self.ftc_menu_btn.setObjectName("FTCMenuButton")
        self.ftc_menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ftc_menu_btn.setIcon(self.icons.icon("common", "menu", "M"))
        self.ftc_menu_btn.setIconSize(QSize(18, 18))
        self.ftc_menu_btn.clicked.connect(self._open_ftc_controls_dialog)
        action_row.addWidget(self.ftc_menu_btn, 0)

        self.generate_btn = AnimatedButton("Generate")
        self.generate_btn.setObjectName("FTCGenerateButton")
        self.generate_btn.setProperty("skipClickSfx", True)
        self.generate_btn.setProperty("disablePressMotion", True)
        self.generate_btn.set_motion_scale_range(0.0)
        self.generate_btn.clicked.connect(self._on_ftc_action_pressed)
        self.generate_btn.setEnabled(False)
        action_row.addWidget(self.generate_btn, 1)
        summary_layout.addLayout(action_row)
        summary_layout.addStretch(1)

        self.upload_gallery = FTCUploadGallery(self.icons)
        polish_surface(self.upload_gallery)
        self.upload_gallery.files_dropped.connect(self._import_files)
        self.upload_gallery.browse_requested.connect(self._browse_files)
        self.upload_gallery.preview_requested.connect(self._preview_source_file)
        self.upload_gallery.remove_requested.connect(self._remove_source_file)

        self._ftc_top_layout.addWidget(summary_surface, 1)
        self.ftc_split_line = QFrame()
        self.ftc_split_line.setObjectName("FTCStraightDivider")
        self._ftc_top_layout.addWidget(self.ftc_split_line, 0)
        self._ftc_top_layout.addWidget(self.upload_gallery, 1)
        files_layout.addWidget(top_host)

        instructions_surface = QFrame()
        instructions_surface.setObjectName("FTCInstructionsSurface")
        polish_surface(instructions_surface)
        self._apply_soft_shadow(instructions_surface, blur=24, alpha=20, y_offset=7)
        instructions_layout = QVBoxLayout(instructions_surface)
        instructions_layout.setContentsMargins(18, 18, 18, 18)
        instructions_layout.setSpacing(12)

        instructions_head = QHBoxLayout()
        instructions_head.setSpacing(10)
        instructions_title = QLabel("Custom instructions")
        instructions_title.setObjectName("SectionTitle")
        instructions_title.setStyleSheet("color: #728292;")
        instructions_head.addWidget(instructions_title)
        instructions_head.addStretch(1)
        self.instructions_count = QLabel("0 / 180")
        self.instructions_count.setObjectName("SmallMeta")
        instructions_head.addWidget(self.instructions_count)
        instructions_layout.addLayout(instructions_head)

        instructions_hint = QLabel("The app's FTC instruction stays protected. Add anything extra below it.")
        instructions_hint.setObjectName("SmallMeta")
        instructions_hint.setWordWrap(True)
        instructions_layout.addWidget(instructions_hint)

        self.instructions_edit = ProtectedInstructionEdit(180)
        self.instructions_edit.setMinimumHeight(132)
        self.instructions_edit.setMaximumHeight(180)
        self.instructions_edit.limited_text_changed.connect(self._on_instructions_changed)
        instructions_layout.addWidget(self.instructions_edit)
        files_layout.addWidget(instructions_surface)

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
        self._refresh_files_to_cards_state()
        QTimer.singleShot(0, self._apply_responsive_ftc_layout)

    def _apply_responsive_ftc_layout(self) -> None:
        controls_width = self.width()
        compact = controls_width < 980
        ultra_compact = controls_width < 760

        if compact:
            self._ftc_top_layout.setDirection(QBoxLayout.Direction.TopToBottom)
            self.ftc_split_line.setFixedHeight(1)
            self.ftc_split_line.setMinimumWidth(0)
            self.ftc_split_line.setMaximumWidth(16777215)
        else:
            self._ftc_top_layout.setDirection(QBoxLayout.Direction.LeftToRight)
            self.ftc_split_line.setFixedWidth(1)
            self.ftc_split_line.setMinimumHeight(0)
            self.ftc_split_line.setMaximumHeight(16777215)

        self.ftc_menu_btn.setFixedSize(48 if ultra_compact else 52, 48 if ultra_compact else 52)
        self.generate_btn.setMinimumHeight(48 if ultra_compact else 52)
        self.instructions_edit.setMinimumHeight(118 if ultra_compact else 132)
        self.instructions_edit.setMaximumHeight(168 if ultra_compact else 180)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_responsive_ftc_layout()

    def _load_ftc_defaults(self) -> dict:
        setup = self.datastore.load_setup()
        ftc = dict(setup.get("ftc", {}))
        ai_settings = self.datastore.load_ai_settings()
        standard_default = int(ftc.get("question_count_standard", 4) or 4)
        force_default = int(ftc.get("question_count_force", 8) or 8)
        return {
            "default_mode": str(ftc.get("default_mode", "standard")),
            "question_count_standard": max(1, standard_default),
            "question_count_force": max(1, force_default),
            "difficulty": str(ftc.get("difficulty", "normal")).strip().lower(),
            "use_ocr": bool(ftc.get("use_ocr", ai_settings.get("files_to_cards_ocr", True))),
        }

    def _build_ftc_default_instruction(self, difficulty: str) -> str:
        profile = self.datastore.load_profile()
        grade = str(profile.get("grade", "")).strip()
        age = str(profile.get("age", "")).strip()
        difficulty_map = {
            "easy": "Easy difficulty",
            "kinda easy": "Kinda easy difficulty",
            "normal": "Average difficulty",
            "kinda difficult": "Kinda difficult difficulty",
            "difficult": "Difficult",
        }
        prefix = difficulty_map.get(difficulty, "Average difficulty")
        audience = []
        if age:
            audience.append(f"age {age}")
        if grade:
            audience.append(grade)
        if audience:
            return f"{prefix} set of questions per {' and '.join(audience)}."
        return f"{prefix} set of questions per the learner."

    def refresh_ftc_defaults(self, *, force: bool = False) -> None:
        self._ftc_defaults = self._load_ftc_defaults()
        self.use_ocr = bool(self._ftc_defaults.get("use_ocr", True))
        self._ftc_question_preferences.setdefault("standard", int(self._ftc_defaults.get("question_count_standard", 4)))
        self._ftc_question_preferences.setdefault("force", int(self._ftc_defaults.get("question_count_force", 8)))
        default_mode = str(self._ftc_defaults.get("default_mode", "standard"))
        if force or (not self.selected_source_files and not self.ftc_run):
            mode_index = self.mode_combo.findData(default_mode)
            if mode_index >= 0:
                self.mode_combo.setCurrentIndex(mode_index)
                self._last_ftc_mode = default_mode
        default_instruction = self._build_ftc_default_instruction(
            str(self._ftc_defaults.get("difficulty", "normal")).strip().lower()
        )
        self.instructions_edit.set_locked_prefix(default_instruction)
        self._ftc_default_instruction = default_instruction
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
        self._play_sound("click")
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
        model_spec = self._active_text_llm_spec()
        if not self.preflight.require_model(model_spec.key, parent=self, feature_name="Card generation"):
            return

        self.active_job = self.pending_jobs.pop(0)
        question = self.active_job["question"]
        item = self.active_job["item"]
        item.setText(f"Saving  |  {self._short_label(question)}")
        self._add_activity(kind="status", title="Queue", text=f"Saving question: {self._short_label(question)}")

        self.autofill_worker = AutofillWorker(
            question,
            self.ollama,
            model=self._active_text_model_tag(),
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

    def _question_cap_for_mode(self, mode: str, total_units: int | None = None) -> int:
        units = sum(source.unit_count for source in self.selected_source_files) if total_units is None else total_units
        return files_to_cards_question_cap(units, mode)

    def _default_question_count_for_mode(self, mode: str) -> int:
        if mode == "force":
            return int(self._ftc_defaults.get("question_count_force", 8))
        return int(self._ftc_defaults.get("question_count_standard", 4))

    def _preferred_question_count_for_mode(self, mode: str) -> int:
        fallback = self._default_question_count_for_mode(mode)
        return max(1, int(self._ftc_question_preferences.get(mode, fallback)))

    def _ftc_hint_text(self, family: str | None) -> str:
        if family == "pdf":
            return "PDF mode is active. Additional imports stay PDF-only."
        if family == "pptx":
            return "PPTX mode is active. Additional imports stay PPTX-only."
        if family == "images":
            return "Image mode is active. You can mix PNG, JPG, JPEG, WEBP, BMP, and TIFF."
        return "Supports images, PDF, and PPTX."

    def _sync_ftc_summary(self) -> None:
        mode_text = str(self.mode_combo.currentText() or "Standard").strip() or "Standard"
        self.ftc_mode_value.setText(
            f'<span style="font-weight:400; color:#657688;">Mode:</span> <span style="font-weight:800; color:#122131;">{mode_text}</span>'
        )
        if self.selected_source_files:
            question_value = int(self.question_count.value() or self._preferred_question_count_for_mode(self._current_mode()))
        else:
            question_value = self._preferred_question_count_for_mode(self._current_mode())
        self.ftc_questions_value.setText(
            f'<span style="font-weight:400; color:#657688;">Questions:</span> <span style="font-weight:800; color:#122131;">{question_value}</span>'
        )

    def _open_ftc_controls_dialog(self) -> None:
        if self.ftc_run is not None:
            return
        total_units = sum(source.unit_count for source in self.selected_source_files)
        parent_window = self.window()
        blur_target = getattr(parent_window, "_app_shell", parent_window)
        model_spec = self._active_text_llm_spec()
        popup = FTCControlsDialog(
            parent=parent_window if isinstance(parent_window, QWidget) else self,
            blur_target=blur_target if isinstance(blur_target, QWidget) else self,
            current_mode=self._current_mode(),
            question_value=int(self.question_count.value() or self._default_question_count_for_mode(self._current_mode())),
            question_caps={
                "standard": self._question_cap_for_mode("standard", total_units),
                "force": self._question_cap_for_mode("force", total_units),
            },
            default_counts={
                "standard": self._default_question_count_for_mode("standard"),
                "force": self._default_question_count_for_mode("force"),
            },
            model_label=model_spec.display_name,
        )
        result = popup.exec_with_backdrop()
        if result == QDialog.DialogCode.Accepted:
            self._on_ftc_popup_mode_changed(popup.current_mode())
            self._on_ftc_popup_question_changed(popup.current_question_count())

    def _on_ftc_popup_mode_changed(self, mode: str) -> None:
        index = self.mode_combo.findData(mode)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)

    def _on_ftc_popup_question_changed(self, value: int) -> None:
        mode = self._current_mode()
        self._ftc_question_preferences[mode] = int(value)
        self.question_count.blockSignals(True)
        if self.selected_source_files:
            self.question_count.setValue(int(value))
        else:
            self.question_count.setMinimum(int(value))
            self.question_count.setMaximum(int(value))
            self.question_count.setValue(int(value))
        self.question_count.blockSignals(False)
        self._sync_ftc_summary()

    def _on_ftc_action_pressed(self) -> None:
        if self.ftc_run is None:
            self._start_files_to_cards()
            return
        self._stop_files_to_cards()

    def _stash_and_clear_ftc_sources(self) -> None:
        if self.selected_source_files:
            self._ftc_stashed_source_files = list(self.selected_source_files)
            self.selected_source_files = []

    def _restore_stashed_ftc_sources(self) -> None:
        if not self._ftc_stashed_source_files:
            return
        self.selected_source_files = list(self._ftc_stashed_source_files)
        self._ftc_stashed_source_files = []

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
        if self.ftc_run is not None:
            return
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
        self._refresh_files_to_cards_state()

    def _remove_source_file(self, path_str: str) -> None:
        if self.ftc_run is not None:
            return
        self.selected_source_files = [source for source in self.selected_source_files if str(source.path) != path_str]
        self._refresh_files_to_cards_state()

    def _refresh_files_to_cards_state(self) -> None:
        family = self._current_source_family()
        total_units = sum(source.unit_count for source in self.selected_source_files)
        mode = self._current_mode()
        limit = files_to_cards_limit(mode)
        question_cap = files_to_cards_question_cap(total_units, mode)
        locked = self.ftc_run is not None

        if total_units == 0:
            summary_text = "No files selected yet."
        else:
            summary_text = f"Selected units: {total_units} / {limit}  |  Max questions now: {question_cap}"
        self.upload_gallery.set_summary(summary_text, self._ftc_hint_text(family))
        self.upload_gallery.set_sources(self.selected_source_files)

        self.question_count.setEnabled(total_units > 0 and not locked)
        default_question_count = self._preferred_question_count_for_mode(mode)
        if question_cap:
            self.question_count.setMaximum(max(question_cap, 0))
            self.question_count.setMinimum(1)
            if self.question_count.value() == 0 or mode != self._last_ftc_mode:
                self.question_count.setValue(min(default_question_count, question_cap))
            if self.question_count.value() > question_cap:
                self.question_count.setValue(question_cap)
        else:
            self.question_count.setMinimum(default_question_count)
            self.question_count.setMaximum(default_question_count)
            self.question_count.setValue(default_question_count)
        self._last_ftc_mode = mode

        can_generate = total_units > 0 and total_units <= limit and question_cap > 0 and not locked
        self.generate_btn.setEnabled(locked or can_generate)
        self.generate_btn.setText("Stop" if locked else "Generate")
        target_name = "PrimaryButton" if locked else "FTCGenerateButton"
        if self.generate_btn.objectName() != target_name:
            self.generate_btn.setObjectName(target_name)
            self.generate_btn.style().unpolish(self.generate_btn)
            self.generate_btn.style().polish(self.generate_btn)
            self.generate_btn.update()
        self.mode_combo.setEnabled(not locked)
        self.instructions_edit.setReadOnly(locked)
        self.instructions_edit.setEnabled(not locked)
        self.upload_gallery.set_locked(locked)
        self.ftc_menu_btn.setEnabled(not locked)
        self._sync_ftc_summary()

    def _on_instructions_changed(self, text: str) -> None:
        self.instructions_count.setText(f"{len(text)} / 180")

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
        close_btn = AnimatedButton("Close")
        close_btn.clicked.connect(dialog.accept)

        layout.addWidget(preview_area, 1)
        layout.addWidget(meta)
        layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignRight)
        dialog.exec()

    def _start_files_to_cards(self) -> None:
        if not self.selected_source_files or self.ftc_run is not None:
            return
        model_spec = self._active_text_llm_spec()
        if not self.preflight.require_model(model_spec.key, parent=self, feature_name="Files To Cards"):
            return

        active_sources = list(self.selected_source_files)
        active_mode = self._current_mode()
        active_family = self._current_source_family() or "images"
        total_units = sum(source.unit_count for source in active_sources)
        limit = files_to_cards_limit(active_mode)
        if total_units <= 0 or total_units > limit:
            return

        self._play_sound("click")
        run_id = str(uuid.uuid4())
        self.ftc_run = FilesToCardsRunState(run_id=run_id, phase="generating", question_entries=[])
        self._add_activity(kind="status", title="Files To Cards", text="Started a new Files To Cards run.")
        self.use_ocr = bool(self._load_ftc_defaults().get("use_ocr", True))
        background_workers = max(1, min(8, int(self.datastore.load_setup().get("performance", {}).get("background_workers", 2) or 2)))

        job = FilesToCardsJob(
            run_id=run_id,
            mode=active_mode,
            source_family=active_family,
            file_paths=[source.path for source in active_sources],
            requested_questions=self.question_count.value(),
            custom_instructions=self.instructions_edit.combined_text().strip(),
            use_ocr=self.use_ocr,
            background_workers=background_workers,
            text_model_tag=self._active_text_model_tag(),
            text_model_label=model_spec.display_name,
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
        self._stash_and_clear_ftc_sources()
        self._refresh_files_to_cards_state()

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
        self._restore_stashed_ftc_sources()
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
            self._restore_stashed_ftc_sources()
        elif self.ftc_run.phase == "autofill":
            self._add_activity(kind="status", title="Files To Cards", text="Files To Cards finished successfully.")
            self.ftc_completed.emit(self._dominant_run_subject(run_id))
            self._ftc_stashed_source_files = []
        else:
            self._restore_stashed_ftc_sources()

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

    def _dominant_run_subject(self, run_id: str) -> str:
        counts: dict[str, int] = {}
        for card in self.datastore.list_all_cards():
            if str(card.get("run_id", "")).strip() != run_id:
                continue
            subject = str(card.get("subject", "")).strip()
            if not subject:
                continue
            counts[subject] = counts.get(subject, 0) + 1
        if not counts:
            return "study"
        return max(counts.items(), key=lambda item: (item[1], item[0]))[0]

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
        if not self.preflight.semantic_search_available():
            self.pending_embedding_cards.clear()
            return
        background_workers = max(
            1,
            min(8, int(self.datastore.load_setup().get("performance", {}).get("background_workers", 2) or 2)),
        )
        batch_size = max(2, min(24, background_workers * 6))
        batch = self.pending_embedding_cards[:batch_size]
        self.pending_embedding_cards = self.pending_embedding_cards[batch_size:]
        self.embedding_worker = EmbeddingWorker(cards=batch, embedding_service=self.embedding_service)
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
