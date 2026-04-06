from __future__ import annotations

from dataclasses import dataclass
import html
from pathlib import Path
import re
import shutil
import webbrowser

from PySide6.QtCore import QEasingCurve, QPoint, QRect, Qt, QTimer, Signal, QVariantAnimation
from PySide6.QtGui import QColor
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
    QSpinBox,
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
        root.setSpacing(12)
        root.addWidget(title_label)
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
        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(title_label)
        layout.addWidget(widget)


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


class ProfilePage(OnboardingPage):
    import_profile_requested = Signal()
    remove_import_requested = Signal()

    def __init__(self, banners_root: Path, sounds: UiSoundBank | None = None) -> None:
        super().__init__(
            title="Welcome to ONCard",
            body="Let us shape the app around how you study, with clean controls and less clutter from the start.",
            banner_path=banners_root / "onboarding_profile_banner_16x9.png",
            banner_name="onboarding_profile_banner_16x9.png",
        )
        self.sounds = sounds
        self._last_attention_value = 5
        self._import_archive_path = ""
        self._imported_profile_active = False
        self._allow_import_removal = True
        self._profile_name_auto_sync = True

        surface = QFrame()
        surface.setObjectName("Surface")
        polish_surface(surface)
        surface_layout = QVBoxLayout(surface)
        surface_layout.setContentsMargins(18, 18, 18, 18)
        surface_layout.setSpacing(12)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        self.name_edit = AnimatedLineEdit()
        self.profile_name_edit = AnimatedLineEdit()
        self.age_spin = QSpinBox()
        self.age_spin.setRange(4, 99)
        self.age_spin.setValue(16)
        self.grade_combo = AnimatedComboBox()
        self.grade_combo.addItems([f"Grade {value}" for value in range(4, 13)])
        self.gender_combo = AnimatedComboBox()
        self.gender_combo.addItems(["Male", "Female", "Custom"])
        self.gender_custom_edit = AnimatedLineEdit()
        self.gender_custom_edit.setMaxLength(20)
        self.gender_custom_edit.setPlaceholderText("Custom gender (max 20)")
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
        self.hobbies_edit = AnimatedLineEdit()

        self.attention_slider = QSlider(Qt.Horizontal)
        self.attention_slider.setRange(1, 10)
        self.attention_slider.setSingleStep(1)
        self.attention_slider.setPageStep(1)
        self.attention_slider.setValue(5)
        self.attention_value = QLabel("Attention span per question: 5 min")
        self.attention_value.setObjectName("SectionText")

        self.name_edit.textChanged.connect(lambda *_: self.changed.emit())
        self.name_edit.textChanged.connect(self._on_name_changed)
        self.profile_name_edit.textEdited.connect(self._on_profile_name_edited)
        self.age_spin.valueChanged.connect(lambda *_: self.changed.emit())
        self.grade_combo.currentTextChanged.connect(lambda *_: self.changed.emit())
        self.gender_combo.currentTextChanged.connect(lambda *_: self.changed.emit())
        self.gender_custom_edit.textChanged.connect(lambda *_: self.changed.emit())
        self.hobbies_edit.textChanged.connect(lambda *_: self.changed.emit())
        self.attention_slider.valueChanged.connect(self._on_attention_changed)

        grid.addWidget(FieldBlock("User name", self.name_edit), 0, 0)
        grid.addWidget(FieldBlock("Profile name", self.profile_name_edit), 0, 1)
        grid.addWidget(FieldBlock("Age", self.age_spin), 1, 0)
        grid.addWidget(FieldBlock("Grade", self.grade_combo), 1, 1)
        grid.addWidget(FieldBlock("Hobbies / interests", self.hobbies_edit), 2, 0)
        grid.addWidget(FieldBlock("Gender", gender_shell), 2, 1)

        surface_layout.addLayout(grid)
        surface_layout.addWidget(self.attention_value)
        surface_layout.addWidget(self.attention_slider)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 2, 0, 0)
        controls.setSpacing(8)
        self.import_profile_btn = AnimatedButton("Import profile")
        self.import_profile_btn.setProperty("disablePressMotion", True)
        self.import_profile_btn.clicked.connect(self.import_profile_requested.emit)
        self.remove_zip_btn = AnimatedButton("remove zip file")
        self.remove_zip_btn.setProperty("disablePressMotion", True)
        self.remove_zip_btn.clicked.connect(self.remove_import_requested.emit)
        self.remove_zip_btn.hide()
        controls.addWidget(self.import_profile_btn, 0, Qt.AlignLeft)
        controls.addWidget(self.remove_zip_btn, 0, Qt.AlignLeft)
        controls.addStretch(1)
        surface_layout.addLayout(controls)

        self.body_layout().addWidget(surface)
        self.body_layout().addStretch(1)

    def _on_attention_changed(self, value: int) -> None:
        if value != self._last_attention_value and self.sounds is not None:
            self.sounds.play("click", volume_scale=1.25)
        self._last_attention_value = value
        self.attention_value.setText(f"Attention span per question: {value} min")
        self.changed.emit()

    def _on_name_changed(self) -> None:
        if self._profile_name_auto_sync:
            self.profile_name_edit.setText(self.name_edit.text().strip())

    def _on_profile_name_edited(self, text: str) -> None:
        self._profile_name_auto_sync = text.strip() == self.name_edit.text().strip()

    def _on_gender_mode_changed(self) -> None:
        is_custom = self.gender_combo.currentText().strip().lower() == "custom"
        self.gender_custom_edit.setVisible(is_custom)

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
            self.gender_custom_edit.setText(gender[:20])
        else:
            self.gender_combo.setCurrentText("Male")
            self.gender_custom_edit.clear()
        self._on_gender_mode_changed()

    def _effective_gender(self) -> str:
        mode = self.gender_combo.currentText().strip()
        if mode.lower() == "custom":
            return self.gender_custom_edit.text().strip()[:20]
        return mode

    def can_continue(self) -> bool:
        if self._imported_profile_active:
            return True
        if not self.name_edit.text().strip():
            return False
        if self.gender_combo.currentText().strip().lower() == "custom":
            return bool(self.gender_custom_edit.text().strip())
        return True

    def profile_payload(self) -> dict:
        user_name = self.name_edit.text().strip()
        return {
            "name": user_name,
            "profile_name": self.profile_name_edit.text().strip() or user_name,
            "age": str(self.age_spin.value()),
            "grade": self.grade_combo.currentText(),
            "gender": self._effective_gender(),
            "hobbies": self.hobbies_edit.text().strip(),
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
        age = max(self.age_spin.minimum(), min(age, self.age_spin.maximum()))
        self.age_spin.setValue(age)
        grade = str(profile.get("grade", "")).strip()
        if grade:
            self.grade_combo.setCurrentText(grade)
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
        self.age_spin.setEnabled(not locked)
        self.grade_combo.setEnabled(not locked)
        self.gender_combo.setEnabled(not locked)
        self.gender_custom_edit.setEnabled(not locked and self.gender_combo.currentText().strip().lower() == "custom")
        if locked:
            self.gender_custom_edit.setVisible(False)
        else:
            self._on_gender_mode_changed()
        self.hobbies_edit.setEnabled(not locked)
        self.attention_slider.setEnabled(not locked)
        self.import_profile_btn.setVisible(not locked)
        self.remove_zip_btn.setVisible(locked and self._allow_import_removal)

    def set_allow_import_removal(self, allow: bool) -> None:
        self._allow_import_removal = bool(allow)
        if self._import_archive_path:
            self.remove_zip_btn.setVisible(self._allow_import_removal)


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
            body="ONCard installs the required AI models automatically, including Gemma for generation and Nomic for embeddings.",
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

        self.summary_label = QLabel()
        self.summary_label.setObjectName("SectionTitle")
        self.summary_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.size_label = QLabel()
        self.size_label.setObjectName("SectionText")
        self.size_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.warning_label = QLabel()
        self.warning_label.setObjectName("SmallMeta")
        self.warning_label.setWordWrap(True)
        self.warning_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.ollama_label = QLabel("Ollama is not installed yet. Install it first, then come back here.")
        self.ollama_label.setObjectName("SmallMeta")
        self.ollama_label.setWordWrap(True)
        self.ollama_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.ollama_button = AnimatedButton("Open Ollama website")
        self.ollama_button.setProperty("disablePressMotion", True)
        self.ollama_button.clicked.connect(lambda: webbrowser.open("https://ollama.com/download"))
        if self.ollama_installed:
            self.ollama_label.hide()
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
                background: rgba(184, 200, 216, 0.45);
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
        self.log.setMinimumHeight(84)
        self.log.setMaximumHeight(110)
        self.log.setPlaceholderText("Installation progress appears here.")

        layout.addWidget(self.summary_label)
        layout.addWidget(self.size_label)
        layout.addWidget(self.warning_label)
        layout.addWidget(self.ollama_label)
        layout.addWidget(self.ollama_button, 0, Qt.AlignLeft)
        layout.addWidget(self.install_button, 0, Qt.AlignHCenter)
        layout.addWidget(self.progress)
        layout.addWidget(self.log)

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
        can_install = self.ollama_installed and self.ram_gb >= 7
        if self.ram_gb < 7:
            self.summary_label.setText("This device is below the minimum requirement for ONCard.")
            self.install_button.setEnabled(False)
        elif not self.ollama_installed:
            self.summary_label.setText("Install Ollama first to unlock model downloads.")
            self.install_button.setEnabled(False)
        elif self.ram_gb >= 23:
            self.summary_label.setText("Your device is eligible for full download.")
            self.install_button.setEnabled(True)
        elif self.ram_gb >= 15:
            self.summary_label.setText("Your device is eligible for the standard download.")
            self.install_button.setEnabled(True)
        else:
            self.summary_label.setText("Your device will use the lighter default download.")
            self.install_button.setEnabled(True)

        self.size_label.setText(f"Selected download size: {size_gb:.1f} GB")
        self.warning_label.setText(
            "ONCard uses gemma3:4b for OCR and generation tasks, plus nomic-embed-text-v2-moe for adaptive-study embeddings."
        )
        self.warning_label.show()

        self.ollama_label.setVisible(not self.ollama_installed)
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
            body="Run the Gemma3:4b speed test. This step is required so ONCard can continue with the full setup flow.",
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
        self.result_title = QLabel("No test run yet.")
        self.result_title.setObjectName("SectionTitle")
        self.badge = QLabel("")
        self.badge.setObjectName("TierBadge")
        self.badge.hide()
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(84)
        self.log.setMaximumHeight(110)

        layout.addWidget(self.run_button, 0, Qt.AlignHCenter)
        layout.addWidget(self.progress)
        layout.addWidget(self.result_title)
        layout.addWidget(self.badge)
        layout.addWidget(self.log)
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
        self.result_title.setText("Running test...")
        self.badge.hide()
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
        self.result_title.setText(f"Average TPS: {avg_tps}")
        self.badge.setText(tier)
        self.badge.show()
        self._enqueue_progress(100)
        self._set_banner_by_tier(tier)
        self.changed.emit()

    def _on_failed(self, message: str) -> None:
        self.result_title.setText("Performance test failed.")
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
                border: none;
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
        root.addWidget(shell_surface, 1)

        shell = QVBoxLayout(shell_surface)
        shell.setContentsMargins(18, 14, 18, 14)
        shell.setSpacing(12)

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
        self.profile_page = ProfilePage(self.paths.banners, self.sounds)
        self.profile_page.set_allow_import_removal(False)
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
        nav.addStretch(1)
        self.back_btn = AnimatedButton("Back")
        self.back_btn.setProperty("disablePressMotion", True)
        self.next_btn = AnimatedButton("Next")
        self.next_btn.setProperty("disablePressMotion", True)
        self.next_btn.setObjectName("PrimaryButton")
        self.finish_btn = AnimatedButton("Finish")
        self.finish_btn.setProperty("disablePressMotion", True)
        self.finish_btn.setObjectName("PrimaryButton")
        self.cancel_btn = AnimatedButton("Cancel")
        self.cancel_btn.setProperty("disablePressMotion", True)
        self.back_btn.clicked.connect(self._go_back)
        self.next_btn.clicked.connect(self._go_next)
        self.finish_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)
        nav.addWidget(self.back_btn)
        nav.addWidget(self.next_btn)
        nav.addWidget(self.finish_btn)
        nav.addWidget(self.cancel_btn)
        blur_layout.addLayout(nav)
        shell.addWidget(blur_layer, 1)

        polish_windows_window(self, rounded=False, small_corners=False, remove_border=True)
        self._show_page(0)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        polish_windows_window(self, rounded=False, small_corners=False, remove_border=True)

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

        archive_match = self.ARCHIVE_AGE_GRADE_PATTERN.search(str(archive_file).strip())
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

        self.setWindowTitle("Profile maker")
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, False)
        self.setWindowFlag(Qt.MSWindowsFixedSizeDialogHint, True)
        self.setFixedSize(980, 700)

        shell = QVBoxLayout(self)
        shell.setContentsMargins(18, 14, 18, 14)
        shell.setSpacing(12)

        self.profile_page = ProfilePage(self.paths.banners, self.sounds)
        self.profile_page.import_profile_requested.connect(self._import_profile)
        self.profile_page.remove_import_requested.connect(self._remove_imported_profile)
        shell.addWidget(self.profile_page, 1)

        nav = QHBoxLayout()
        nav.addStretch(1)
        self.create_btn = AnimatedButton("Create account")
        self.create_btn.setObjectName("PrimaryButton")
        self.cancel_btn = AnimatedButton("Cancel")
        self.create_btn.clicked.connect(self._accept_if_valid)
        self.cancel_btn.clicked.connect(self.reject)
        nav.addWidget(self.create_btn)
        nav.addWidget(self.cancel_btn)
        shell.addLayout(nav)

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
        self.profile_page.set_imported_profile(inspection.profile, archive_path=archive_file)
        self.import_archive_path = archive_file

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

