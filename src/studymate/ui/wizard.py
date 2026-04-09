from __future__ import annotations

from dataclasses import dataclass
import html
from pathlib import Path
import re
import shutil
import sys
import webbrowser

from PySide6.QtCore import QEasingCurve, QPoint, QRect, QRegularExpression, QSize, Qt, QTimer, Signal, QVariantAnimation
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsBlurEffect,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QSlider,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
import psutil

from studymate.services.account_archive_service import AccountArchiveService
from studymate.services.data_store import DataStore
from studymate.services.model_registry import MODELS, recommended_models_for_ram, required_models_for_ram, total_selected_size_gb
from studymate.services.ollama_service import OllamaService
from studymate.ui.animated import AnimatedButton, AnimatedComboBox, AnimatedLineEdit, AnimatedStackedWidget, polish_surface
from studymate.ui.audio import UiSoundBank
from studymate.ui.banner_widget import BannerWidget
from studymate.ui.icon_helper import IconHelper
from studymate.ui.window_effects import polish_windows_window
from studymate.workers.install_worker import ModelInstallWorker
from studymate.workers.performance_worker import PerformanceWorker


def _ram_gb() -> int:
    return int(round(psutil.virtual_memory().total / (1024**3)))


@dataclass
class SetupState:
    ram_gb: int = 0
    advanced_installation: bool = False
    selected_models: list[str] | None = None
    installed_models: dict | None = None
    performance_arena: dict | None = None


def _normalized_import_profile_payload(*, inspection, archive_file: str, archive_age_grade_pattern: re.Pattern[str]) -> dict:
    manifest = inspection.manifest if isinstance(inspection.manifest, dict) else {}
    raw_profile = inspection.profile if isinstance(inspection.profile, dict) else {}
    manifest_profile = manifest.get("profile", {}) if isinstance(manifest.get("profile", {}), dict) else {}
    setup_payload = manifest.get("setup", {}) if isinstance(manifest.get("setup", {}), dict) else {}

    sources = [raw_profile, manifest_profile, setup_payload, manifest]

    def _first_text(keys: tuple[str, ...]) -> str:
        for source in sources:
            for key in keys:
                value = source.get(key, None)
                if value is None:
                    continue
                text = str(value).strip()
                if text:
                    return text
        return ""

    def _first_int(keys: tuple[str, ...]) -> int | None:
        for source in sources:
            for key in keys:
                value = source.get(key, None)
                if value is None:
                    continue
                try:
                    return int(str(value).strip())
                except ValueError:
                    continue
        return None

    name = _first_text(("name", "user_name", "username", "student_name", "account_name"))
    if not name:
        name = str(manifest.get("account_name", "")).strip()
    profile_name = _first_text(("profile_name", "display_name", "nickname"))
    if not profile_name:
        profile_name = name

    archive_match = archive_age_grade_pattern.search(str(archive_file).strip())
    age_from_filename = int(archive_match.group("age")) if archive_match else None
    grade_from_filename = int(archive_match.group("grade")) if archive_match else None

    age_number = _first_int(("age", "user_age", "student_age"))
    if age_number is None:
        age_number = age_from_filename
    if age_number is None:
        age_text = ""
    else:
        age_text = str(max(4, min(age_number, 99)))

    grade_text = _first_text(("grade", "class_grade", "school_grade", "class", "year"))
    if not grade_text and grade_from_filename is not None:
        grade_text = f"Grade {grade_from_filename}"
    if grade_text:
        digits = "".join(ch for ch in grade_text if ch.isdigit())
        if digits:
            grade_text = f"Grade {digits[:2]}"

    gender_text = _first_text(("gender", "sex", "user_gender"))
    hobbies_text = _first_text(("hobbies", "hobby", "interests", "about", "bio"))
    focus_value = _first_int(("attention_span_minutes", "question_focus_level", "attention", "focus_minutes", "focus_time"))
    if focus_value is None:
        focus_value = 5
    focus_value = max(1, min(focus_value, 10))

    return {
        "name": name,
        "profile_name": profile_name,
        "age": age_text,
        "grade": grade_text,
        "gender": gender_text,
        "hobbies": hobbies_text,
        "attention_span_minutes": focus_value,
        "question_focus_level": focus_value,
    }


class OnboardingPage(QWidget):
    changed = Signal()

    def __init__(self, *, title: str, body: str, banner_path: Path, banner_name: str) -> None:
        super().__init__()
        self.setObjectName("OnboardingPage")
        self._banner = BannerWidget(banner_path=banner_path, placeholder_text=banner_name, height=196, radius=26)
        self._body_layout = QVBoxLayout()
        self._body_layout.setSpacing(12)

        title_label = QLabel(title)
        title_label.setObjectName("PageTitle")
        title_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        body_label = QLabel(body)
        body_label.setObjectName("SectionText")
        body_label.setWordWrap(True)
        body_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        has_body = bool(body.strip())
        root.setSpacing(8 if not has_body else 12)
        root.addWidget(title_label)
        if has_body:
            root.addWidget(body_label)
        root.addWidget(self._banner, 0, Qt.AlignHCenter)
        root.addLayout(self._body_layout, 1)

    def body_layout(self) -> QVBoxLayout:
        return self._body_layout

    def can_continue(self) -> bool:
        return True

    def on_enter(self) -> None:
        pass


class FieldBlock(QWidget):
    def __init__(self, title: str, widget: QWidget) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        has_title = bool(str(title).strip())
        layout.setSpacing(6 if has_title else 0)
        if has_title:
            title_label = QLabel(title)
            title_label.setObjectName("SectionTitle")
            layout.addWidget(title_label)
        layout.addWidget(widget)


class FadingIconButton(AnimatedButton):
    def __init__(
        self,
        *,
        icon_path: Path,
        tooltip: str,
        button_size: int = 36,
        icon_size: int = 14,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._hover_fill = 0.0
        self._press_fill = 0.0
        self.setProperty("disablePressMotion", True)
        self.setObjectName("WizardIconButton")
        self.setText("")
        self.setIcon(QIcon(str(icon_path)))
        self.setIconSize(QSize(icon_size, icon_size))
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(button_size, button_size)
        self.setStyleSheet(
            """
            QPushButton#WizardIconButton {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 12px;
                padding: 0px;
            }
            QPushButton#WizardIconButton:disabled {
                background: transparent;
                border: 1px solid transparent;
            }
            """
        )

        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(180)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._hover_anim.valueChanged.connect(self._set_hover_fill)

        self._press_anim = QVariantAnimation(self)
        self._press_anim.setDuration(110)
        self._press_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._press_anim.valueChanged.connect(self._set_press_fill)

    def _set_hover_fill(self, value) -> None:
        self._hover_fill = float(value)
        self.update()

    def _set_press_fill(self, value) -> None:
        self._press_fill = float(value)
        self.update()

    def _animate_fill(self, animation: QVariantAnimation, target: float) -> None:
        animation.stop()
        current = float(animation.currentValue()) if animation.currentValue() is not None else (
            self._hover_fill if animation is self._hover_anim else self._press_fill
        )
        animation.setStartValue(current)
        animation.setEndValue(float(target))
        animation.start()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        if self.isEnabled():
            self._animate_fill(self._hover_anim, 1.0)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._animate_fill(self._hover_anim, 0.0)
        self._animate_fill(self._press_anim, 0.0)

    def mousePressEvent(self, event) -> None:
        if self.isEnabled():
            self._animate_fill(self._press_anim, 1.0)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        self._animate_fill(self._press_anim, 0.0)

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        if not enabled:
            self._hover_fill = 0.0
            self._press_fill = 0.0
            self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self.isEnabled():
            return
        fill_strength = max(self._hover_fill * 0.42, self._press_fill * 0.72)
        if fill_strength <= 0.001:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(19, 49, 75, int(255 * min(0.22, fill_strength))))
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.drawRoundedRect(rect, 12, 12)


class PlaceholderComboBox(AnimatedComboBox):
    def __init__(self, placeholder: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._placeholder = placeholder
        self._popup_handler = None
        self.setPlaceholderText(placeholder)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#8f9dad"))
        self.setPalette(palette)
        self.setCurrentIndex(-1)

    def set_popup_handler(self, handler) -> None:
        self._popup_handler = handler

    def showPopup(self) -> None:
        if callable(self._popup_handler):
            self._popup_handler()
            return
        super().showPopup()


class PrefixedHobbyLineEdit(AnimatedLineEdit):
    def __init__(self, *, prefix: str = "I like ", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._prefix = prefix
        self._syncing_prefix = False
        self._intro_running = False
        self.textChanged.connect(self._enforce_prefix)

        self._intro_anim = QVariantAnimation(self)
        self._intro_anim.setDuration(850)
        self._intro_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._intro_anim.valueChanged.connect(self._on_intro_progress)
        self._intro_anim.finished.connect(self._on_intro_finished)

    def _prefix_len(self) -> int:
        return len(self._prefix)

    def _with_sync(self, fn) -> None:
        if self._syncing_prefix:
            return
        self._syncing_prefix = True
        try:
            fn()
        finally:
            self._syncing_prefix = False

    def _on_intro_progress(self, value) -> None:
        progress = float(value)
        count = int(round(progress * self._prefix_len()))
        alpha = max(0.0, min(1.0, progress))

        def _apply() -> None:
            self.setText(self._prefix[:count])
            self.setCursorPosition(len(self.text()))
            self.setStyleSheet(f"QLineEdit {{ color: rgba(22, 32, 43, {int(255 * alpha)}); }}")

        self._with_sync(_apply)

    def _on_intro_finished(self) -> None:
        self._intro_running = False

        def _apply() -> None:
            self.setReadOnly(False)
            self.setText(self._prefix)
            self.setCursorPosition(self._prefix_len())
            self.setStyleSheet("")

        self._with_sync(_apply)

    def _start_intro_if_needed(self) -> None:
        if self._intro_running or self.text().strip():
            return
        self._intro_running = True
        self.setReadOnly(True)
        self._intro_anim.stop()
        self._intro_anim.setStartValue(0.0)
        self._intro_anim.setEndValue(1.0)
        self._intro_anim.start()

    def _apply_prefix_now(self) -> None:
        if self.text().startswith(self._prefix):
            if self.cursorPosition() < self._prefix_len():
                self.setCursorPosition(self._prefix_len())
            return

        def _apply() -> None:
            current = self.text().strip()
            self.setText(f"{self._prefix}{current}" if current else self._prefix)
            self.setCursorPosition(max(self._prefix_len(), len(self.text())))

        self._with_sync(_apply)

    def _enforce_prefix(self, _text: str) -> None:
        if self._syncing_prefix or not self.hasFocus():
            return
        if self._intro_running:
            return
        self._apply_prefix_now()

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        if not self.text().strip():
            self._start_intro_if_needed()
        else:
            self._apply_prefix_now()

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if self.cursorPosition() < self._prefix_len():
            self.setCursorPosition(self._prefix_len())

    def keyPressEvent(self, event) -> None:
        if self._intro_running:
            event.ignore()
            return
        key = event.key()
        has_selection = self.hasSelectedText()
        selection_start = self.selectionStart()
        if key == Qt.Key.Key_Backspace:
            if (has_selection and selection_start < self._prefix_len()) or (
                not has_selection and self.cursorPosition() <= self._prefix_len()
            ):
                return
        if key == Qt.Key.Key_Delete:
            if (has_selection and selection_start < self._prefix_len()) or (
                not has_selection and self.cursorPosition() < self._prefix_len()
            ):
                return
        if key == Qt.Key.Key_Home:
            self.setCursorPosition(self._prefix_len())
            return
        if key == Qt.Key.Key_Left and not has_selection and self.cursorPosition() <= self._prefix_len():
            return
        super().keyPressEvent(event)
        if self.cursorPosition() < self._prefix_len():
            self.setCursorPosition(self._prefix_len())


class StartupPopupDialog(QDialog):
    def __init__(
        self,
        *,
        parent: QWidget,
        blur_target: QWidget | None = None,
        message: str,
        buttons: list[str],
        default_button: str | None = None,
    ) -> None:
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._choice = ""
        self._blur_target = blur_target or parent
        self._overlay_target = parent
        self._overlay: QWidget | None = None
        self._previous_effect = None
        self._applied_blur: QGraphicsBlurEffect | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(44, 44, 44, 44)
        root.setSpacing(0)

        card = QFrame(self)
        card.setObjectName("StartupPopupCard")
        card.setStyleSheet(
            """
            QFrame#StartupPopupCard {
                background: rgba(255, 255, 255, 0.96);
                border: 1px solid rgba(220, 228, 236, 0.85);
                border-radius: 28px;
            }
            """
        )
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(44)
        shadow.setOffset(0, 0)
        shadow.setColor(QColor(13, 26, 39, 110))
        card.setGraphicsEffect(shadow)
        root.addWidget(card)

        body = QVBoxLayout(card)
        body.setContentsMargins(22, 20, 22, 18)
        body.setSpacing(14)

        message_label = QLabel(message)
        message_label.setWordWrap(True)
        message_label.setObjectName("SectionText")
        body.addWidget(message_label)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        for label in buttons:
            button = AnimatedButton(label)
            button.setProperty("disablePressMotion", True)
            if default_button and label == default_button:
                button.setObjectName("PrimaryButton")
            button.clicked.connect(lambda _checked=False, value=label: self._on_choice(value))
            actions.addWidget(button)
        body.addLayout(actions)

        self.setFixedSize(760, 300)

    def _on_choice(self, value: str) -> None:
        self._choice = value
        self.accept()

    def exec_with_backdrop(self) -> str:
        self._apply_backdrop()
        try:
            self._center_on_parent()
            self.exec()
            return self._choice
        finally:
            self._clear_backdrop()

    def _center_on_parent(self) -> None:
        parent_widget = self.parentWidget()
        if parent_widget is None:
            return
        parent_rect = parent_widget.frameGeometry()
        self.move(
            int(parent_rect.center().x() - (self.width() / 2)),
            int(parent_rect.center().y() - (self.height() / 2)),
        )

    def _apply_backdrop(self) -> None:
        if self._blur_target is None:
            return
        self._previous_effect = self._blur_target.graphicsEffect()
        blur = QGraphicsBlurEffect(self._blur_target)
        blur.setBlurRadius(8.0)
        self._blur_target.setGraphicsEffect(blur)
        self._applied_blur = blur

        overlay = QWidget(self._overlay_target)
        overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
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
        self._applied_blur = None
        self._previous_effect = None


class GradePickerDialog(QDialog):
    def __init__(
        self,
        *,
        parent: QWidget,
        blur_target: QWidget | None,
        anchor: QWidget,
        options: list[str],
        current_value: str = "",
    ) -> None:
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._choice = ""
        self._blur_target = blur_target or parent
        self._overlay_target = parent
        self._anchor = anchor
        self._overlay: QWidget | None = None
        self._previous_effect = None
        self._applied_blur: QGraphicsBlurEffect | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(0)

        card = QFrame(self)
        card.setObjectName("GradePickerCard")
        card.setStyleSheet(
            """
            QFrame#GradePickerCard {
                background: rgba(255, 255, 255, 0.96);
                border: 1px solid rgba(216, 225, 234, 0.88);
                border-radius: 30px;
            }
            QLabel#GradePickerTitle {
                color: #142130;
                font-family: "Nunito Sans", "Segoe UI Variable Display", "Segoe UI", sans-serif;
                font-size: 17px;
                font-weight: 800;
            }
            QLabel#GradePickerMeta {
                color: #6d7c8b;
                font-size: 12px;
            }
            QPushButton#GradePickerOption {
                background: rgba(246, 250, 253, 0.98);
                border: 1px solid rgba(205, 218, 230, 0.92);
                border-radius: 15px;
                padding: 8px 12px;
                color: #728292;
                font-size: 13px;
                font-weight: 700;
                text-align: left;
            }
            QPushButton#GradePickerOption:hover {
                background: rgba(237, 244, 250, 0.98);
                border: 1px solid rgba(154, 180, 206, 0.92);
            }
            QPushButton#GradePickerOption[optionSelected="true"] {
                background: rgba(221, 234, 247, 0.98);
                border: 1px solid rgba(121, 160, 199, 0.92);
                color: #4f6477;
            }
            """
        )
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(42)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(13, 26, 39, 78))
        card.setGraphicsEffect(shadow)
        root.addWidget(card)

        body = QVBoxLayout(card)
        body.setContentsMargins(18, 16, 18, 20)
        body.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title = QLabel("Choose your grade")
        title.setObjectName("GradePickerTitle")
        header.addWidget(title)
        header.addStretch(1)

        icon_root = getattr(getattr(parent, "paths", None), "icons", None)
        if isinstance(icon_root, Path):
            close_icon = icon_root / "common" / "cross_two.png"
            self.close_btn = FadingIconButton(
                icon_path=close_icon,
                tooltip="Close",
                button_size=32,
                icon_size=11,
                parent=card,
            )
            self.close_btn.clicked.connect(self.reject)
            header.addWidget(self.close_btn, 0, Qt.AlignTop)

        body.addLayout(header)

        meta = QLabel("Pick the grade that matches your current school level.")
        meta.setObjectName("GradePickerMeta")
        body.addWidget(meta)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        for column in range(5):
            grid.setColumnStretch(column, 1)

        def _button_for(option: str) -> AnimatedButton:
            button = AnimatedButton(option)
            button.setObjectName("GradePickerOption")
            button.setProperty("disablePressMotion", True)
            button.setFixedHeight(40)
            button.setFixedWidth(118)
            button.set_motion_scale_range(0.0)
            button.set_motion_hover_grow(0, 0)
            button.set_motion_lift(0.0)
            button.set_motion_press_scale(0.0)
            button.setProperty("optionSelected", option == current_value)
            button.clicked.connect(lambda _checked=False, value=option: self._on_choice(value))
            return button

        top_row_options = options[:5]
        bottom_row_options = options[5:10]
        for column, option in enumerate(top_row_options):
            grid.addWidget(_button_for(option), 0, column, alignment=Qt.AlignCenter)
        for column, option in enumerate(bottom_row_options):
            grid.addWidget(_button_for(option), 1, column, alignment=Qt.AlignCenter)

        body.addLayout(grid)
        self.setFixedSize(690, 228)

    def _on_choice(self, value: str) -> None:
        self._choice = value
        self.accept()

    def exec_with_backdrop(self) -> str:
        self._apply_backdrop()
        try:
            self._position_below_anchor()
            self.exec()
            return self._choice
        finally:
            self._clear_backdrop()

    def _position_below_anchor(self) -> None:
        parent_widget = self.parentWidget()
        if parent_widget is None:
            return
        parent_rect = parent_widget.frameGeometry()
        x = int(parent_rect.center().x() - (self.width() / 2))
        y = int(parent_rect.center().y() - (self.height() / 2))
        self.move(x, y)

    def _apply_backdrop(self) -> None:
        if self._blur_target is None:
            return
        self._previous_effect = self._blur_target.graphicsEffect()
        blur = QGraphicsBlurEffect(self._blur_target)
        blur.setBlurRadius(8.0)
        self._blur_target.setGraphicsEffect(blur)
        self._applied_blur = blur

        overlay = QWidget(self._overlay_target)
        overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
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
        self._applied_blur = None
        self._previous_effect = None


class GenderPickerDialog(QDialog):
    def __init__(
        self,
        *,
        parent: QWidget,
        blur_target: QWidget | None,
        current_value: str = "",
    ) -> None:
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._blur_target = blur_target or parent
        self._overlay_target = parent
        self._overlay: QWidget | None = None
        self._previous_effect = None
        self._applied_blur: QGraphicsBlurEffect | None = None
        self._choice = ""
        self._selected_preset = ""
        self._fallback_preset = ""

        normalized = current_value.strip()
        lowered = normalized.lower()
        if lowered == "male":
            self._selected_preset = "Male"
            self._fallback_preset = "Male"
        elif lowered == "female":
            self._selected_preset = "Female"
            self._fallback_preset = "Female"
        else:
            self._choice = normalized

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(0)

        card = QFrame(self)
        card.setObjectName("GenderPickerCard")
        card.setStyleSheet(
            """
            QFrame#GenderPickerCard {
                background: rgba(255, 255, 255, 0.96);
                border: 1px solid rgba(216, 225, 234, 0.88);
                border-radius: 30px;
            }
            QLabel#GenderPickerTitle {
                color: #142130;
                font-family: "Nunito Sans", "Segoe UI Variable Display", "Segoe UI", sans-serif;
                font-size: 17px;
                font-weight: 800;
            }
            QLabel#GenderPickerMeta {
                color: #6d7c8b;
                font-size: 12px;
            }
            QPushButton#GenderPresetOption {
                background: rgba(246, 250, 253, 0.98);
                border: 1px solid rgba(205, 218, 230, 0.92);
                border-radius: 15px;
                padding: 8px 12px;
                color: #142130;
                font-size: 13px;
                font-weight: 700;
                text-align: left;
            }
            QPushButton#GenderPresetOption:hover {
                background: rgba(237, 244, 250, 0.98);
                border: 1px solid rgba(154, 180, 206, 0.92);
            }
            QPushButton#GenderPresetOption[optionSelected="true"] {
                background: rgba(221, 234, 247, 0.98);
                border: 1px solid rgba(121, 160, 199, 0.92);
                color: #102131;
            }
            QLineEdit#GenderCustomInput {
                background: rgba(246, 250, 253, 0.98);
                border: 1px solid rgba(205, 218, 230, 0.92);
                border-radius: 15px;
                padding: 8px 12px;
                color: #142130;
                font-size: 13px;
            }
            QLineEdit#GenderCustomInput:focus {
                background: rgba(252, 254, 255, 0.98);
                border: 1px solid rgba(121, 160, 199, 0.92);
            }
            """
        )
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(42)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(13, 26, 39, 78))
        card.setGraphicsEffect(shadow)
        root.addWidget(card)

        body = QVBoxLayout(card)
        body.setContentsMargins(18, 14, 18, 16)
        body.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title = QLabel("Choose your gender")
        title.setObjectName("GenderPickerTitle")
        header.addWidget(title)
        header.addStretch(1)

        icon_root = getattr(getattr(parent, "paths", None), "icons", None)
        if isinstance(icon_root, Path):
            check_icon = icon_root / "common" / "check.png"
            self.confirm_btn = FadingIconButton(
                icon_path=check_icon,
                tooltip="Apply",
                button_size=32,
                icon_size=11,
                parent=card,
            )
            self.confirm_btn.clicked.connect(self._accept_current_choice)
            header.addWidget(self.confirm_btn, 0, Qt.AlignTop)

            close_icon = icon_root / "common" / "cross_two.png"
            self.close_btn = FadingIconButton(
                icon_path=close_icon,
                tooltip="Close",
                button_size=32,
                icon_size=11,
                parent=card,
            )
            self.close_btn.clicked.connect(self.reject)
            header.addWidget(self.close_btn, 0, Qt.AlignTop)

        body.addLayout(header)

        meta = QLabel("Select one, or write your gender and pronouns below.")
        meta.setObjectName("GenderPickerMeta")
        body.addWidget(meta)

        preset_row = QHBoxLayout()
        preset_row.setContentsMargins(0, 8, 0, 2)
        preset_row.setSpacing(10)

        self.male_btn = AnimatedButton("Male")
        self.male_btn.setObjectName("GenderPresetOption")
        self.male_btn.setProperty("disablePressMotion", True)
        self.male_btn.setFixedHeight(40)
        self.male_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.male_btn.setProperty("optionSelected", self._selected_preset == "Male")
        self.male_btn.set_motion_scale_range(0.0)
        self.male_btn.set_motion_hover_grow(0, 0)
        self.male_btn.set_motion_lift(0.0)
        self.male_btn.set_motion_press_scale(0.0)
        self.male_btn.clicked.connect(lambda: self._select_preset("Male"))

        self.female_btn = AnimatedButton("Female")
        self.female_btn.setObjectName("GenderPresetOption")
        self.female_btn.setProperty("disablePressMotion", True)
        self.female_btn.setFixedHeight(40)
        self.female_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.female_btn.setProperty("optionSelected", self._selected_preset == "Female")
        self.female_btn.set_motion_scale_range(0.0)
        self.female_btn.set_motion_hover_grow(0, 0)
        self.female_btn.set_motion_lift(0.0)
        self.female_btn.set_motion_press_scale(0.0)
        self.female_btn.clicked.connect(lambda: self._select_preset("Female"))

        preset_row.addWidget(self.male_btn)
        preset_row.addWidget(self.female_btn)
        body.addLayout(preset_row)

        self.custom_input = AnimatedLineEdit(card)
        self.custom_input.setObjectName("GenderCustomInput")
        self.custom_input.setPlaceholderText("Gender | Pronoun(s)")
        self.custom_input.setFixedHeight(40)
        self.custom_input.setText(self._choice)
        self.custom_input.textEdited.connect(self._on_custom_text_edited)
        body.addWidget(self.custom_input)

        self.setFixedSize(430, 246)
        self._refresh_selection_state()
        self._refresh_confirm_state()

    def _select_preset(self, value: str) -> None:
        self._selected_preset = value
        self._fallback_preset = value
        self._choice = ""
        self.custom_input.blockSignals(True)
        self.custom_input.clear()
        self.custom_input.blockSignals(False)
        self._refresh_selection_state()
        self._refresh_confirm_state()

    def _on_custom_text_edited(self, text: str) -> None:
        self._choice = text.strip()
        if self._choice:
            self._selected_preset = ""
        self._refresh_selection_state()
        self._refresh_confirm_state()

    def _valid_custom_choice(self) -> str:
        candidate = self.custom_input.text().strip()
        if not candidate:
            return ""
        gender_part, separator, pronoun_part = candidate.partition("|")
        if separator != "|":
            return ""
        gender = gender_part.strip()
        pronouns = pronoun_part.strip()
        if not gender or not pronouns:
            return ""
        return f"{gender} | {pronouns}"

    def _refresh_selection_state(self) -> None:
        self.male_btn.setProperty("optionSelected", self._selected_preset == "Male")
        self.female_btn.setProperty("optionSelected", self._selected_preset == "Female")
        for button in (self.male_btn, self.female_btn):
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()

    def _refresh_confirm_state(self) -> None:
        has_choice = bool(self._valid_custom_choice() or self._selected_preset or self._fallback_preset)
        if hasattr(self, "confirm_btn"):
            self.confirm_btn.setEnabled(has_choice)

    def _accept_current_choice(self) -> None:
        valid_custom = self._valid_custom_choice()
        if valid_custom:
            self._choice = valid_custom
        elif self._selected_preset:
            self._choice = self._selected_preset
        else:
            self._choice = self._fallback_preset
        if not self._choice:
            return
        self.accept()

    def exec_with_backdrop(self) -> str:
        self._apply_backdrop()
        try:
            self._center_on_parent()
            self.exec()
            return self._choice
        finally:
            self._clear_backdrop()

    def _center_on_parent(self) -> None:
        parent_widget = self.parentWidget()
        if parent_widget is None:
            return
        parent_rect = parent_widget.frameGeometry()
        x = int(parent_rect.center().x() - (self.width() / 2))
        y = int(parent_rect.center().y() - (self.height() / 2))
        self.move(x, y)

    def _apply_backdrop(self) -> None:
        if self._blur_target is None:
            return
        self._previous_effect = self._blur_target.graphicsEffect()
        blur = QGraphicsBlurEffect(self._blur_target)
        blur.setBlurRadius(8.0)
        self._blur_target.setGraphicsEffect(blur)
        self._applied_blur = blur

        overlay = QWidget(self._overlay_target)
        overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
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
        self._applied_blur = None
        self._previous_effect = None


class ProfilePage(OnboardingPage):
    import_profile_requested = Signal()
    remove_import_requested = Signal()

    def __init__(
        self,
        banners_root: Path,
        sounds: UiSoundBank | None = None,
        *,
        onboarding_placeholder_tint: bool = False,
    ) -> None:
        super().__init__(
            title="Welcome to ONCard",
            body="",
            banner_path=banners_root / "onboarding_profile_banner_16x9.png",
            banner_name="onboarding_profile_banner_16x9.png",
        )
        self.sounds = sounds
        self._onboarding_placeholder_tint = bool(onboarding_placeholder_tint)
        self._last_attention_value = 5
        self._import_archive_path = ""
        self._imported_profile_active = False
        self._allow_import_removal = True
        self._show_inline_import_control = True
        self._profile_name_auto_sync = True
        self._banner.banner_height = 300
        self._banner.banner_width = int(self._banner.banner_height * (16 / 9))
        self._banner.radius = 30
        self._banner.setFixedSize(self._banner.banner_width, self._banner.banner_height)
        self._banner.update()
        root_layout = self.layout()
        if root_layout is not None:
            root_layout.setSpacing(8)
        self.body_layout().setContentsMargins(0, 22, 0, 0)

        surface = QFrame()
        surface.setObjectName("Surface")
        polish_surface(surface)
        surface_layout = QVBoxLayout(surface)
        surface_layout.setContentsMargins(18, 28, 18, 6)
        surface_layout.setSpacing(0)

        grid_host = QWidget()
        grid_host.setStyleSheet("background: transparent;")
        grid_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        self.name_edit = AnimatedLineEdit()
        self.name_edit.setPlaceholderText("User name")
        self.profile_name_edit = AnimatedLineEdit()
        self.profile_name_edit.setPlaceholderText("Profile name")
        self.age_edit = AnimatedLineEdit()
        self.age_edit.setObjectName("WizardAgeEdit")
        self.age_edit.setPlaceholderText("Age:")
        self.age_edit.setMaxLength(2)
        self.age_edit.setValidator(QRegularExpressionValidator(QRegularExpression("(?:[0-9]|[1-9][0-9])?"), self.age_edit))
        self.grade_combo = PlaceholderComboBox("grade")
        self.grade_combo.setObjectName("WizardGradeCombo")
        self.grade_combo.addItems([f"Grade {value}" for value in range(3, 13)])
        self.grade_combo.setMaxVisibleItems(6)
        self.grade_combo.set_popup_handler(self._open_grade_picker)
        self.gender_combo = PlaceholderComboBox("gender")
        self.gender_combo.setObjectName("WizardGenderCombo")
        self.gender_combo.addItems(["Male", "Female", "Custom"])
        self.gender_combo.setMaxVisibleItems(6)
        self.gender_combo.set_popup_handler(self._open_gender_picker)
        self.gender_custom_edit = AnimatedLineEdit()
        self.gender_custom_edit.setMaxLength(64)
        self.gender_custom_edit.setPlaceholderText("Gender | Pronoun(s)")
        self.gender_custom_edit.setVisible(False)
        self.gender_combo.currentIndexChanged.connect(self._on_gender_mode_changed)
        gender_shell = QWidget()
        gender_shell.setObjectName("WizardGenderShell")
        gender_shell.setStyleSheet("QWidget#WizardGenderShell { background: transparent; }")
        gender_layout = QVBoxLayout(gender_shell)
        gender_layout.setContentsMargins(0, 0, 0, 0)
        gender_layout.setSpacing(6)
        gender_layout.addWidget(self.gender_combo)
        gender_layout.addWidget(self.gender_custom_edit)
        self.hobbies_edit = PrefixedHobbyLineEdit(prefix="I like ")
        self.hobbies_edit.setPlaceholderText("Hobbies / interests")

        self.attention_slider = QSlider(Qt.Horizontal)
        self.attention_slider.setObjectName("WizardAttentionSlider")
        self.attention_slider.setRange(1, 10)
        self.attention_slider.setSingleStep(1)
        self.attention_slider.setPageStep(1)
        self.attention_slider.setValue(5)
        self.attention_slider.setFixedHeight(28)
        self.attention_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.attention_value = QLabel("Attention span per question: 5 min")
        self.attention_value.setObjectName("SectionText")
        self.attention_value.setContentsMargins(0, 0, 0, 0)

        self.name_edit.textChanged.connect(lambda *_: self.changed.emit())
        self.name_edit.textChanged.connect(self._on_name_changed)
        self.name_edit.textEdited.connect(lambda text: self._capitalize_first_letter(self.name_edit, text))
        self.profile_name_edit.textEdited.connect(self._on_profile_name_edited)
        self.profile_name_edit.textEdited.connect(lambda text: self._capitalize_first_letter(self.profile_name_edit, text))
        self.age_edit.textChanged.connect(lambda *_: self.changed.emit())
        self.age_edit.textChanged.connect(lambda *_: self._refresh_age_visual_state())
        self.grade_combo.currentTextChanged.connect(lambda *_: self.changed.emit())
        self.grade_combo.currentIndexChanged.connect(lambda *_: self._refresh_grade_visual_state())
        self.gender_combo.currentTextChanged.connect(lambda *_: self.changed.emit())
        self.gender_combo.currentIndexChanged.connect(lambda *_: self._refresh_gender_visual_state())
        self.gender_custom_edit.textChanged.connect(lambda *_: self.changed.emit())
        self.hobbies_edit.textChanged.connect(lambda *_: self.changed.emit())
        self.attention_slider.valueChanged.connect(self._on_attention_changed)

        for control in (
            self.name_edit,
            self.profile_name_edit,
            self.age_edit,
            self.grade_combo,
            self.gender_combo,
            self.hobbies_edit,
        ):
            control.setFixedHeight(56)
        self.gender_custom_edit.setFixedHeight(56)

        grid.addWidget(FieldBlock("", self.name_edit), 0, 0)
        grid.addWidget(FieldBlock("", self.profile_name_edit), 0, 1)
        grid.addWidget(FieldBlock("", self.age_edit), 1, 0)
        grid.addWidget(FieldBlock("", self.grade_combo), 1, 1)
        grid.addWidget(FieldBlock("", self.hobbies_edit), 2, 0)
        grid.addWidget(FieldBlock("", gender_shell), 2, 1)

        attention_shell = QWidget()
        attention_shell.setStyleSheet("background: transparent;")
        attention_layout = QVBoxLayout(attention_shell)
        attention_layout.setContentsMargins(0, 12, 0, 10)
        attention_layout.setSpacing(6)
        attention_layout.addWidget(self.attention_value, 0, Qt.AlignTop)
        attention_layout.addWidget(self.attention_slider, 0, Qt.AlignTop)
        attention_layout.addStretch(1)
        attention_shell.setFixedHeight(90)
        attention_shell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        grid.addWidget(attention_shell, 3, 0, 1, 2)

        surface_layout.addWidget(grid_host, 0, Qt.AlignTop)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 2, 0, 0)
        controls.setSpacing(8)
        self.import_handshake_btn = FadingIconButton(
            icon_path=(banners_root.parent / "icons" / "common" / "handshake.png"),
            tooltip="Import profile",
            button_size=34,
            icon_size=14,
        )
        self.import_handshake_btn.clicked.connect(self.import_profile_requested.emit)
        self.remove_zip_btn = AnimatedButton("Remove")
        self.remove_zip_btn.setProperty("disablePressMotion", True)
        self.remove_zip_btn.clicked.connect(self.remove_import_requested.emit)
        self.remove_zip_btn.hide()
        controls.addWidget(self.import_handshake_btn, 0, Qt.AlignLeft)
        controls.addWidget(self.remove_zip_btn, 0, Qt.AlignLeft)
        controls.addStretch(1)
        surface_layout.addLayout(controls)

        self._refresh_age_visual_state()
        self._refresh_grade_visual_state()
        self._refresh_gender_visual_state()

        self.body_layout().addWidget(surface, 1)

    def _on_attention_changed(self, value: int) -> None:
        if value != self._last_attention_value and self.sounds is not None:
            self.sounds.play("click", volume_scale=1.25)
        self._last_attention_value = value
        self.attention_value.setText(f"Attention span per question: {value} min")
        self.changed.emit()

    def _on_name_changed(self) -> None:
        if self._profile_name_auto_sync:
            self.profile_name_edit.setText(self.name_edit.text().strip())

    def _capitalize_first_letter(self, widget: AnimatedLineEdit, text: str) -> None:
        if not text:
            return
        trimmed = text.lstrip()
        if not trimmed:
            return
        first = trimmed[0]
        upper_first = first.upper()
        if first == upper_first:
            return
        offset = len(text) - len(trimmed)
        updated = f"{text[:offset]}{upper_first}{trimmed[1:]}"
        cursor = widget.cursorPosition()
        widget.blockSignals(True)
        widget.setText(updated)
        widget.blockSignals(False)
        widget.setCursorPosition(min(cursor, len(updated)))
        if widget is self.name_edit:
            self._on_name_changed()
        self.changed.emit()

    def _on_profile_name_edited(self, text: str) -> None:
        self._profile_name_auto_sync = text.strip() == self.name_edit.text().strip()

    def _on_gender_mode_changed(self) -> None:
        self.gender_custom_edit.setVisible(False)

    def _refresh_age_visual_state(self) -> None:
        is_placeholder = not self.age_edit.text().strip()
        self._set_widget_text_tint(self.age_edit, muted=is_placeholder)

    def _refresh_grade_visual_state(self) -> None:
        self._set_widget_text_tint(
            self.grade_combo,
            muted=self._onboarding_placeholder_tint and self.grade_combo.currentIndex() < 0,
        )
        self.grade_combo.update()

    def _open_grade_picker(self) -> None:
        if not self.grade_combo.isEnabled():
            return
        parent_widget = self.window() if isinstance(self.window(), QWidget) else self
        blur_target = getattr(parent_widget, "_popup_blur_target", parent_widget)
        options = [self.grade_combo.itemText(index) for index in range(self.grade_combo.count())]
        current_value = self.grade_combo.currentText().strip() if self.grade_combo.currentIndex() >= 0 else ""
        selected = GradePickerDialog(
            parent=parent_widget,
            blur_target=blur_target,
            anchor=self.grade_combo,
            options=options,
            current_value=current_value,
        ).exec_with_backdrop()
        if not selected:
            return
        self.grade_combo.setCurrentText(selected)
        self.grade_combo.setFocus()

    def _open_gender_picker(self) -> None:
        if not self.gender_combo.isEnabled():
            return
        parent_widget = self.window() if isinstance(self.window(), QWidget) else self
        blur_target = getattr(parent_widget, "_popup_blur_target", parent_widget)
        current_value = self._effective_gender()
        selected = GenderPickerDialog(
            parent=parent_widget,
            blur_target=blur_target,
            current_value=current_value,
        ).exec_with_backdrop()
        if not selected:
            return
        normalized = selected.strip()
        lowered = normalized.lower()
        if lowered == "male":
            self.gender_combo.setCurrentText("Male")
            self.gender_custom_edit.clear()
        elif lowered == "female":
            self.gender_combo.setCurrentText("Female")
            self.gender_custom_edit.clear()
        else:
            self.gender_combo.setCurrentText("Custom")
            self.gender_custom_edit.setText(normalized[:64])
        self.gender_combo.setFocus()

    def _refresh_gender_visual_state(self) -> None:
        self._set_widget_text_tint(
            self.gender_combo,
            muted=self._onboarding_placeholder_tint and self.gender_combo.currentIndex() < 0,
        )
        self.gender_combo.update()

    def _set_widget_text_tint(self, widget: QWidget, *, muted: bool) -> None:
        color = QColor("#8f9dad") if muted else QColor("#16202b")
        palette = widget.palette()
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            palette.setColor(group, QPalette.ColorRole.Text, color)
            palette.setColor(group, QPalette.ColorRole.ButtonText, color)
            palette.setColor(group, QPalette.ColorRole.WindowText, color)
            palette.setColor(group, QPalette.ColorRole.PlaceholderText, QColor("#8f9dad"))
        widget.setPalette(palette)
        widget.update()

    def _set_gender_from_profile(self, gender_value: str) -> None:
        gender = str(gender_value or "").strip()
        normalized = gender.lower()
        if normalized == "male":
            self.gender_combo.setCurrentText("Male")
            self.gender_custom_edit.clear()
        elif normalized == "female":
            self.gender_combo.setCurrentText("Female")
            self.gender_custom_edit.clear()
        elif gender:
            self.gender_combo.setCurrentText("Custom")
            self.gender_custom_edit.setText(gender[:64])
        else:
            self.gender_combo.setCurrentIndex(-1)
            self.gender_custom_edit.clear()
        self._on_gender_mode_changed()
        self._refresh_gender_visual_state()

    def _effective_gender(self) -> str:
        mode = self.gender_combo.currentText().strip()
        if not mode:
            return ""
        if mode.lower() == "custom":
            return self.gender_custom_edit.text().strip()[:64]
        return mode

    def can_continue(self) -> bool:
        if self._imported_profile_active:
            return True
        if not self.name_edit.text().strip():
            return False
        if not self.profile_name_edit.text().strip():
            return False
        if not self.age_edit.text().strip():
            return False
        if self.grade_combo.currentIndex() < 0:
            return False
        if self.gender_combo.currentIndex() < 0:
            return False
        hobbies_text = self.hobbies_edit.text().strip()
        if hobbies_text.lower().startswith("i like "):
            hobbies_text = hobbies_text[7:].strip()
        if not hobbies_text:
            return False
        if self.gender_combo.currentText().strip().lower() == "custom":
            return bool(self.gender_custom_edit.text().strip())
        return True

    def profile_payload(self) -> dict:
        user_name = self.name_edit.text().strip()
        age_text = self.age_edit.text().strip()
        hobbies_text = self.hobbies_edit.text().strip()
        if hobbies_text.lower().startswith("i like "):
            hobbies_text = hobbies_text[7:].strip()
        return {
            "name": user_name,
            "profile_name": self.profile_name_edit.text().strip() or user_name,
            "age": age_text,
            "grade": "" if self.grade_combo.currentIndex() < 0 else self.grade_combo.currentText(),
            "gender": self._effective_gender(),
            "hobbies": hobbies_text,
            "attention_span_minutes": self.attention_slider.value(),
            "question_focus_level": self.attention_slider.value(),
        }

    def set_imported_profile(self, profile: dict, *, archive_path: str) -> None:
        self._import_archive_path = str(archive_path)
        self._imported_profile_active = True
        imported_name = str(profile.get("name", "")).strip()
        self.name_edit.setText(imported_name)
        self.profile_name_edit.setText(str(profile.get("profile_name", "")).strip() or imported_name)
        self._profile_name_auto_sync = False
        try:
            age = int(str(profile.get("age", "")).strip() or 16)
        except ValueError:
            age = 16
        age = max(0, min(age, 9))
        self.age_edit.setText(str(age) if age > 0 else "")
        self._refresh_age_visual_state()
        grade = str(profile.get("grade", "")).strip()
        if grade:
            self.grade_combo.setCurrentText(grade)
        else:
            self.grade_combo.setCurrentIndex(-1)
        self._refresh_grade_visual_state()
        self._set_gender_from_profile(str(profile.get("gender", "")).strip())
        self.hobbies_edit.setText(str(profile.get("hobbies", "")).strip())
        try:
            attention_value = int(profile.get("attention_span_minutes", profile.get("question_focus_level", 5)) or 5)
        except ValueError:
            attention_value = 5
        attention_value = max(self.attention_slider.minimum(), min(attention_value, self.attention_slider.maximum()))
        self.attention_slider.setValue(attention_value)
        self._set_form_locked(True)
        self.changed.emit()

    def clear_imported_profile(self) -> None:
        self._import_archive_path = ""
        self._imported_profile_active = False
        self._profile_name_auto_sync = True
        self._set_form_locked(False)
        self.changed.emit()

    def imported_archive_path(self) -> str:
        return self._import_archive_path

    def _set_form_locked(self, locked: bool) -> None:
        self.name_edit.setEnabled(not locked)
        self.profile_name_edit.setEnabled(not locked)
        self.age_edit.setEnabled(not locked)
        self.grade_combo.setEnabled(not locked)
        self.gender_combo.setEnabled(not locked)
        self.gender_custom_edit.setEnabled(not locked and self.gender_combo.currentText().strip().lower() == "custom")
        if locked:
            self.gender_custom_edit.setVisible(False)
        else:
            self._on_gender_mode_changed()
        self.hobbies_edit.setEnabled(not locked)
        self.attention_slider.setEnabled(not locked)
        self.import_handshake_btn.setVisible((not locked) and self._show_inline_import_control)
        self.remove_zip_btn.setVisible(locked and self._allow_import_removal)

    def set_allow_import_removal(self, allow: bool) -> None:
        self._allow_import_removal = bool(allow)
        if self._import_archive_path:
            self.remove_zip_btn.setVisible(self._allow_import_removal)

    def set_inline_import_control_visible(self, visible: bool) -> None:
        self._show_inline_import_control = bool(visible)
        self.import_handshake_btn.setVisible(self._show_inline_import_control and not self._imported_profile_active)


class AboutPage(OnboardingPage):
    def __init__(self, banners_root: Path) -> None:
        super().__init__(
            title="A warm hello",
            body="This app stays free, local-first, and built to help without subscriptions or rate limits.",
            banner_path=banners_root / "onboarding_about_banner_16x9.png",
            banner_name="onboarding_about_banner_16x9.png",
        )

        surface = QFrame()
        surface.setObjectName("Surface")
        polish_surface(surface)
        surface.setStyleSheet("QFrame#Surface { border: none; background: transparent; }")
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        for line in [
            "ONCard is a free and open-source study app designed to help you build strong understanding through focused flashcard practice, clear feedback loops, and a workflow that stays simple even as your card library grows.",
            "The app includes AI-assisted tools to speed up drafting, improving, and organizing your study material, while still keeping your learning process in your control so you can adapt every card and session to your own pace.",
            "There are no subscriptions, no hidden unlock tiers, and no artificial limits on your usage. You can keep building your study system without worrying about paywalls, and your feedback directly helps shape future improvements for everyone.",
        ]:
            label = QLabel()
            label.setObjectName("SectionText")
            label.setWordWrap(True)
            label.setTextFormat(Qt.RichText)
            label.setText(f"<div style='text-align: justify;'>{html.escape(line)}</div>")
            label.setAlignment(Qt.AlignTop)
            label.setFixedWidth(500)
            layout.addWidget(label)
            layout.setAlignment(label, Qt.AlignHCenter)

        self.body_layout().addWidget(surface)
        self.body_layout().addStretch(1)


class ModelInstallerPage(OnboardingPage):
    def __init__(self, banners_root: Path, icons: IconHelper, ollama: OllamaService) -> None:
        super().__init__(
            title="Install AI models",
            body="",
            banner_path=banners_root / "onboarding_models_banner_16x9.png",
            banner_name="onboarding_models_banner_16x9.png",
        )
        self.icons = icons
        self.ollama = ollama
        self.ram_gb = _ram_gb()
        self.ollama_installed = shutil.which("ollama") is not None
        self.install_worker: ModelInstallWorker | None = None
        self.installed_models: dict[str, bool] = {}
        self.last_selected: list[str] = []
        self._progress_queue: list[int] = []
        self._progress_busy = False
        self._progress_animation = QVariantAnimation(self)
        self._progress_animation.setDuration(430)
        self._progress_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._progress_animation.valueChanged.connect(
            lambda value: self.progress.setValue(int(round(float(value))))
        )
        self._progress_animation.finished.connect(self._on_progress_animation_finished)

        surface = QFrame()
        surface.setObjectName("Surface")
        polish_surface(surface)
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.size_label = QLabel()
        self.size_label.setObjectName("SectionText")
        self.size_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.ollama_button = AnimatedButton("Open Ollama website")
        self.ollama_button.setProperty("disablePressMotion", True)
        self.ollama_button.clicked.connect(lambda: webbrowser.open("https://ollama.com/download"))
        if self.ollama_installed:
            self.ollama_button.hide()

        self.install_button = AnimatedButton("Install selected models")
        self.install_button.setProperty("disablePressMotion", True)
        self.install_button.setObjectName("WizardActionButton")
        self.install_button.set_motion_scale_range(0.0)
        self.install_button.set_motion_hover_grow(0, 0)
        self.install_button.set_motion_lift(0.0)
        self.install_button.set_motion_press_scale(0.0)
        self.install_button.setMinimumWidth(320)
        self.install_button.setMaximumWidth(360)
        self.install_button.clicked.connect(self._install_models)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.setObjectName("InstallerThinProgress")
        self.progress.setStyleSheet(
            """
            QProgressBar#InstallerThinProgress {
                background: #d4deea;
                border: none;
                border-radius: 4px;
            }
            QProgressBar#InstallerThinProgress::chunk {
                background: #0f2539;
                border-radius: 4px;
            }
            """
        )

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(260)
        self.log.setMaximumHeight(360)
        self.log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.log.setPlaceholderText("")

        layout.addWidget(self.size_label)
        layout.addWidget(self.ollama_button, 0, Qt.AlignHCenter)
        layout.addWidget(self.install_button, 0, Qt.AlignHCenter)
        layout.addWidget(self.progress)
        layout.addWidget(self.log, 1)

        self.body_layout().addWidget(surface)
        self.body_layout().addStretch(1)

        self._apply_recommended_selection()
        self._refresh_copy()

    def _apply_recommended_selection(self) -> None:
        self.last_selected = recommended_models_for_ram(self.ram_gb)
        self._refresh_copy()

    def _refresh_copy(self) -> None:
        selected = self.selected_models()
        size_gb = total_selected_size_gb(selected)
        if self.ram_gb < 7:
            self.install_button.setEnabled(False)
        elif not self.ollama_installed:
            self.install_button.setEnabled(False)
        else:
            self.install_button.setEnabled(True)

        self.size_label.setText(
            f"Selected download size: {size_gb:.1f} GB | Models: Gemma3:4b and Nomic-embed-MoE"
        )
        self.ollama_button.setVisible(not self.ollama_installed)

    def selected_models(self) -> list[str]:
        return list(recommended_models_for_ram(self.ram_gb))

    def _append_log(self, text: str) -> None:
        self.log.append(text)

    def _install_models(self) -> None:
        if self.ram_gb < 7:
            QMessageBox.warning(self, "Requirements", "ONCard needs at least 7GB of RAM.")
            return
        if self.install_worker and self.install_worker.isRunning():
            return

        selected = self.selected_models()
        if not selected:
            QMessageBox.warning(self, "No models selected", "Select at least one model to install.")
            return

        self.last_selected = selected
        self._reset_progress_sequence(0)
        self.log.clear()
        self.install_button.setEnabled(False)

        self.install_worker = ModelInstallWorker(selected, self.ollama)
        self.install_worker.line.connect(self._append_log)
        self.install_worker.model_finished.connect(self._on_model_finished)
        self.install_worker.complete.connect(self._on_install_complete)
        self.install_worker.start()
        self.changed.emit()

    def _on_model_finished(self, key: str, ok: bool, tag: str) -> None:
        self.installed_models[key] = ok
        marker = "OK" if ok else "FAILED"
        self._append_log(f"[{marker}] {MODELS[key].display_name} via {tag}")
        if self.last_selected:
            done = len(self.installed_models.keys())
            progress_value = int((done / len(self.last_selected)) * 100)
            self._enqueue_progress(progress_value)
        self.changed.emit()

    def _on_install_complete(self, _: dict) -> None:
        self.install_button.setEnabled(True)
        self._enqueue_progress(100)
        self.changed.emit()

    def _reset_progress_sequence(self, value: int) -> None:
        self._progress_animation.stop()
        self._progress_queue.clear()
        self._progress_busy = False
        self.progress.setValue(max(0, min(value, 100)))

    def _enqueue_progress(self, target: int) -> None:
        value = max(0, min(int(target), 100))
        if self._progress_queue and self._progress_queue[-1] == value:
            return
        self._progress_queue.append(value)
        self._run_next_progress_step()

    def _run_next_progress_step(self) -> None:
        if self._progress_busy or not self._progress_queue:
            return
        target = self._progress_queue.pop(0)
        current = self.progress.value()
        self._progress_busy = True
        if target == current:
            QTimer.singleShot(1000, self._after_progress_pause)
            return
        self._progress_animation.stop()
        self._progress_animation.setStartValue(current)
        self._progress_animation.setEndValue(target)
        self._progress_animation.start()

    def _on_progress_animation_finished(self) -> None:
        QTimer.singleShot(1000, self._after_progress_pause)

    def _after_progress_pause(self) -> None:
        self._progress_busy = False
        self._run_next_progress_step()

    def can_continue(self) -> bool:
        if self.ram_gb < 7:
            return False
        selected = self.last_selected or self.selected_models()
        if not selected:
            return False
        required = required_models_for_ram(self.ram_gb)
        for key in required:
            if key in selected and not self.installed_models.get(key, False):
                return False
        for key in selected:
            if not self.installed_models.get(key, False):
                return False
        return True

    def setup_payload(self) -> SetupState:
        return SetupState(
            ram_gb=self.ram_gb,
            advanced_installation=False,
            selected_models=self.last_selected or self.selected_models(),
            installed_models=self.installed_models,
        )


class PerformancePage(OnboardingPage):
    def __init__(self, banners_root: Path, ollama: OllamaService) -> None:
        super().__init__(
            title="Test performance",
            body="",
            banner_path=banners_root / "performance_default_banner_16x9.png",
            banner_name="performance_default_banner_16x9.png",
        )
        self.ollama = ollama
        self.worker: PerformanceWorker | None = None
        self.avg_tps: float | None = None
        self.tier = ""
        self._progress_queue: list[int] = []
        self._progress_busy = False
        self._progress_animation = QVariantAnimation(self)
        self._progress_animation.setDuration(420)
        self._progress_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._progress_animation.valueChanged.connect(
            lambda value: self.progress.setValue(int(round(float(value))))
        )
        self._progress_animation.finished.connect(self._on_progress_animation_finished)

        surface = QFrame()
        surface.setObjectName("Surface")
        polish_surface(surface)
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        self.run_button = AnimatedButton("Run 4-question TPS test")
        self.run_button.setProperty("disablePressMotion", True)
        self.run_button.setObjectName("WizardActionButton")
        self.run_button.set_motion_scale_range(0.0)
        self.run_button.set_motion_hover_grow(0, 0)
        self.run_button.set_motion_lift(0.0)
        self.run_button.set_motion_press_scale(0.0)
        self.run_button.setMinimumWidth(320)
        self.run_button.setMaximumWidth(360)
        self.run_button.clicked.connect(self._run_benchmark)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.setObjectName("TesterThinProgress")
        self.progress.setStyleSheet(
            """
            QProgressBar#TesterThinProgress {
                background: rgba(184, 200, 216, 0.45);
                border: none;
                border-radius: 4px;
            }
            QProgressBar#TesterThinProgress::chunk {
                background: #0f2539;
                border-radius: 4px;
            }
            """
        )
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(260)
        self.log.setMaximumHeight(360)
        self.log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.log.setPlaceholderText("")

        layout.addWidget(self.run_button, 0, Qt.AlignHCenter)
        layout.addWidget(self.progress)
        layout.addWidget(self.log, 1)
        self.body_layout().addWidget(surface)
        self.body_layout().addStretch(1)

    def _set_banner_by_tier(self, tier: str) -> None:
        tier_key = "poor"
        if "Best" in tier:
            tier_key = "best"
        elif "Smooth" in tier:
            tier_key = "smooth"
        elif "Normal" in tier:
            tier_key = "normal"
        file_name = f"performance_{tier_key}_banner_16x9.png"
        self._banner.banner_path = self._banner.banner_path.parent / file_name
        self._banner.placeholder_text = file_name
        self._banner.update()

    def _run_benchmark(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        self._reset_progress_sequence(0)
        self.log.clear()
        self.worker = PerformanceWorker(self.ollama)
        self.worker.progress.connect(self.log.append)
        self.worker.sample.connect(self._on_sample)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_sample(self, idx: int, tps: float) -> None:
        self._enqueue_progress(int((max(0, min(idx, 4)) / 4) * 100))
        self.log.append(f"Q{idx}: {tps} TPS")

    def _on_done(self, avg_tps: float, tier: str) -> None:
        self.avg_tps = avg_tps
        self.tier = tier
        self._enqueue_progress(100)
        self._set_banner_by_tier(tier)
        parent_widget = self.window() if isinstance(self.window(), QWidget) else self
        blur_target = getattr(parent_widget, "_popup_blur_target", parent_widget)
        StartupPopupDialog(
            parent=parent_widget,
            blur_target=blur_target,
            message=f"Performance level: {tier}",
            buttons=["Okay"],
            default_button="Okay",
        ).exec_with_backdrop()
        self.changed.emit()

    def _on_failed(self, message: str) -> None:
        self.log.append(message)
        self.changed.emit()

    def _reset_progress_sequence(self, value: int) -> None:
        self._progress_animation.stop()
        self._progress_queue.clear()
        self._progress_busy = False
        self.progress.setValue(max(0, min(value, 100)))

    def _enqueue_progress(self, target: int) -> None:
        value = max(0, min(int(target), 100))
        if self._progress_queue and self._progress_queue[-1] == value:
            return
        self._progress_queue.append(value)
        self._run_next_progress_step()

    def _run_next_progress_step(self) -> None:
        if self._progress_busy or not self._progress_queue:
            return
        target = self._progress_queue.pop(0)
        current = self.progress.value()
        self._progress_busy = True
        if target == current:
            QTimer.singleShot(1000, self._after_progress_pause)
            return
        self._progress_animation.stop()
        self._progress_animation.setStartValue(current)
        self._progress_animation.setEndValue(target)
        self._progress_animation.start()

    def _on_progress_animation_finished(self) -> None:
        QTimer.singleShot(1000, self._after_progress_pause)

    def _after_progress_pause(self) -> None:
        self._progress_busy = False
        self._run_next_progress_step()

    def performance_payload(self) -> dict:
        if self.avg_tps is None:
            return {"skipped": False, "avg_tps": None, "tier": ""}
        return {"skipped": False, "avg_tps": self.avg_tps, "tier": self.tier}

    def can_continue(self) -> bool:
        return self.avg_tps is not None


class QuickStartPage(OnboardingPage):
    def __init__(self, banners_root: Path) -> None:
        super().__init__(
            title="Quick start",
            body="A short guide before you jump in. We hold this page for five seconds so it actually gets read.",
            banner_path=banners_root / "onboarding_quickstart_banner_16x9.png",
            banner_name="onboarding_quickstart_banner_16x9.png",
        )
        self._remaining = 5
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        surface = QFrame()
        surface.setObjectName("Surface")
        polish_surface(surface)
        layout = QVBoxLayout(surface)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        for line in [
            'Press the "Create" button to make your first card. Or write a question and press Autofill for magic.',
            'Then go to "Cards" and either press Start or open the Study subtab after choosing a card.',
            "Good luck with your studies.",
        ]:
            label = QLabel(line)
            label.setObjectName("SectionText")
            label.setWordWrap(True)
            layout.addWidget(label)

        self.timer_label = QLabel("")
        self.timer_label.setObjectName("SectionTitle")
        layout.addWidget(self.timer_label)

        self.body_layout().addWidget(surface)
        self.body_layout().addStretch(1)

    def on_enter(self) -> None:
        self._remaining = 5
        self.timer_label.setText("Please read this page. Finish unlocks in 5s.")
        self._timer.start(1000)
        self.changed.emit()

    def _tick(self) -> None:
        self._remaining -= 1
        if self._remaining <= 0:
            self._timer.stop()
            self.timer_label.setText("You are all set. Press Finish to enter ONCard.")
        else:
            self.timer_label.setText(f"Please read this page. Finish unlocks in {self._remaining}s.")
        self.changed.emit()

    def can_continue(self) -> bool:
        return self._remaining <= 0


class OnboardingWizard(QDialog):
    ARCHIVE_AGE_GRADE_PATTERN = re.compile(r"_A(?P<age>\d{1,2})_G(?P<grade>\d{1,2})\.zip$", re.IGNORECASE)

    def __init__(
        self,
        paths,
        datastore: DataStore,
        ollama: OllamaService,
        icons: IconHelper,
        *,
        archive_service: AccountArchiveService | None = None,
    ) -> None:
        super().__init__()
        self.paths = paths
        self.datastore = datastore
        self.ollama = ollama
        self.icons = icons
        self.archive_service = archive_service
        self.sounds = UiSoundBank(self.paths.assets / "sfx")
        self.current_index = 0
        self.import_archive_path = ""
        self._import_flow_locked = False

        self.setWindowTitle("ONCard Setup")
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, False)
        self.setWindowFlag(Qt.MSWindowsFixedSizeDialogHint, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(1040, 760)
        self.setStyleSheet(
            """
            QFrame#OnboardingWindowShell {
                background: #ffffff;
                border: 1px solid rgba(198, 210, 223, 0.92);
                border-radius: 30px;
            }
            QStackedWidget#OnboardingStack,
            QWidget#OnboardingPage {
                background: transparent;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        shell_surface = QFrame(self)
        shell_surface.setObjectName("OnboardingWindowShell")
        polish_surface(shell_surface)
        self._shell_shadow_effect = None
        if not (sys.platform == "win32" and self.testAttribute(Qt.WA_TranslucentBackground)):
            shell_shadow = QGraphicsDropShadowEffect(shell_surface)
            shell_shadow.setBlurRadius(34)
            shell_shadow.setOffset(0, 10)
            shell_shadow.setColor(QColor(17, 35, 57, 68))
            shell_surface.setGraphicsEffect(shell_shadow)
            self._shell_shadow_effect = shell_shadow
        root.addWidget(shell_surface, 1)

        shell = QVBoxLayout(shell_surface)
        shell.setContentsMargins(18, 14, 18, 14)
        shell.setSpacing(12)
        self._shell_surface = shell_surface
        self.close_btn = FadingIconButton(
            icon_path=self.paths.icons / "common" / "cross_two.png",
            tooltip="Close",
            button_size=34,
            icon_size=12,
            parent=shell_surface,
        )
        self.close_btn.clicked.connect(self.reject)

        blur_layer = QWidget(shell_surface)
        blur_layer.setObjectName("OnboardingBlurLayer")
        blur_layer.setAttribute(Qt.WA_StyledBackground, True)
        blur_layer.setStyleSheet("QWidget#OnboardingBlurLayer { background: transparent; }")
        self._popup_blur_target = blur_layer
        blur_layout = QVBoxLayout(blur_layer)
        blur_layout.setContentsMargins(0, 0, 0, 0)
        blur_layout.setSpacing(12)

        self.stack = AnimatedStackedWidget()
        self.stack.setObjectName("OnboardingStack")
        self.profile_page = ProfilePage(
            self.paths.banners,
            self.sounds,
            onboarding_placeholder_tint=True,
        )
        self.profile_page.set_allow_import_removal(False)
        self.profile_page.set_inline_import_control_visible(False)
        self.about_page = AboutPage(self.paths.banners)
        self.model_page = ModelInstallerPage(self.paths.banners, self.icons, self.ollama)
        self.performance_page = PerformancePage(self.paths.banners, self.ollama)
        self.quickstart_page = QuickStartPage(self.paths.banners)
        self.pages: list[OnboardingPage] = [
            self.profile_page,
            self.about_page,
            self.model_page,
            self.performance_page,
            self.quickstart_page,
        ]
        for page in self.pages:
            page.changed.connect(self._refresh_nav)
            self.stack.addWidget(page)
        self.profile_page.import_profile_requested.connect(self._import_profile_into_profile_page)
        self.profile_page.remove_import_requested.connect(self._remove_imported_profile)
        blur_layout.addWidget(self.stack, 1)

        nav = QHBoxLayout()
        nav.setContentsMargins(0, 8, 8, 4)
        nav.setSpacing(0)
        self.add_profile_btn = FadingIconButton(
            icon_path=self.paths.icons / "common" / "handshake.png",
            tooltip="Add Profile",
            button_size=34,
            icon_size=14,
        )
        self.back_btn = FadingIconButton(
            icon_path=self.paths.icons / "common" / "angle-left.png",
            tooltip="Back",
            button_size=34,
            icon_size=13,
        )
        self.next_btn = FadingIconButton(
            icon_path=self.paths.icons / "common" / "angle-right.png",
            tooltip="Next",
            button_size=34,
            icon_size=13,
        )
        self.finish_btn = FadingIconButton(
            icon_path=self.paths.icons / "common" / "check.png",
            tooltip="Finish",
            button_size=34,
            icon_size=12,
        )
        self.add_profile_btn.clicked.connect(self._import_profile_into_profile_page)
        self.back_btn.clicked.connect(self._go_back)
        self.next_btn.clicked.connect(self._go_next)
        self.finish_btn.clicked.connect(self.accept)
        nav.addStretch(1)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(10)
        action_row.addWidget(self.add_profile_btn)
        action_row.addWidget(self.back_btn)
        action_row.addWidget(self.next_btn)
        action_row.addWidget(self.finish_btn)
        nav.addLayout(action_row)
        blur_layout.addLayout(nav)
        shell.addWidget(blur_layer, 1)
        self._position_close_button()

        polish_windows_window(self, rounded=False, small_corners=False, remove_border=True)
        self._show_page(0)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        polish_windows_window(self, rounded=False, small_corners=False, remove_border=True)
        self._position_close_button()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_close_button()

    def _position_close_button(self) -> None:
        if not hasattr(self, "close_btn") or not hasattr(self, "_shell_surface"):
            return
        margin_right = 18
        margin_top = 14
        x = self._shell_surface.width() - self.close_btn.width() - margin_right
        y = margin_top
        self.close_btn.move(max(0, x), max(0, y))
        self.close_btn.raise_()

    def _show_page(self, index: int) -> None:
        self.current_index = index
        self.stack.setCurrentIndex(index)
        self.pages[index].on_enter()
        self._refresh_nav()

    def _refresh_nav(self) -> None:
        last = self.current_index == len(self.pages) - 1
        current = self.pages[self.current_index]
        model_index = self.pages.index(self.model_page)
        if self._import_flow_locked:
            self.back_btn.setEnabled(self.current_index > model_index)
        else:
            self.back_btn.setEnabled(self.current_index > 0)
        on_profile_page = self.current_index == self.pages.index(self.profile_page)
        self.add_profile_btn.setVisible(on_profile_page and not self._import_flow_locked)
        self.next_btn.setVisible(not last)
        self.finish_btn.setVisible(last)
        self.next_btn.setEnabled(current.can_continue())
        self.finish_btn.setEnabled(current.can_continue())

    def _go_back(self) -> None:
        if self._import_flow_locked:
            model_index = self.pages.index(self.model_page)
            if self.current_index <= model_index:
                return
        if self.current_index > 0:
            self._show_page(self.current_index - 1)

    def _go_next(self) -> None:
        if self.current_index < len(self.pages) - 1 and self.pages[self.current_index].can_continue():
            self._show_page(self.current_index + 1)

    def _import_profile_into_profile_page(self) -> None:
        if self.archive_service is None:
            QMessageBox.warning(self, "Import profile", "Import service is not available right now.")
            return
        confirm_choice = StartupPopupDialog(
            parent=self,
            blur_target=self._popup_blur_target,
            message=(
                'Hey there. Pressing "Browse account" will open the menu to locate your old account file. '
                "Once you select it, we will handle the rest for you."
            ),
            buttons=["Cancel", "Browse account"],
            default_button="Browse account",
        ).exec_with_backdrop()
        if confirm_choice != "Browse account":
            return
        archive_file, _ = QFileDialog.getOpenFileName(self, "Import profile zip", "", "Zip files (*.zip)")
        if not archive_file:
            return
        inspection = self.archive_service.inspect_archive(Path(archive_file))
        if not inspection.valid:
            QMessageBox.warning(self, "Import profile", inspection.error or "This profile zip is not valid.")
            return
        imported_profile = self._normalized_import_profile(inspection=inspection, archive_file=archive_file)
        self.profile_page.set_imported_profile(imported_profile, archive_path=archive_file)
        self.import_archive_path = archive_file
        self._import_flow_locked = True
        imported_name = str(imported_profile.get("name", "")).strip() or "there"
        StartupPopupDialog(
            parent=self,
            blur_target=self._popup_blur_target,
            message=(
                f'Hello, {imported_name}, welcome back! We have set up your profile into this ONCard app. '
                'You can press "okay" to continue.'
            ),
            buttons=["okay"],
            default_button="okay",
        ).exec_with_backdrop()
        self._show_page(self.pages.index(self.model_page))
        self._refresh_nav()

    def _normalized_import_profile(self, *, inspection, archive_file: str) -> dict:
        return _normalized_import_profile_payload(
            inspection=inspection,
            archive_file=archive_file,
            archive_age_grade_pattern=self.ARCHIVE_AGE_GRADE_PATTERN,
        )

    def _remove_imported_profile(self) -> None:
        self.profile_page.clear_imported_profile()
        self.import_archive_path = ""
        self._refresh_nav()

    def accept(self) -> None:
        if not self.pages[self.current_index].can_continue():
            return
        profile = self.profile_page.profile_payload()
        self.datastore.save_profile(profile)

        setup_state = self.datastore.load_setup()
        setup_payload = self.model_page.setup_payload()
        perf_payload = self.performance_page.performance_payload()
        setup_state["onboarding_complete"] = True
        setup_state["ram_gb"] = setup_payload.ram_gb
        setup_state["advanced_installation"] = setup_payload.advanced_installation
        setup_state["selected_models"] = setup_payload.selected_models or []
        setup_state["installed_models"] = setup_payload.installed_models or {}
        setup_state["performance_arena"] = perf_payload
        self.datastore.save_setup(setup_state)
        super().accept()


class ProfileMakerDialog(QDialog):
    ARCHIVE_AGE_GRADE_PATTERN = re.compile(r"_A(?P<age>\d{1,2})_G(?P<grade>\d{1,2})\.zip$", re.IGNORECASE)

    def __init__(
        self,
        paths,
        *,
        existing_names: set[str] | None = None,
        archive_service: AccountArchiveService | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.paths = paths
        self.existing_names = set(existing_names or set())
        self.archive_service = archive_service
        self.import_archive_path = ""
        self.sounds = UiSoundBank(self.paths.assets / "sfx")

        self.setWindowTitle("Profile setup")
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, False)
        self.setWindowFlag(Qt.MSWindowsFixedSizeDialogHint, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(1040, 760)
        self.setStyleSheet(
            """
            QFrame#OnboardingWindowShell {
                background: #ffffff;
                border: none;
                border-radius: 30px;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        shell_surface = QFrame(self)
        shell_surface.setObjectName("OnboardingWindowShell")
        polish_surface(shell_surface)
        root.addWidget(shell_surface, 1)

        shell = QVBoxLayout(shell_surface)
        shell.setContentsMargins(18, 14, 18, 14)
        shell.setSpacing(12)

        self._shell_surface = shell_surface
        self.close_btn = FadingIconButton(
            icon_path=self.paths.icons / "common" / "cross_two.png",
            tooltip="Close",
            button_size=34,
            icon_size=12,
            parent=shell_surface,
        )
        self.close_btn.clicked.connect(self.reject)

        self.profile_page = ProfilePage(
            self.paths.banners,
            self.sounds,
            onboarding_placeholder_tint=True,
        )
        self.profile_page.import_profile_requested.connect(self._import_profile)
        self.profile_page.remove_import_requested.connect(self._remove_imported_profile)
        shell.addWidget(self.profile_page, 1)

        nav = QHBoxLayout()
        nav.setContentsMargins(0, 8, 8, 4)
        nav.setSpacing(0)
        nav.addStretch(1)
        self.finish_btn = FadingIconButton(
            icon_path=self.paths.icons / "common" / "check.png",
            tooltip="Create profile",
            button_size=34,
            icon_size=12,
        )
        self.finish_btn.clicked.connect(self._accept_if_valid)
        nav.addWidget(self.finish_btn)
        shell.addLayout(nav)
        self._position_close_button()
        polish_windows_window(self, rounded=False, small_corners=False, remove_border=True)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        polish_windows_window(self, rounded=False, small_corners=False, remove_border=True)
        self._position_close_button()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_close_button()

    def _position_close_button(self) -> None:
        if not hasattr(self, "close_btn") or not hasattr(self, "_shell_surface"):
            return
        margin_right = 18
        margin_top = 14
        x = self._shell_surface.width() - self.close_btn.width() - margin_right
        y = margin_top
        self.close_btn.move(max(0, x), max(0, y))
        self.close_btn.raise_()

    def _import_profile(self) -> None:
        if self.archive_service is None:
            QMessageBox.warning(self, "Import profile", "Import service is not available right now.")
            return
        archive_file, _ = QFileDialog.getOpenFileName(self, "Import profile zip", "", "Zip files (*.zip)")
        if not archive_file:
            return
        inspection = self.archive_service.inspect_archive(Path(archive_file))
        if not inspection.valid:
            QMessageBox.warning(self, "Import profile", inspection.error or "This profile zip is not valid.")
            return
        imported_profile = _normalized_import_profile_payload(
            inspection=inspection,
            archive_file=archive_file,
            archive_age_grade_pattern=self.ARCHIVE_AGE_GRADE_PATTERN,
        )
        self.profile_page.set_imported_profile(imported_profile, archive_path=archive_file)
        self.import_archive_path = archive_file
        QMessageBox.information(
            self,
            "Import profile",
            'Profile cached successfully! press "Add profile" to add the account',
        )

    def _remove_imported_profile(self) -> None:
        self.profile_page.clear_imported_profile()
        self.import_archive_path = ""

    def _accept_if_valid(self) -> None:
        profile = self.profile_payload()
        name = str(profile.get("name", "")).strip()
        if not name:
            QMessageBox.warning(self, "Profile maker", "Name is required.")
            return
        if name in self.existing_names:
            QMessageBox.warning(self, "Profile maker", "An account with the same name already exists.")
            return
        self.accept()

    def profile_payload(self) -> dict:
        return self.profile_page.profile_payload()

