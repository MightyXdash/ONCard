from __future__ import annotations

from pathlib import Path
import shutil

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsBlurEffect,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QStyle,
)

from studymate.services.data_store import DataStore
from studymate.services.model_preflight import ModelPreflightService
from studymate.services.model_registry import MODELS, ModelSpec, non_embedding_llm_keys
from studymate.services.ollama_service import OllamaError, OllamaService
from studymate.ui.animated import AnimatedButton, AnimatedComboBox, AnimatedLineEdit, polish_surface
from studymate.workers.install_worker import ModelInstallWorker


FOLLOWUP_CONTEXT_MIN = 9216
REINFORCEMENT_CONTEXT_MIN = 8192
MAX_CONTEXT_LENGTH = 65536
ASK_AI_TONE_OPTIONS = [
    ("Warm", "warm"),
    ("Funny", "funny"),
    ("Sarcastic", "sarcastic"),
    ("Glazer", "glazer"),
    ("Shakespeare", "shakespeare"),
]
ASK_AI_EMOJI_LABELS = {
    1: "Emoji usage: none",
    2: "Emoji usage: some",
    3: "Emoji usage: good amount",
    4: "Emoji usage: a lot",
}
MODEL_ROLE_COPY = {
    "gemma3_4b": "Create cards, Files To Cards, grading, follow-up help, and reinforcement generation.",
    "ministral_3_3b": "Optional lightweight LLM with native tool calling for Ask AI and other text features.",
    "ministral_3_8b": "Optional balanced LLM with native tool calling for Ask AI and other text features.",
    "ministral_3_14b": "Optional larger LLM with native tool calling for Ask AI and other text features.",
    "nomic_embed_text_v2_moe": "Semantic search, recommendations, topic clustering, and adaptive study features.",
}


class PopupMenuComboBox(AnimatedComboBox):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._popup_handler = None

    def set_popup_handler(self, handler) -> None:
        self._popup_handler = handler

    def showPopup(self) -> None:
        if callable(self._popup_handler):
            self._popup_handler()
            return
        super().showPopup()


class FTCPopupChoiceDialog(QDialog):
    def __init__(
        self,
        *,
        parent: QWidget,
        blur_target: QWidget | None,
        title: str,
        options: list[tuple[str, str]],
        current_value: str,
    ) -> None:
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._blur_target = blur_target or parent
        self._overlay_target = parent
        self._overlay: QWidget | None = None
        self._previous_effect = None
        self._selected_value = str(current_value or "")
        self._choice_buttons: dict[str, AnimatedButton] = {}

        options_clean = [(str(label), str(value)) for label, value in options if str(value).strip()]
        if not options_clean:
            options_clean = [("Normal", "normal")]
        known_values = {value for _label, value in options_clean}
        if self._selected_value not in known_values:
            self._selected_value = options_clean[0][1]

        root = QVBoxLayout(self)
        root.setContentsMargins(44, 44, 44, 44)
        root.setSpacing(0)

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

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header_title = QLabel(title)
        header_title.setObjectName("SectionTitle")
        header.addWidget(header_title)
        header.addStretch(1)

        icon_provider = getattr(parent, "icons", None)
        if icon_provider is not None and hasattr(icon_provider, "icon"):
            save_icon = icon_provider.icon("common", "check", "C")
            close_icon = icon_provider.icon("common", "cross_two", "X")
        else:
            save_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
            close_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton)

        self.save_btn = QToolButton()
        self.save_btn.setObjectName("FTCPopupIconButton")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setIcon(save_icon if isinstance(save_icon, QIcon) else QIcon())
        self.save_btn.setIconSize(QSize(15, 15))
        self.save_btn.setFixedSize(34, 34)
        self.save_btn.clicked.connect(self._save_and_accept)
        header.addWidget(self.save_btn)

        self.close_btn = QToolButton()
        self.close_btn.setObjectName("FTCPopupIconButton")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setIcon(close_icon if isinstance(close_icon, QIcon) else QIcon())
        self.close_btn.setIconSize(QSize(15, 15))
        self.close_btn.setFixedSize(34, 34)
        self.close_btn.clicked.connect(self.reject)
        header.addWidget(self.close_btn)
        body.addLayout(header)

        choices_shell = QFrame()
        choices_shell.setObjectName("FTCPopupFieldShell")
        choices_layout = QHBoxLayout(choices_shell)
        choices_layout.setContentsMargins(8, 8, 8, 8)
        choices_layout.setSpacing(8)
        for label, value in options_clean:
            button = AnimatedButton(label)
            button.setObjectName("FTCPopupChoiceButton")
            button.setCheckable(True)
            button.setProperty("disablePressMotion", True)
            button.set_motion_scale_range(0.0)
            button.clicked.connect(lambda _checked=False, selected=value: self._set_value(selected))
            choices_layout.addWidget(button, 1)
            self._choice_buttons[value] = button
        body.addWidget(choices_shell)
        self._refresh_buttons()
        self.setMinimumWidth(500)

    def selected_value(self) -> str:
        return str(self._selected_value or "")

    def exec_with_backdrop(self) -> int:
        self._apply_backdrop()
        try:
            self._center_on_parent()
            return self.exec()
        finally:
            self._clear_backdrop()

    def mousePressEvent(self, event) -> None:
        if not self.card.geometry().contains(event.position().toPoint()):
            self.reject()
            event.accept()
            return
        super().mousePressEvent(event)

    def _set_value(self, value: str) -> None:
        self._selected_value = str(value or "")
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        for value, button in self._choice_buttons.items():
            selected = value == self._selected_value
            button.setChecked(selected)
            button.setProperty("selected", selected)
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()

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


class SettingsDialog(QDialog):
    def __init__(
        self,
        datastore: DataStore,
        ollama: OllamaService,
        preflight: ModelPreflightService,
        parent=None,
        *,
        session_controller=None,
    ) -> None:
        super().__init__(parent)
        self.datastore = datastore
        self.ollama = ollama
        self.preflight = preflight
        self.session_controller = session_controller
        self._install_worker: ModelInstallWorker | None = None
        self._install_target_key = ""
        self._model_rows: dict[str, dict[str, object]] = {}
        self._account_action_buttons: list[QPushButton] = []
        self._sfx_ready = False
        self._last_attention_value = 5
        self._last_ask_ai_emoji_value = 2
        self._model_worker_action = "install"

        self.setWindowTitle("Settings")
        self.setObjectName("SettingsDialog")
        self._apply_initial_geometry()
        self._build_ui()
        self._load()
        self._sfx_ready = True

    def _apply_initial_geometry(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(860, 720)
            return
        available = screen.availableGeometry()
        width = min(860, max(720, available.width() - 120))
        height = min(720, max(560, available.height() - 120))
        self.resize(width, height)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        title = QLabel("Settings")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_general_tab(), "General")
        self.tabs.addTab(self._build_stats_tab(), "Stats")
        self.tabs.addTab(self._build_ai_tab(), "AI")
        self.tabs.addTab(self._build_performance_tab(), "Performance")
        root.addWidget(self.tabs, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.cancel_btn = AnimatedButton("Cancel")
        self.save_btn = AnimatedButton("Save")
        self.save_btn.setObjectName("PrimaryButton")
        self.cancel_btn.clicked.connect(self.reject)
        self.save_btn.clicked.connect(self._save)
        actions.addWidget(self.cancel_btn)
        actions.addWidget(self.save_btn)
        root.addLayout(actions)

    def _build_general_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        intro = QLabel("Update the basic student profile ONCard uses when generating and grading responses.")
        intro.setObjectName("SectionText")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        surface = QFrame()
        surface.setObjectName("Surface")
        polish_surface(surface)
        form = QFormLayout(surface)
        form.setContentsMargins(20, 20, 20, 20)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(14)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignTop)

        self.name_edit = AnimatedLineEdit()
        self.profile_name_edit = AnimatedLineEdit()
        self.age_spin = QSpinBox()
        self.age_spin.setRange(4, 99)
        self.hobbies_edit = AnimatedLineEdit()
        self.grade_combo = AnimatedComboBox()
        self.grade_combo.setEditable(True)
        self.grade_combo.addItems([f"Grade {value}" for value in range(4, 13)])
        self.gender_combo = AnimatedComboBox()
        self.gender_combo.addItems(["Male", "Female", "Custom"])
        self.gender_custom_edit = AnimatedLineEdit()
        self.gender_custom_edit.setMaxLength(20)
        self.gender_custom_edit.setPlaceholderText("Custom gender (max 20)")
        self.gender_custom_edit.setVisible(False)
        self.gender_combo.currentIndexChanged.connect(self._on_gender_mode_changed)
        gender_shell = QWidget()
        gender_shell.setObjectName("SettingsGenderShell")
        gender_shell.setStyleSheet("QWidget#SettingsGenderShell { background: transparent; }")
        gender_layout = QVBoxLayout(gender_shell)
        gender_layout.setContentsMargins(0, 0, 0, 0)
        gender_layout.setSpacing(6)
        gender_layout.addWidget(self.gender_combo)
        gender_layout.addWidget(self.gender_custom_edit)
        self.attention_slider = QSlider(Qt.Horizontal)
        self.attention_slider.setObjectName("SettingsAttentionSlider")
        self.attention_slider.setRange(1, 10)
        self.attention_slider.setSingleStep(1)
        self.attention_slider.setPageStep(1)
        self.attention_slider.setValue(5)
        self.attention_slider.setStyleSheet(
            """
            QSlider#SettingsAttentionSlider {
                background: transparent;
            }
            QSlider#SettingsAttentionSlider::groove:horizontal {
                height: 6px;
                border-radius: 4px;
                background: #d4deea;
            }
            QSlider#SettingsAttentionSlider::sub-page:horizontal {
                background: #d4deea;
                border-radius: 4px;
            }
            QSlider#SettingsAttentionSlider::add-page:horizontal {
                background: #d4deea;
                border-radius: 4px;
            }
            QSlider#SettingsAttentionSlider::handle:horizontal {
                width: 20px;
                height: 20px;
                margin: -7px 0;
                border-radius: 10px;
                background: #0f2539;
            }
            """
        )
        self.attention_slider.valueChanged.connect(self._on_attention_changed)
        self.attention_value = QLabel("Attention span per question: 5 min")
        self.attention_value.setObjectName("SectionText")
        attention_shell = QWidget()
        attention_shell.setObjectName("SettingsAttentionShell")
        attention_shell.setStyleSheet("QWidget#SettingsAttentionShell { background: transparent; }")
        attention_layout = QVBoxLayout(attention_shell)
        attention_layout.setContentsMargins(0, 0, 0, 0)
        attention_layout.setSpacing(6)
        attention_layout.addWidget(self.attention_value)
        attention_layout.addWidget(self.attention_slider)

        form.addRow("User name", self.name_edit)
        form.addRow("Profile name", self.profile_name_edit)
        form.addRow("Age", self.age_spin)
        form.addRow("Hobby/Interests", self.hobbies_edit)
        form.addRow("Grade", self.grade_combo)
        form.addRow("Gender", gender_shell)
        form.addRow("Attention span", attention_shell)

        layout.addWidget(surface)

        account_surface = QFrame()
        account_surface.setObjectName("Surface")
        polish_surface(account_surface)
        account_layout = QVBoxLayout(account_surface)
        account_layout.setContentsMargins(20, 20, 20, 20)
        account_layout.setSpacing(8)
        account_title = QLabel("Profile account actions")
        account_title.setObjectName("SectionTitle")
        account_note = QLabel("Manage your account directly from profile settings.")
        account_note.setObjectName("SectionText")
        account_note.setWordWrap(True)
        account_layout.addWidget(account_title)
        account_layout.addWidget(account_note)

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 2, 0, 0)
        actions_row.setSpacing(10)
        for text, handler in (
            ("export account", self._export_account_flow),
            ("delete account", self._delete_account_flow),
            ("change account", self._change_account_flow),
            ("New account", self._new_account_flow),
        ):
            button = QPushButton(text)
            button.setObjectName("SettingsTinyLink")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFlat(True)
            button.clicked.connect(handler)
            button.setStyleSheet(
                """
                QPushButton#SettingsTinyLink {
                    border: none;
                    background: transparent;
                    color: #8C96A1;
                    font-size: 11px;
                    padding: 0px;
                    text-align: left;
                }
                QPushButton#SettingsTinyLink:hover {
                    color: #2E7DFF;
                }
                """
            )
            actions_row.addWidget(button, 0, Qt.AlignLeft)
            self._account_action_buttons.append(button)
        actions_row.addStretch(1)
        account_layout.addLayout(actions_row)
        layout.addWidget(account_surface)

        ftc_surface = QFrame()
        ftc_surface.setObjectName("Surface")
        polish_surface(ftc_surface)
        ftc_layout = QVBoxLayout(ftc_surface)
        ftc_layout.setContentsMargins(20, 20, 20, 20)
        ftc_layout.setSpacing(10)

        ftc_title = QLabel("FTC")
        ftc_title.setObjectName("SectionTitle")
        ftc_note = QLabel("Default Files To Cards settings. Question counts are capped by available units per run.")
        ftc_note.setObjectName("SectionText")
        ftc_note.setWordWrap(True)
        ftc_layout.addWidget(ftc_title)
        ftc_layout.addWidget(ftc_note)

        ftc_form = QFormLayout()
        ftc_form.setHorizontalSpacing(16)
        ftc_form.setVerticalSpacing(14)
        ftc_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        ftc_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        ftc_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.ftc_default_mode = PopupMenuComboBox()
        self.ftc_default_mode.addItem("Standard", "standard")
        self.ftc_default_mode.addItem("Force", "force")
        self.ftc_default_mode.set_popup_handler(self._open_ftc_mode_picker)

        self.ftc_questions_standard = QSpinBox()
        self.ftc_questions_standard.setRange(1, 30)
        self.ftc_questions_standard.setMinimumWidth(140)
        self.ftc_questions_force = QSpinBox()
        self.ftc_questions_force.setRange(1, 30)
        self.ftc_questions_force.setMinimumWidth(140)

        self.ftc_difficulty = PopupMenuComboBox()
        self.ftc_difficulty.addItem("Easy", "easy")
        self.ftc_difficulty.addItem("Kinda easy", "kinda easy")
        self.ftc_difficulty.addItem("Normal", "normal")
        self.ftc_difficulty.addItem("Kinda difficult", "kinda difficult")
        self.ftc_difficulty.addItem("Difficult", "difficult")
        self.ftc_difficulty.set_popup_handler(self._open_ftc_difficulty_picker)

        self.ftc_ocr_checkbox = QCheckBox("Use OCR in Files To Cards")

        ftc_form.addRow("Default mode", self.ftc_default_mode)
        ftc_form.addRow("Question quantity (Standard)", self.ftc_questions_standard)
        ftc_form.addRow("Question quantity (Force)", self.ftc_questions_force)
        ftc_form.addRow("Difficulty", self.ftc_difficulty)
        ftc_form.addRow("Files To Cards OCR", self.ftc_ocr_checkbox)
        ftc_layout.addLayout(ftc_form)

        ftc_hint = QLabel(
            "Custom instructions will be pre-filled in Files To Cards based on the selected difficulty and profile."
        )
        ftc_hint.setObjectName("SmallMeta")
        ftc_hint.setWordWrap(True)
        ftc_layout.addWidget(ftc_hint)

        layout.addWidget(ftc_surface)
        self._set_account_actions_enabled(self.session_controller is not None)
        layout.addStretch(1)
        scroll.setWidget(host)
        return scroll

    def _open_ftc_mode_picker(self) -> None:
        self._open_ftc_choice_picker(
            title="Default mode",
            control=self.ftc_default_mode,
            fallback_value="standard",
        )

    def _open_ftc_difficulty_picker(self) -> None:
        self._open_ftc_choice_picker(
            title="Difficulty",
            control=self.ftc_difficulty,
            fallback_value="normal",
        )

    def _open_ftc_choice_picker(self, *, title: str, control: QComboBox, fallback_value: str) -> None:
        options: list[tuple[str, str]] = []
        for index in range(control.count()):
            label = str(control.itemText(index)).strip()
            value = str(control.itemData(index) or "").strip()
            if label and value:
                options.append((label, value))
        current_value = str(control.currentData() or fallback_value).strip() or fallback_value
        parent_widget = self.window() if isinstance(self.window(), QWidget) else self
        blur_target = getattr(parent_widget, "_popup_blur_target", parent_widget)
        picker = FTCPopupChoiceDialog(
            parent=parent_widget,
            blur_target=blur_target,
            title=title,
            options=options,
            current_value=current_value,
        )
        if picker.exec_with_backdrop() != QDialog.DialogCode.Accepted:
            return
        selected = picker.selected_value().strip() or fallback_value
        selected_index = control.findData(selected)
        if selected_index >= 0:
            control.setCurrentIndex(selected_index)

    def _build_ai_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        runtime_surface = QFrame()
        runtime_surface.setObjectName("Surface")
        polish_surface(runtime_surface)
        runtime_layout = QVBoxLayout(runtime_surface)
        runtime_layout.setContentsMargins(20, 20, 20, 20)
        runtime_layout.setSpacing(8)

        runtime_title = QLabel("Ollama runtime")
        runtime_title.setObjectName("SectionTitle")
        self.ollama_status = QLabel("")
        self.ollama_status.setObjectName("SectionText")
        self.ollama_status.setWordWrap(True)
        self.ollama_hint = QLabel("")
        self.ollama_hint.setObjectName("SmallMeta")
        self.ollama_hint.setWordWrap(True)
        self.refresh_models_btn = AnimatedButton("Refresh model status")
        self.refresh_models_btn.clicked.connect(self._refresh_model_status)
        runtime_layout.addWidget(runtime_title)
        runtime_layout.addWidget(self.ollama_status)
        runtime_layout.addWidget(self.ollama_hint)
        runtime_layout.addWidget(self.refresh_models_btn, 0, Qt.AlignLeft)
        layout.addWidget(runtime_surface)

        models_surface = QFrame()
        models_surface.setObjectName("Surface")
        polish_surface(models_surface)
        models_layout = QVBoxLayout(models_surface)
        models_layout.setContentsMargins(20, 20, 20, 20)
        models_layout.setSpacing(12)

        models_title = QLabel("Installed Ollama models")
        models_title.setObjectName("SectionTitle")
        models_note = QLabel("These are the Ollama models ONCard currently uses.")
        models_note.setObjectName("SectionText")
        models_note.setWordWrap(True)
        models_layout.addWidget(models_title)
        models_layout.addWidget(models_note)

        for spec in MODELS.values():
            row = self._build_model_row(spec)
            models_layout.addWidget(row["container"])
            self._model_rows[spec.key] = row

        self.install_log = QTextEdit()
        self.install_log.setReadOnly(True)
        self.install_log.setPlaceholderText("Model install activity will appear here.")
        self.install_log.setMinimumHeight(120)
        self.install_log.setMaximumHeight(160)
        models_layout.addWidget(self.install_log)
        layout.addWidget(models_surface)

        ai_surface = QFrame()
        ai_surface.setObjectName("Surface")
        polish_surface(ai_surface)
        ai_layout = QVBoxLayout(ai_surface)
        ai_layout.setContentsMargins(20, 20, 20, 20)
        ai_layout.setSpacing(12)

        ai_title = QLabel("AI features")
        ai_title.setObjectName("SectionTitle")
        ai_note = QLabel(
            "Context lengths can only be increased above the shipped defaults. Higher values can use more memory and may slow requests on weaker devices."
        )
        ai_note.setObjectName("SectionText")
        ai_note.setWordWrap(True)
        ai_layout.addWidget(ai_title)
        ai_layout.addWidget(ai_note)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(14)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.followup_ctx = QSpinBox()
        self.followup_ctx.setRange(FOLLOWUP_CONTEXT_MIN, MAX_CONTEXT_LENGTH)
        self.followup_ctx.setSingleStep(1024)
        self.followup_ctx.setSuffix(" tokens")
        self.reinforcement_ctx = QSpinBox()
        self.reinforcement_ctx.setRange(REINFORCEMENT_CONTEXT_MIN, MAX_CONTEXT_LENGTH)
        self.reinforcement_ctx.setSingleStep(1024)
        self.reinforcement_ctx.setSuffix(" tokens")
        self.ask_ai_tone = AnimatedComboBox()
        for label, value in ASK_AI_TONE_OPTIONS:
            self.ask_ai_tone.addItem(label, value)
        self.ask_ai_emoji_slider = QSlider(Qt.Orientation.Horizontal)
        self.ask_ai_emoji_slider.setObjectName("SettingsAskAiEmojiSlider")
        self.ask_ai_emoji_slider.setRange(1, 4)
        self.ask_ai_emoji_slider.setSingleStep(1)
        self.ask_ai_emoji_slider.setPageStep(1)
        self.ask_ai_emoji_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.ask_ai_emoji_slider.setTickInterval(1)
        self.ask_ai_emoji_slider.setStyleSheet(
            """
            QSlider#SettingsAskAiEmojiSlider {
                min-height: 28px;
                background: transparent;
            }
            QSlider#SettingsAskAiEmojiSlider::groove:horizontal {
                height: 6px;
                border-radius: 3px;
                background: rgba(15, 37, 57, 0.10);
            }
            QSlider#SettingsAskAiEmojiSlider::sub-page:horizontal {
                border-radius: 3px;
                background: #0f2539;
            }
            QSlider#SettingsAskAiEmojiSlider::add-page:horizontal {
                border-radius: 3px;
                background: rgba(15, 37, 57, 0.18);
            }
            QSlider#SettingsAskAiEmojiSlider::handle:horizontal {
                width: 20px;
                height: 20px;
                margin: -7px 0;
                border-radius: 10px;
                background: #0f2539;
            }
            """
        )
        self.ask_ai_emoji_slider.valueChanged.connect(self._on_ask_ai_emoji_changed)
        self.ask_ai_emoji_value = QLabel(ASK_AI_EMOJI_LABELS[2])
        self.ask_ai_emoji_value.setObjectName("SectionText")
        self.selected_text_llm = AnimatedComboBox()
        emoji_shell = QWidget()
        emoji_shell.setObjectName("SettingsAskAiEmojiShell")
        emoji_shell.setStyleSheet("QWidget#SettingsAskAiEmojiShell { background: transparent; }")
        emoji_layout = QVBoxLayout(emoji_shell)
        emoji_layout.setContentsMargins(0, 0, 0, 0)
        emoji_layout.setSpacing(6)
        emoji_layout.addWidget(self.ask_ai_emoji_value)
        emoji_layout.addWidget(self.ask_ai_emoji_slider)
        form.addRow("Follow-up context length", self.followup_ctx)
        form.addRow("Reinforcement context length", self.reinforcement_ctx)
        form.addRow("AI text model", self.selected_text_llm)
        form.addRow("Ask AI tone", self.ask_ai_tone)
        form.addRow("Ask AI emoji level", emoji_shell)
        ai_layout.addLayout(form)

        minimum_note = QLabel(
            f"Minimums: Follow-up {FOLLOWUP_CONTEXT_MIN} tokens, Reinforcement {REINFORCEMENT_CONTEXT_MIN} tokens."
        )
        minimum_note.setObjectName("SmallMeta")
        minimum_note.setWordWrap(True)
        ai_layout.addWidget(minimum_note)
        tone_note = QLabel(
            "Ask AI can use a saved tone preset and emoji intensity. The model still adapts to the situation, but this sets the default style."
        )
        tone_note.setObjectName("SmallMeta")
        tone_note.setWordWrap(True)
        ai_layout.addWidget(tone_note)
        model_note = QLabel(
            "Default setup installs only Gemma3:4b and Nomic Embed. Ministral models are optional and can be installed later here. The dropdown below uses installed text models only."
        )
        model_note.setObjectName("SmallMeta")
        model_note.setWordWrap(True)
        ai_layout.addWidget(model_note)
        layout.addWidget(ai_surface)

        layout.addStretch(1)
        scroll.setWidget(host)
        return scroll

    def _build_stats_tab(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        intro = QLabel("Choose which time range is selected by default when opening View stats.")
        intro.setObjectName("SectionText")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        surface = QFrame()
        surface.setObjectName("Surface")
        polish_surface(surface)
        form = QFormLayout(surface)
        form.setContentsMargins(20, 20, 20, 20)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(14)

        self.stats_default_range = AnimatedComboBox()
        self.stats_default_range.addItem("Hourly", "hourly")
        self.stats_default_range.addItem("Daily 3 days", "daily")
        self.stats_default_range.addItem("Weekly", "weekly")
        self.stats_default_range.addItem("2 Weeks", "2weeks")
        self.stats_default_range.addItem("Monthly", "monthly")
        form.addRow("Default time range", self.stats_default_range)

        note = QLabel("This only sets the initial selection. You can still switch range in View stats anytime.")
        note.setObjectName("SmallMeta")
        note.setWordWrap(True)

        layout.addWidget(surface)
        layout.addWidget(note)
        layout.addStretch(1)
        return host

    def _build_performance_tab(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        intro = QLabel("Control how aggressively ONCard warms caches, uses background workers, and handles motion.")
        intro.setObjectName("SectionText")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        perf_surface = QFrame()
        perf_surface.setObjectName("Surface")
        polish_surface(perf_surface)
        perf_layout = QFormLayout(perf_surface)
        perf_layout.setContentsMargins(20, 20, 20, 20)
        perf_layout.setHorizontalSpacing(16)
        perf_layout.setVerticalSpacing(14)

        self.performance_mode = AnimatedComboBox()
        self.performance_mode.addItem("Auto", "auto")
        self.performance_mode.addItem("Manual", "manual")
        self.performance_mode.currentIndexChanged.connect(self._refresh_performance_mode)

        self.startup_workers = QSpinBox()
        self.startup_workers.setRange(1, 8)
        self.background_workers = QSpinBox()
        self.background_workers.setRange(1, 8)
        self.warm_cache_checkbox = QCheckBox("Warm SQL, card, and vector caches during startup")
        self.reduced_motion_checkbox = QCheckBox("Reduce motion and transition animations")

        perf_layout.addRow("Mode", self.performance_mode)
        perf_layout.addRow("Startup workers", self.startup_workers)
        perf_layout.addRow("Background workers", self.background_workers)
        perf_layout.addRow("Startup warmup", self.warm_cache_checkbox)
        perf_layout.addRow("Reduced motion", self.reduced_motion_checkbox)

        note = QLabel(
            "Auto keeps ONCard on the recommended defaults. Manual lets you raise or lower the worker counts explicitly."
        )
        note.setObjectName("SmallMeta")
        note.setWordWrap(True)
        layout.addWidget(perf_surface)
        layout.addWidget(note)
        layout.addStretch(1)
        return host

    def _build_model_row(self, spec: ModelSpec) -> dict[str, object]:
        container = QFrame()
        container.setObjectName("QueueRow")
        polish_surface(container)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        copy_col = QVBoxLayout()
        copy_col.setContentsMargins(0, 0, 0, 0)
        copy_col.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        name_label = QLabel(spec.display_name)
        name_label.setObjectName("SectionTitle")
        kind_label = QLabel("Required" if spec.required else "Optional")
        kind_label.setObjectName("CardMetaPill")
        title_row.addWidget(name_label)
        title_row.addWidget(kind_label, 0, Qt.AlignLeft)
        title_row.addStretch(1)

        meta_label = QLabel(f"Tag: {spec.primary_tag}  |  Size: {spec.size_label}")
        meta_label.setObjectName("SmallMeta")
        role_label = QLabel(MODEL_ROLE_COPY.get(spec.key, "Used by ONCard."))
        role_label.setObjectName("SectionText")
        role_label.setWordWrap(True)
        copy_col.addLayout(title_row)
        copy_col.addWidget(meta_label)
        copy_col.addWidget(role_label)

        side_col = QVBoxLayout()
        side_col.setContentsMargins(0, 0, 0, 0)
        side_col.setSpacing(8)
        side_col.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status_label = QLabel("Checking...")
        status_label.setObjectName("CardMetaPill")
        install_btn = AnimatedButton("Install")
        reinstall_btn = AnimatedButton("Reinstall")
        delete_btn = AnimatedButton("Delete")
        install_btn.clicked.connect(lambda _checked=False, key=spec.key: self._install_model(key))
        reinstall_btn.clicked.connect(lambda _checked=False, key=spec.key: self._install_model(key))
        delete_btn.clicked.connect(lambda _checked=False, key=spec.key: self._delete_model(key))
        reinstall_btn.setVisible(False)
        delete_btn.setVisible(False)
        side_col.addWidget(status_label, 0, Qt.AlignRight)
        side_col.addWidget(install_btn, 0, Qt.AlignRight)
        side_col.addWidget(reinstall_btn, 0, Qt.AlignRight)
        side_col.addWidget(delete_btn, 0, Qt.AlignRight)

        layout.addLayout(copy_col, 1)
        layout.addLayout(side_col)
        return {
            "container": container,
            "status": status_label,
            "install_btn": install_btn,
            "reinstall_btn": reinstall_btn,
            "delete_btn": delete_btn,
            "spec": spec,
        }

    def _load(self) -> None:
        profile = self.datastore.load_profile()
        user_name = str(profile.get("name", "")).strip()
        profile_name = str(profile.get("profile_name", "")).strip() or user_name
        self.name_edit.setText(user_name)
        self.profile_name_edit.setText(profile_name)
        self.age_spin.setValue(self._coerce_age(profile.get("age")))
        self.hobbies_edit.setText(str(profile.get("hobbies", "")))
        self._set_gender_from_profile(str(profile.get("gender", "")).strip())

        grade = str(profile.get("grade", "")).strip()
        if grade and self.grade_combo.findText(grade) < 0:
            self.grade_combo.addItem(grade)
        if grade:
            self.grade_combo.setCurrentText(grade)
        attention_value = int(profile.get("attention_span_minutes", profile.get("question_focus_level", 5)) or 5)
        attention_value = max(1, min(10, attention_value))
        self.attention_slider.setValue(attention_value)
        self._last_attention_value = attention_value
        self._update_attention_label(attention_value)

        ai_settings = self.datastore.load_ai_settings()
        self.followup_ctx.setValue(max(FOLLOWUP_CONTEXT_MIN, int(ai_settings.get("followup_context_length", FOLLOWUP_CONTEXT_MIN))))
        self.reinforcement_ctx.setValue(
            max(REINFORCEMENT_CONTEXT_MIN, int(ai_settings.get("reinforcement_context_length", REINFORCEMENT_CONTEXT_MIN)))
        )
        tone_value = str(ai_settings.get("ask_ai_tone", ai_settings.get("assistant_tone", "warm"))).strip().lower() or "warm"
        tone_index = self.ask_ai_tone.findData(tone_value)
        if tone_index < 0:
            tone_index = self.ask_ai_tone.findData("warm")
        if tone_index < 0:
            tone_index = 0
        self.ask_ai_tone.setCurrentIndex(tone_index)
        emoji_value = max(1, min(4, int(ai_settings.get("ask_ai_emoji_level", 2) or 2)))
        self.ask_ai_emoji_slider.setValue(emoji_value)
        self._last_ask_ai_emoji_value = emoji_value
        self._update_ask_ai_emoji_label(emoji_value)
        setup = self.datastore.load_setup()
        ftc_setup = dict(setup.get("ftc", {}))
        default_mode = str(ftc_setup.get("default_mode", "standard"))
        mode_index = self.ftc_default_mode.findData(default_mode)
        if mode_index < 0:
            mode_index = 0
        self.ftc_default_mode.setCurrentIndex(mode_index)
        self.ftc_questions_standard.setValue(max(1, min(30, int(ftc_setup.get("question_count_standard", 4) or 4))))
        self.ftc_questions_force.setValue(max(1, min(30, int(ftc_setup.get("question_count_force", 8) or 8))))
        difficulty_value = str(ftc_setup.get("difficulty", "normal")).strip().lower()
        difficulty_index = self.ftc_difficulty.findData(difficulty_value)
        if difficulty_index < 0:
            difficulty_index = self.ftc_difficulty.findData("normal")
        if difficulty_index < 0:
            difficulty_index = 2
        self.ftc_difficulty.setCurrentIndex(difficulty_index)
        use_ocr = ftc_setup.get("use_ocr", ai_settings.get("files_to_cards_ocr", True))
        self.ftc_ocr_checkbox.setChecked(bool(use_ocr))
        performance = dict(setup.get("performance", {}))
        self.performance_mode.setCurrentIndex(0 if str(performance.get("mode", "auto")) == "auto" else 1)
        self.startup_workers.setValue(max(1, min(8, int(performance.get("startup_workers", 8) or 8))))
        self.background_workers.setValue(max(1, min(8, int(performance.get("background_workers", 2) or 2))))
        self.warm_cache_checkbox.setChecked(bool(performance.get("warm_cache_on_startup", True)))
        self.reduced_motion_checkbox.setChecked(bool(performance.get("reduced_motion", False)))
        stats_setup = dict(setup.get("stats", {}))
        default_stats_range = str(stats_setup.get("default_range", "daily")).strip().lower() or "daily"
        stats_index = self.stats_default_range.findData(default_stats_range)
        if stats_index < 0:
            stats_index = self.stats_default_range.findData("daily")
        if stats_index < 0:
            stats_index = 1
        self.stats_default_range.setCurrentIndex(stats_index)
        self._refresh_performance_mode()
        self._refresh_model_status()

    def _save(self) -> None:
        profile_name = self.name_edit.text().strip()
        if not profile_name:
            QMessageBox.warning(self, "Settings", "Name is required.")
            return
        if self.gender_combo.currentText().strip().lower() == "custom" and not self.gender_custom_edit.text().strip():
            QMessageBox.warning(self, "Settings", "Enter a custom gender up to 20 characters.")
            return
        if self.session_controller is not None:
            try:
                self.session_controller.rename_active_account(profile_name)
            except Exception as exc:
                QMessageBox.warning(self, "Settings", str(exc))
                return

        profile = self.datastore.load_profile()
        profile["name"] = profile_name
        profile["profile_name"] = self.profile_name_edit.text().strip() or profile_name
        profile["age"] = str(self.age_spin.value())
        profile["hobbies"] = self.hobbies_edit.text().strip()
        profile["grade"] = self.grade_combo.currentText().strip()
        profile["gender"] = self._effective_gender_value()
        profile["attention_span_minutes"] = self.attention_slider.value()
        profile["question_focus_level"] = self.attention_slider.value()
        self.datastore.save_profile(profile)

        ai_settings = self.datastore.load_ai_settings()
        ai_settings["followup_context_length"] = max(FOLLOWUP_CONTEXT_MIN, self.followup_ctx.value())
        ai_settings["reinforcement_context_length"] = max(REINFORCEMENT_CONTEXT_MIN, self.reinforcement_ctx.value())
        ai_settings["use_selected_llm_for_text_features"] = True
        selected_key = str(self.selected_text_llm.currentData() or "").strip()
        if selected_key:
            ai_settings["selected_text_llm_key"] = selected_key
        ai_settings["ask_ai_tone"] = str(self.ask_ai_tone.currentData() or "warm")
        ai_settings["assistant_tone"] = ai_settings["ask_ai_tone"]
        ai_settings["ask_ai_emoji_level"] = max(1, min(4, self.ask_ai_emoji_slider.value()))
        self.datastore.save_ai_settings(ai_settings)

        setup = self.datastore.load_setup()
        setup["ftc"] = {
            "default_mode": str(self.ftc_default_mode.currentData() or "standard"),
            "question_count_standard": int(self.ftc_questions_standard.value()),
            "question_count_force": int(self.ftc_questions_force.value()),
            "difficulty": str(self.ftc_difficulty.currentData() or "normal"),
            "use_ocr": bool(self.ftc_ocr_checkbox.isChecked()),
        }
        ai_settings = self.datastore.load_ai_settings()
        ai_settings["files_to_cards_ocr"] = self.ftc_ocr_checkbox.isChecked()
        self.datastore.save_ai_settings(ai_settings)
        setup["performance"] = {
            "mode": str(self.performance_mode.currentData() or "auto"),
            "startup_workers": self.startup_workers.value(),
            "background_workers": self.background_workers.value(),
            "warm_cache_on_startup": self.warm_cache_checkbox.isChecked(),
            "reduced_motion": self.reduced_motion_checkbox.isChecked(),
        }
        setup["stats"] = {
            "default_range": str(self.stats_default_range.currentData() or "daily"),
        }
        self.datastore.save_setup(setup)
        self.accept()

    def _play_click_sound(self, *, volume_scale: float = 1.0) -> None:
        if not self._sfx_ready:
            return
        parent = self.parentWidget()
        sounds = getattr(parent, "sounds", None)
        if sounds is not None:
            sounds.play("click", volume_scale=volume_scale)

    def _on_attention_changed(self, value: int) -> None:
        if value != self._last_attention_value:
            self._play_click_sound(volume_scale=1.25)
        self._last_attention_value = value
        self._update_attention_label(value)

    def _on_gender_mode_changed(self) -> None:
        is_custom = self.gender_combo.currentText().strip().lower() == "custom"
        self.gender_custom_edit.setVisible(is_custom)

    def _on_ask_ai_emoji_changed(self, value: int) -> None:
        if value != self._last_ask_ai_emoji_value:
            self._play_click_sound(volume_scale=1.1)
        self._last_ask_ai_emoji_value = value
        self._update_ask_ai_emoji_label(value)

    def _refresh_text_model_choices(self, snap=None) -> None:
        snapshot = snap or self.preflight.snapshot(force=False)
        ai_settings = self.datastore.load_ai_settings()
        saved_key = str(ai_settings.get("selected_text_llm_key", "")).strip()
        installed_keys = [key for key in non_embedding_llm_keys() if self._is_model_installed_ui(snapshot, key)]
        current_key = str(self.selected_text_llm.currentData() or saved_key).strip()
        target_key = saved_key if saved_key in installed_keys else (installed_keys[0] if installed_keys else "")
        self.selected_text_llm.blockSignals(True)
        self.selected_text_llm.clear()
        for key in installed_keys:
            spec = MODELS.get(key)
            if spec is None:
                continue
            self.selected_text_llm.addItem(spec.display_name, key)
        selected_index = self.selected_text_llm.findData(target_key)
        if selected_index < 0:
            selected_index = self.selected_text_llm.findData(current_key)
        if selected_index < 0 and self.selected_text_llm.count() > 0:
            selected_index = 0
        if selected_index >= 0:
            self.selected_text_llm.setCurrentIndex(selected_index)
        self.selected_text_llm.setEnabled(self.selected_text_llm.count() > 0)
        self.selected_text_llm.blockSignals(False)

    def _is_model_installed_ui(self, snapshot, model_key: str) -> bool:
        spec = MODELS.get(model_key)
        if spec is None:
            return False
        if snapshot.cli_available:
            # Prefer live tag inspection whenever Ollama is present.
            if snapshot.installed_tags:
                probe_tags = [spec.primary_tag, *spec.candidate_tags]
                return any(tag in snapshot.installed_tags for tag in probe_tags)
            # If CLI exists but tag lookup failed, avoid stale reinstall/delete states.
            if snapshot.error:
                return False
        return bool(snapshot.installed_models.get(model_key, False))

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

    def _effective_gender_value(self) -> str:
        mode = self.gender_combo.currentText().strip()
        if mode.lower() == "custom":
            return self.gender_custom_edit.text().strip()[:20]
        return mode

    def _update_attention_label(self, value: int) -> None:
        self.attention_value.setText(f"Attention span per question: {value} min")

    def _update_ask_ai_emoji_label(self, value: int) -> None:
        self.ask_ai_emoji_value.setText(ASK_AI_EMOJI_LABELS.get(int(value), ASK_AI_EMOJI_LABELS[2]))

    def _set_account_actions_enabled(self, enabled: bool) -> None:
        for button in self._account_action_buttons:
            button.setEnabled(enabled)

    def _export_account_flow(self) -> bool:
        if self.session_controller is None:
            return False
        try:
            temp_zip = self.session_controller.create_temp_export()
        except Exception as exc:
            QMessageBox.warning(self, "Export account", str(exc))
            return False
        msg = QMessageBox(self)
        msg.setWindowTitle("Export account")
        msg.setText("We have made a copy of your data. Where would you like to save it?")
        choose_btn = msg.addButton("I will choose", QMessageBox.AcceptRole)
        downloads_btn = msg.addButton("Downloads folder", QMessageBox.AcceptRole)
        cancel_btn = msg.addButton("Cancel", QMessageBox.RejectRole)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked == cancel_btn:
            self._cleanup_temp_export(temp_zip)
            return False

        destination: Path | None = None
        if clicked == downloads_btn:
            destination = Path.home() / "Downloads" / temp_zip.name
        elif clicked == choose_btn:
            filename, _ = QFileDialog.getSaveFileName(self, "Save exported account", temp_zip.name, "Zip files (*.zip)")
            if not filename:
                self._cleanup_temp_export(temp_zip)
                return False
            destination = Path(filename)
        if destination is None:
            self._cleanup_temp_export(temp_zip)
            return False

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(temp_zip, destination)
        except Exception as exc:
            QMessageBox.warning(self, "Export account", f"Could not save export: {exc}")
            self._cleanup_temp_export(temp_zip)
            return False
        self._cleanup_temp_export(temp_zip)
        QMessageBox.information(self, "Export account", f"Account copy saved:\n{destination}")
        return True

    @staticmethod
    def _cleanup_temp_export(path: Path) -> None:
        parent = path.parent
        path.unlink(missing_ok=True)
        shutil.rmtree(parent, ignore_errors=True)

    def _delete_account_flow(self) -> None:
        if self.session_controller is None:
            return
        for step in range(1, 5):
            answer = QMessageBox.question(
                self,
                "Delete account",
                f"Your local account will be delete forever. Are you sure? [{step}/4]",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if answer != QMessageBox.Yes:
                return

        final = QMessageBox(self)
        final.setWindowTitle("Delete account")
        final.setText("Got it! We will delete your data for you. Would you like to create a copy of your account before you do that?")
        copy_btn = final.addButton("Okay!", QMessageBox.AcceptRole)
        final.addButton("permentantly delete my data", QMessageBox.DestructiveRole)
        cancel_btn = final.addButton("Cancel", QMessageBox.RejectRole)
        final.exec()
        clicked = final.clickedButton()
        if clicked == cancel_btn:
            return
        if clicked == copy_btn and not self._export_account_flow():
            return
        try:
            self.session_controller.delete_current_account()
        except Exception as exc:
            QMessageBox.warning(self, "Delete account", str(exc))
            return
        self.accept()

    def _change_account_flow(self) -> None:
        if self.session_controller is None:
            return
        for _ in range(3):
            confirm = QMessageBox(self)
            confirm.setWindowTitle("Change account")
            confirm.setText(
                "Changin the account will delete your data and overwrite it with the data given by the user. please confirm this message 3 times"
            )
            ok_btn = confirm.addButton("okay", QMessageBox.AcceptRole)
            confirm.addButton("cancel", QMessageBox.RejectRole)
            confirm.exec()
            if confirm.clickedButton() != ok_btn:
                return

        ready = QMessageBox(self)
        ready.setWindowTitle("Change account")
        ready.setText(
            "Got it! After you import your data from the other account, we will delete the in-app data and overwrite it with your new account"
        )
        okay_btn = ready.addButton("Okay", QMessageBox.AcceptRole)
        ready.addButton("Cancel", QMessageBox.RejectRole)
        ready.exec()
        if ready.clickedButton() != okay_btn:
            return

        archive_file, _ = QFileDialog.getOpenFileName(self, "Import account zip", "", "Zip files (*.zip)")
        if not archive_file:
            return
        try:
            self.session_controller.import_archive_into_current(Path(archive_file))
        except Exception as exc:
            QMessageBox.warning(self, "Change account", str(exc))
            return
        QMessageBox.information(self, "Change account", "Account data was imported and overwritten successfully.")
        self.accept()

    def _new_account_flow(self) -> None:
        if self.session_controller is None:
            return
        profile = self.datastore.load_profile()
        name = str(profile.get("name", "")).strip() or "Student"
        first = QMessageBox(self)
        first.setWindowTitle("New account")
        first.setText(
            f"Hey, {name}. It is nice to see you making another account. Creating a new account won't affect any of your existing account(s). you can change it anytime by pressing on the app icon > pressing accounts > and pressing on your prefered account"
        )
        yes_btn = first.addButton("yes, I am in!", QMessageBox.AcceptRole)
        first.addButton("cancel", QMessageBox.RejectRole)
        first.exec()
        if first.clickedButton() != yes_btn:
            return

        second = QMessageBox(self)
        second.setWindowTitle("New account")
        second.setText("Nice! New account will be made. The app will open a new profile maker window for you to make a new account.")
        okay_btn = second.addButton("Okay", QMessageBox.AcceptRole)
        second.addButton("nevermind, I changed my mind", QMessageBox.RejectRole)
        second.exec()
        if second.clickedButton() != okay_btn:
            return

        try:
            created = bool(self.session_controller.create_new_account_via_profile(self))
        except Exception as exc:
            QMessageBox.warning(self, "New account", str(exc))
            return
        if created:
            self.accept()

    def _refresh_model_status(self) -> None:
        snap = self.preflight.snapshot(force=True)
        if not snap.cli_available:
            self.ollama_status.setText("Ollama CLI was not found on this system.")
            self.ollama_hint.setText("Install Ollama first, then use this tab to install or refresh ONCard's models.")
        elif snap.error and not snap.installed_tags:
            self.ollama_status.setText("Ollama is installed, but ONCard could not read live model tags right now.")
            self.ollama_hint.setText(snap.error or "Make sure Ollama is running, then refresh model status.")
        else:
            api_text = "API reachable." if snap.api_reachable else "API not responding yet."
            self.ollama_status.setText(f"Ollama is installed. {api_text}")
            self.ollama_hint.setText("Model status below comes from the live Ollama tag list.")

        installing = bool(self._install_worker and self._install_worker.isRunning())
        for key, spec in MODELS.items():
            row = self._model_rows[key]
            status_label = row["status"]
            install_btn = row["install_btn"]
            reinstall_btn = row["reinstall_btn"]
            delete_btn = row["delete_btn"]
            is_installed = self._is_model_installed_ui(snap, key)
            if snap.error and not snap.installed_tags and snap.cli_available:
                status_text = "Saved installed" if is_installed else "Status unavailable"
            else:
                status_text = "Installed" if is_installed else "Not installed"
            status_label.setText(status_text)
            install_btn.setVisible(not is_installed)
            reinstall_btn.setVisible(is_installed)
            delete_btn.setVisible(is_installed)
            enabled = snap.cli_available and not installing
            install_btn.setEnabled(enabled)
            reinstall_btn.setEnabled(enabled)
            delete_btn.setEnabled(enabled)
        self._refresh_text_model_choices(snap)

    def _install_model(self, model_key: str) -> None:
        if self._install_worker and self._install_worker.isRunning():
            return
        if shutil.which("ollama") is None:
            QMessageBox.warning(self, "Ollama missing", "Install Ollama first, then come back to install ONCard's models.")
            return
        if model_key not in MODELS:
            return

        self._install_target_key = model_key
        self._model_worker_action = "install"
        self.install_log.clear()
        self.install_log.append(f"Installing {MODELS[model_key].display_name}...")
        self.install_log.append("Press Ctrl + C twice in the terminal if you need to cancel the running Ollama action.")
        self._set_install_buttons_enabled(False)
        self.save_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)

        worker = ModelInstallWorker([model_key], self.ollama, action="install")
        self._install_worker = worker
        worker.line.connect(self.install_log.append)
        worker.complete.connect(self._on_install_complete)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _delete_model(self, model_key: str) -> None:
        if self._install_worker and self._install_worker.isRunning():
            return
        spec = MODELS.get(model_key)
        if spec is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete model",
            f"Remove {spec.display_name} from Ollama?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return

        self._install_target_key = model_key
        self._model_worker_action = "remove"
        self.install_log.clear()
        self.install_log.append(f"Removing {spec.display_name}...")
        self.install_log.append("Press Ctrl + C twice in the terminal if you need to cancel the running Ollama action.")
        self._set_install_buttons_enabled(False)
        self.save_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)

        worker = ModelInstallWorker([model_key], self.ollama, action="remove")
        self._install_worker = worker
        worker.line.connect(self.install_log.append)
        worker.complete.connect(self._on_install_complete)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_install_complete(self, status: dict) -> None:
        updated_setup = self.datastore.load_setup()
        installed_models = dict(updated_setup.get("installed_models", {}))
        selected_models = list(updated_setup.get("selected_models", []))
        ai_settings = self.datastore.load_ai_settings()

        successes = []
        failures = []
        for key, ok in status.items():
            if self._model_worker_action == "remove":
                if ok:
                    installed_models[key] = False
                    selected_models = [item for item in selected_models if item != key]
                    if str(ai_settings.get("selected_text_llm_key", "")).strip() == key:
                        replacement = ""
                        for llm_key in non_embedding_llm_keys():
                            if llm_key != key and bool(installed_models.get(llm_key, False)):
                                replacement = llm_key
                                break
                        ai_settings["selected_text_llm_key"] = replacement
                    successes.append(MODELS[key].display_name)
                else:
                    failures.append(MODELS[key].display_name)
                continue
            installed_models[key] = bool(ok)
            if ok and key not in selected_models:
                selected_models.append(key)
                successes.append(MODELS[key].display_name)
            elif ok:
                successes.append(MODELS[key].display_name)
            else:
                failures.append(MODELS[key].display_name)

        updated_setup["installed_models"] = installed_models
        updated_setup["selected_models"] = selected_models
        self.datastore.save_setup(updated_setup)
        self.datastore.save_ai_settings(ai_settings)
        self.preflight.invalidate()

        self._install_worker = None
        completed_action = self._model_worker_action
        self._model_worker_action = "install"
        self._set_install_buttons_enabled(True)
        self.save_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self._refresh_model_status()

        if completed_action == "remove" and successes and not failures:
            QMessageBox.information(self, "Model removed", f"{', '.join(successes)} removed successfully.")
        elif successes and not failures:
            QMessageBox.information(self, "Model installed", f"{', '.join(successes)} installed successfully.")
        elif failures and not successes:
            title = "Remove failed" if completed_action == "remove" else "Install failed"
            verb = "remove" if completed_action == "remove" else "install"
            QMessageBox.warning(self, title, f"Could not {verb} {', '.join(failures)}.")
        elif successes and failures:
            QMessageBox.warning(
                self,
                "Action partially failed",
                f"Completed: {', '.join(successes)}\nFailed: {', '.join(failures)}",
            )

    def _set_install_buttons_enabled(self, enabled: bool) -> None:
        cli_installed = shutil.which("ollama") is not None
        for row in self._model_rows.values():
            row["install_btn"].setEnabled(enabled and cli_installed)
            row["reinstall_btn"].setEnabled(enabled and cli_installed)
            row["delete_btn"].setEnabled(enabled and cli_installed)
        self.refresh_models_btn.setEnabled(enabled)

    def _refresh_performance_mode(self) -> None:
        manual = str(self.performance_mode.currentData() or "auto") == "manual"
        self.startup_workers.setEnabled(manual)
        self.background_workers.setEnabled(manual)

    def reject(self) -> None:
        if self._install_worker and self._install_worker.isRunning():
            QMessageBox.information(self, "Install in progress", "Wait for the current model installation to finish first.")
            return
        super().reject()

    @staticmethod
    def _coerce_age(value: object) -> int:
        try:
            age = int(str(value).strip())
        except (TypeError, ValueError):
            return 16
        return max(4, min(99, age))
