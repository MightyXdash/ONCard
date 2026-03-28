from __future__ import annotations

import shutil

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QTabBar,
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
    def __init__(self, datastore: DataStore, ollama: OllamaService, preflight: ModelPreflightService, parent=None) -> None:
        super().__init__(parent)
        self.datastore = datastore
        self.ollama = ollama
        self.preflight = preflight
        self._install_worker: ModelInstallWorker | None = None
        self._install_target_key = ""
        self._model_rows: dict[str, dict[str, object]] = {}
        self._sfx_ready = False

        self.setWindowTitle("Settings")
        self._apply_initial_geometry()
        self._build_ui()
        self._install_click_sfx_hooks()
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
        self.age_spin = QSpinBox()
        self.age_spin.setRange(4, 99)
        self.hobbies_edit = AnimatedLineEdit()
        self.grade_combo = AnimatedComboBox()
        self.grade_combo.setEditable(True)
        self.grade_combo.addItems([f"Grade {value}" for value in range(4, 13)])

        form.addRow("Name", self.name_edit)
        form.addRow("Age", self.age_spin)
        form.addRow("Hobby/Interests", self.hobbies_edit)
        form.addRow("Grade", self.grade_combo)

        layout.addWidget(surface)
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
        self.name_edit.setText(str(profile.get("name", "")))
        self.age_spin.setValue(self._coerce_age(profile.get("age")))
        self.hobbies_edit.setText(str(profile.get("hobbies", "")))

        grade = str(profile.get("grade", "")).strip()
        if grade and self.grade_combo.findText(grade) < 0:
            self.grade_combo.addItem(grade)
        if grade:
            self.grade_combo.setCurrentText(grade)

        ai_settings = self.datastore.load_ai_settings()
        self.followup_ctx.setValue(max(FOLLOWUP_CONTEXT_MIN, int(ai_settings.get("followup_context_length", FOLLOWUP_CONTEXT_MIN))))
        self.reinforcement_ctx.setValue(
            max(REINFORCEMENT_CONTEXT_MIN, int(ai_settings.get("reinforcement_context_length", REINFORCEMENT_CONTEXT_MIN)))
        )
        setup = self.datastore.load_setup()
        performance = dict(setup.get("performance", {}))
        self.performance_mode.setCurrentIndex(0 if str(performance.get("mode", "auto")) == "auto" else 1)
        self.startup_workers.setValue(max(1, min(8, int(performance.get("startup_workers", 8) or 8))))
        self.background_workers.setValue(max(1, min(8, int(performance.get("background_workers", 2) or 2))))
        self.warm_cache_checkbox.setChecked(bool(performance.get("warm_cache_on_startup", True)))
        self.reduced_motion_checkbox.setChecked(bool(performance.get("reduced_motion", False)))
        self._refresh_performance_mode()
        self._refresh_model_status()

    def _save(self) -> None:
        profile = self.datastore.load_profile()
        profile["name"] = self.name_edit.text().strip()
        profile["age"] = str(self.age_spin.value())
        profile["hobbies"] = self.hobbies_edit.text().strip()
        profile["grade"] = self.grade_combo.currentText().strip()
        self.datastore.save_profile(profile)

        ai_settings = self.datastore.load_ai_settings()
        ai_settings["followup_context_length"] = max(FOLLOWUP_CONTEXT_MIN, self.followup_ctx.value())
        ai_settings["reinforcement_context_length"] = max(REINFORCEMENT_CONTEXT_MIN, self.reinforcement_ctx.value())
        self.datastore.save_ai_settings(ai_settings)

        setup = self.datastore.load_setup()
        setup["performance"] = {
            "mode": str(self.performance_mode.currentData() or "auto"),
            "startup_workers": self.startup_workers.value(),
            "background_workers": self.background_workers.value(),
            "warm_cache_on_startup": self.warm_cache_checkbox.isChecked(),
            "reduced_motion": self.reduced_motion_checkbox.isChecked(),
        }
        self.datastore.save_setup(setup)
        self.accept()

    def _install_click_sfx_hooks(self) -> None:
        widgets = [self, *self.findChildren(QWidget)]
        for widget in widgets:
            if widget.property("_clickSfxHooked"):
                continue
            widget.setProperty("_clickSfxHooked", True)
            widget.installEventFilter(self)

    def _play_click_sound(self) -> None:
        if not self._sfx_ready:
            return
        parent = self.parentWidget()
        sounds = getattr(parent, "sounds", None)
        if sounds is not None:
            sounds.play("click")

    def eventFilter(self, watched, event) -> bool:
        interactive = (
            QAbstractButton,
            QAbstractSpinBox,
            QComboBox,
            QLineEdit,
            QTextEdit,
            QTabBar,
        )
        if isinstance(watched, interactive):
            if event.type() == QEvent.MouseButtonPress:
                self._play_click_sound()
            elif event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                self._play_click_sound()
        return super().eventFilter(watched, event)

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
