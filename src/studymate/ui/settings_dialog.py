from __future__ import annotations

from pathlib import Path
import shutil

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
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
    QVBoxLayout,
    QWidget,
)

from studymate.services.data_store import DataStore
from studymate.services.model_preflight import ModelPreflightService
from studymate.services.model_registry import MODELS, ModelSpec
from studymate.services.ollama_service import OllamaError, OllamaService
from studymate.ui.animated import AnimatedButton, AnimatedComboBox, AnimatedLineEdit, polish_surface
from studymate.workers.install_worker import ModelInstallWorker


FOLLOWUP_CONTEXT_MIN = 8192
REINFORCEMENT_CONTEXT_MIN = 8192
MAX_CONTEXT_LENGTH = 65536
MODEL_ROLE_COPY = {
    "gemma3_4b": "Create cards, Files To Cards, grading, follow-up help, and reinforcement generation.",
    "nomic_embed_text_v2_moe": "Semantic search, recommendations, topic clustering, and adaptive study features.",
}


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

        self.ftc_default_mode = AnimatedComboBox()
        self.ftc_default_mode.addItem("Standard", "standard")
        self.ftc_default_mode.addItem("Force", "force")

        self.ftc_questions_standard = QSpinBox()
        self.ftc_questions_standard.setRange(1, 30)
        self.ftc_questions_standard.setMinimumWidth(140)
        self.ftc_questions_force = QSpinBox()
        self.ftc_questions_force.setRange(1, 30)
        self.ftc_questions_force.setMinimumWidth(140)

        self.ftc_difficulty = AnimatedComboBox()
        self.ftc_difficulty.addItem("Easy", "easy")
        self.ftc_difficulty.addItem("Kinda easy", "kinda easy")
        self.ftc_difficulty.addItem("Normal", "normal")
        self.ftc_difficulty.addItem("Kinda difficult", "kinda difficult")
        self.ftc_difficulty.addItem("Difficult", "difficult")

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
        form.addRow("Follow-up context length", self.followup_ctx)
        form.addRow("Reinforcement context length", self.reinforcement_ctx)
        ai_layout.addLayout(form)

        minimum_note = QLabel(
            f"Minimums: Follow-up {FOLLOWUP_CONTEXT_MIN} tokens, Reinforcement {REINFORCEMENT_CONTEXT_MIN} tokens."
        )
        minimum_note.setObjectName("SmallMeta")
        minimum_note.setWordWrap(True)
        ai_layout.addWidget(minimum_note)
        layout.addWidget(ai_surface)

        layout.addStretch(1)
        scroll.setWidget(host)
        return scroll

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
        button = AnimatedButton("Install")
        button.clicked.connect(lambda _checked=False, key=spec.key: self._install_model(key))
        side_col.addWidget(status_label, 0, Qt.AlignRight)
        side_col.addWidget(button, 0, Qt.AlignRight)

        layout.addLayout(copy_col, 1)
        layout.addLayout(side_col)
        return {
            "container": container,
            "status": status_label,
            "button": button,
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
            button = row["button"]
            status_label = row["status"]
            is_installed = snap.has_model(key)
            if snap.error and not snap.installed_tags and snap.cli_available:
                status_text = "Saved installed" if is_installed else "Status unavailable"
            else:
                status_text = "Installed" if is_installed else "Not installed"
            status_label.setText(status_text)
            button.setText("Reinstall" if is_installed else "Install")
            button.setEnabled(snap.cli_available and not installing)

    def _install_model(self, model_key: str) -> None:
        if self._install_worker and self._install_worker.isRunning():
            return
        if shutil.which("ollama") is None:
            QMessageBox.warning(self, "Ollama missing", "Install Ollama first, then come back to install ONCard's models.")
            return
        if model_key not in MODELS:
            return

        self._install_target_key = model_key
        self.install_log.clear()
        self.install_log.append(f"Installing {MODELS[model_key].display_name}...")
        self._set_install_buttons_enabled(False)
        self.save_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)

        worker = ModelInstallWorker([model_key], self.ollama)
        self._install_worker = worker
        worker.line.connect(self.install_log.append)
        worker.complete.connect(self._on_install_complete)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_install_complete(self, status: dict) -> None:
        updated_setup = self.datastore.load_setup()
        installed_models = dict(updated_setup.get("installed_models", {}))
        selected_models = list(updated_setup.get("selected_models", []))

        successes = []
        failures = []
        for key, ok in status.items():
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
        self.preflight.invalidate()

        self._install_worker = None
        self._set_install_buttons_enabled(True)
        self.save_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self._refresh_model_status()

        if successes and not failures:
            QMessageBox.information(self, "Model installed", f"{', '.join(successes)} installed successfully.")
        elif failures and not successes:
            QMessageBox.warning(self, "Install failed", f"Could not install {', '.join(failures)}.")
        elif successes and failures:
            QMessageBox.warning(
                self,
                "Install partially failed",
                f"Installed: {', '.join(successes)}\nFailed: {', '.join(failures)}",
            )

    def _set_install_buttons_enabled(self, enabled: bool) -> None:
        cli_installed = shutil.which("ollama") is not None
        for row in self._model_rows.values():
            button = row["button"]
            button.setEnabled(enabled and cli_installed)
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
