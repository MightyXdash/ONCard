from __future__ import annotations

from pathlib import Path
import shutil
import webbrowser

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap
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
    QStackedWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QStyle,
)

from studymate.services.data_store import DataStore
from studymate.services.model_preflight import ModelPreflightService
from studymate.services.model_registry import MODELS, ModelSpec, non_embedding_llm_keys, resolve_active_text_llm_spec, resolve_active_text_model_tag, text_llm_key_for_model_tag
from studymate.services.ollama_service import OllamaError, OllamaService
from studymate.ui.animated import AnimatedButton, AnimatedComboBox, AnimatedLineEdit, polish_surface
from studymate.ui.wizard import GenderPickerDialog, GradePickerDialog
from studymate.ui.window_effects import polish_windows_window
from studymate.workers.install_worker import ModelInstallWorker
from studymate.workers.mcq_worker import MCQBulkWorker


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
OLLAMA_CLOUD_KEYS_URL = "https://ollama.com/settings/keys"
CHECK_ICON_URL = (Path(__file__).resolve().parents[3] / "assets" / "icons" / "common" / "check_white_small.svg").as_posix()


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


class SettingsPickerButton(AnimatedButton):
    def __init__(self, placeholder: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._placeholder = placeholder
        self._items: list[str] = []
        self._current_text = ""
        self.setObjectName("SettingsPickerButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("disablePressMotion", True)
        self.set_motion_scale_range(0.0)
        self.set_motion_hover_grow(0, 0)
        self.set_motion_lift(0.0)
        self.set_motion_press_scale(0.0)
        self.setMinimumHeight(38)
        self._refresh_text()

    def addItem(self, text: str) -> None:
        clean = str(text or "").strip()
        if clean and clean not in self._items:
            self._items.append(clean)

    def addItems(self, items: list[str]) -> None:
        for item in items:
            self.addItem(item)

    def findText(self, text: str) -> int:
        try:
            return self._items.index(str(text or "").strip())
        except ValueError:
            return -1

    def currentText(self) -> str:
        return self._current_text

    def setCurrentText(self, text: str) -> None:
        self._current_text = str(text or "").strip()
        self._refresh_text()

    def _refresh_text(self) -> None:
        self.setText(self._current_text or self._placeholder)
        self.setProperty("placeholder", not bool(self._current_text))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class FTCPopupChoiceDialog(QDialog):
    def __init__(
        self,
        *,
        parent: QWidget,
        blur_target: QWidget | None,
        title: str,
        options: list[tuple[str, str]],
        current_value: str,
        vertical_choices: bool = False,
        icon_provider=None,
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
        choices_layout = QVBoxLayout(choices_shell) if vertical_choices else QHBoxLayout(choices_shell)
        choices_layout.setContentsMargins(8, 8, 8, 8)
        choices_layout.setSpacing(8)
        for label, value in options_clean:
            button = AnimatedButton(label)
            button.setObjectName("FTCPopupChoiceButton")
            button.setCheckable(True)
            button.setProperty("disablePressMotion", True)
            button.set_motion_scale_range(0.0)
            button.clicked.connect(lambda _checked=False, selected=value: self._set_value(selected))
            if vertical_choices:
                choices_layout.addWidget(button)
            else:
                choices_layout.addWidget(button, 1)
            self._choice_buttons[value] = button
        body.addWidget(choices_shell)
        self._refresh_buttons()
        self.setMinimumWidth(360 if vertical_choices else 500)

    def selected_value(self) -> str:
        return str(self._selected_value or "")

    def exec_with_backdrop(self) -> int:
        self._apply_backdrop()
        try:
            self.adjustSize()
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
            try:
                self._blur_target.setGraphicsEffect(self._previous_effect)
            except RuntimeError:
                try:
                    self._blur_target.setGraphicsEffect(None)
                except RuntimeError:
                    pass
        self._previous_effect = None


class ExportAccountDialog(QDialog):
    def __init__(
        self,
        *,
        parent: QWidget,
        blur_target: QWidget | None,
        icons_root: Path | None,
    ) -> None:
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._download_requested = False
        self._blur_target = blur_target
        self._overlay_target = parent
        self._overlay: QWidget | None = None
        self._previous_effect = None
        self._icons_root = icons_root

        root = QVBoxLayout(self)
        root.setContentsMargins(44, 44, 44, 44)
        root.setSpacing(0)

        card = QFrame(self)
        card.setObjectName("ExportAccountPopupCard")
        card.setStyleSheet(
            """
            QFrame#ExportAccountPopupCard {
                background: rgba(255, 255, 255, 0.96);
                border: 1px solid rgba(220, 228, 236, 0.85);
                border-radius: 28px;
            }
            QToolButton#ExportAccountIconButton {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 12px;
                padding: 0px;
            }
            QToolButton#ExportAccountIconButton:hover {
                background-color: rgba(15, 37, 57, 0.08);
                border-color: rgba(15, 37, 57, 0.08);
            }
            QToolButton#ExportAccountIconButton:pressed {
                background-color: rgba(15, 37, 57, 0.14);
                border-color: rgba(15, 37, 57, 0.14);
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
        body.setContentsMargins(24, 22, 24, 20)
        body.setSpacing(16)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QLabel("Export account")
        title.setObjectName("SectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        body.addLayout(header)

        message = QLabel("We made a copy of your data. Press download to save it to your Downloads folder.")
        message.setObjectName("SectionText")
        message.setWordWrap(True)
        body.addWidget(message)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addStretch(1)
        download_btn = self._icon_button("download", "Download to Downloads")
        download_btn.clicked.connect(self._download)
        actions.addWidget(download_btn)
        close_btn = self._icon_button("cross_two", "Cancel")
        close_btn.clicked.connect(self.reject)
        actions.addWidget(close_btn)
        body.addLayout(actions)

        self.setFixedSize(560, 270)

    def download_requested(self) -> bool:
        return self._download_requested

    def exec_with_backdrop(self) -> int:
        self._apply_backdrop()
        try:
            self._center_on_parent()
            return self.exec()
        finally:
            self._clear_backdrop()

    def _download(self) -> None:
        self._download_requested = True
        self.accept()

    def _icon_button(self, icon_name: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("ExportAccountIconButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setToolTip(tooltip)
        button.setFixedSize(34, 34)
        if self._icons_root is not None:
            button.setIcon(QIcon(str(self._icons_root / "common" / f"{icon_name}.png")))
            button.setIconSize(QSize(15, 15))
        return button

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
            try:
                self._blur_target.setGraphicsEffect(self._previous_effect)
            except RuntimeError:
                try:
                    self._blur_target.setGraphicsEffect(None)
                except RuntimeError:
                    pass
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
        self.paths = getattr(parent, "paths", None)
        self._install_worker: ModelInstallWorker | None = None
        self._mcq_bulk_worker: MCQBulkWorker | None = None
        self._install_target_key = ""
        self._model_rows: dict[str, dict[str, object]] = {}
        self._account_action_buttons: list[QPushButton] = []
        self._sfx_ready = False
        self._last_attention_value = 5
        self._last_ask_ai_emoji_value = 2
        self._model_worker_action = "install"
        self._cloud_model_tags: list[str] = []
        self._loading_cloud_models = False
        self._backdrop_overlay: QWidget | None = None
        self._backdrop_target: QWidget | None = None
        self._backdrop_previous_effect = None
        self._settings_nav_buttons: list[QToolButton] = []
        self._deferred_status_loaded = False

        self.setWindowTitle("Settings")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
        self.setWindowFlag(Qt.WindowType.MSWindowsFixedSizeDialogHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("SettingsDialog")
        self.setModal(True)
        self.setStyleSheet(
            """
            QDialog#SettingsDialog {
                background: transparent;
            }
            QFrame#SettingsWindowShell {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #f8fafc);
                border: 1px solid rgba(203, 213, 225, 0.6);
                border-radius: 24px;
            }
            QStackedWidget#SettingsPages,
            QScrollArea#SettingsScrollArea,
            QScrollArea#SettingsScrollArea > QWidget,
            QScrollArea#SettingsScrollArea > QWidget > QWidget,
            QWidget#SettingsTabCanvas {
                background: transparent;
                border: none;
            }
            QFrame#SettingsCard {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #fafbfc);
                border: 1px solid rgba(203, 213, 225, 0.5);
                border-radius: 18px;
            }
            QFrame#SettingsCard:hover {
                border: 1px solid rgba(148, 163, 184, 0.6);
            }
            QFrame#SettingsSectionCard {
                background: rgba(248, 250, 252, 0.7);
                border: 1px solid rgba(226, 232, 240, 0.6);
                border-radius: 16px;
            }
            QToolButton#SettingsHeaderIconButton,
            QToolButton#SettingsHeaderActionButton {
                background-color: transparent;
                border: 2px solid transparent;
                border-radius: 12px;
                padding: 4px;
                outline: none;
            }
            QToolButton#SettingsHeaderIconButton:hover,
            QToolButton#SettingsHeaderActionButton:hover {
                background-color: rgba(241, 245, 249, 0.8);
                border: 2px solid transparent;
            }
            QToolButton#SettingsHeaderIconButton:checked {
                background-color: #0f2539;
                border: 2px solid transparent;
            }
            QToolButton#SettingsHeaderIconButton:checked:hover {
                background-color: #13314b;
                border: 2px solid transparent;
            }
            QToolButton#SettingsHeaderIconButton:checked:focus {
                border: 2px solid rgba(15, 37, 57, 0.4);
            }
            QToolButton#SettingsHeaderActionButton:pressed {
                background-color: #e2e8f0;
                border: 2px solid transparent;
            }
            QToolButton#SettingsHeaderIconButton:focus,
            QToolButton#SettingsHeaderActionButton:focus {
                border: 2px solid rgba(15, 37, 57, 0.3);
            }
            QToolButton#SettingsNavTab {
                background-color: rgba(241, 245, 249, 0.58);
                border: 1px solid rgba(226, 232, 240, 0.72);
                border-radius: 12px;
                padding: 8px 12px;
                color: #64748b;
                font-size: 13px;
                font-weight: 600;
            }
            QToolButton#SettingsNavTab:hover {
                background-color: rgba(241, 245, 249, 0.9);
                border-color: rgba(203, 213, 225, 0.92);
                color: #334155;
            }
            QToolButton#SettingsNavTab:checked {
                background-color: #0f2539;
                border: 1px solid #0f2539;
                color: #ffffff;
            }
            QPushButton#SettingsPickerButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #f8fafc);
                border: 1.5px solid rgba(203, 213, 225, 0.6);
                border-radius: 12px;
                padding: 10px 14px;
                color: #1e293b;
                font-size: 13px;
                font-weight: 500;
                text-align: left;
            }
            QPushButton#SettingsPickerButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f8fafc, stop:1 #f1f5f9);
                border: 1.5px solid rgba(148, 163, 184, 0.7);
            }
            QPushButton#SettingsPickerButton:pressed {
                background: #e2e8f0;
                border: 1.5px solid rgba(100, 116, 139, 0.8);
            }
            QPushButton#SettingsPickerButton[placeholder="true"] {
                color: #94a3b8;
            }
            """
        )
        self._apply_initial_geometry()
        self._build_ui()
        self._disable_settings_motion_transforms()
        self._load()
        self._sfx_ready = True
        polish_windows_window(self, rounded=False, small_corners=False, remove_border=True)

    def _apply_initial_geometry(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(860, 720)
            return
        available = screen.availableGeometry()
        width = min(860, max(720, available.width() - 120))
        height = min(780, max(620, available.height() - 80))
        self.resize(width, height)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 80)
        root.setSpacing(0)

        shell_surface = QFrame(self)
        shell_surface.setObjectName("SettingsWindowShell")
        polish_surface(shell_surface)
        self._shell_surface = shell_surface
        root.addWidget(shell_surface, 1)
        self._bottom_fade = QWidget(shell_surface)
        self._bottom_fade.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._bottom_fade.setStyleSheet(
            """
            background: qlineargradient(
                x1: 0, y1: 0, x2: 0, y2: 1,
                stop: 0 rgba(248, 250, 252, 0),
                stop: 0.35 rgba(248, 250, 252, 240),
                stop: 1 #f8fafc
            );
            border-bottom-left-radius: 24px;
            border-bottom-right-radius: 24px;
            """
        )
        self._top_fade = QWidget(shell_surface)
        self._top_fade.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._top_fade.setStyleSheet(
            """
            background: qlineargradient(
                x1: 0, y1: 0, x2: 0, y2: 1,
                stop: 0 rgba(248, 250, 252, 160),
                stop: 0.45 rgba(248, 250, 252, 80),
                stop: 1 rgba(248, 250, 252, 0)
            );
            """
        )

        shell = QVBoxLayout(shell_surface)
        shell.setContentsMargins(20, 18, 20, 18)
        shell.setSpacing(16)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QLabel("Settings")
        title.setObjectName("PageTitle")
        title.setStyleSheet(
            """
            QLabel#PageTitle {
                font-family: "Nunito Sans", "Segoe UI Variable Display", "Segoe UI", sans-serif;
                font-size: 26px;
                font-weight: 800;
                color: #0f172a;
                background: transparent;
            }
            """
        )
        header.addWidget(title)
        header.addSpacing(12)

        self.pages = QStackedWidget()
        self.pages.setObjectName("SettingsPages")
        page_specs = [
            ("General", "general", self._build_general_tab()),
            ("AI", "ai", self._build_ai_tab()),
            ("Audio", "stats", self._build_audio_tab()),
            ("Performance", "performance", self._build_performance_tab()),
        ]
        for index, (label, icon_name, page) in enumerate(page_specs):
            self.pages.addWidget(page)
            button = self._header_icon_button(icon_name, label, checkable=True)
            button.clicked.connect(lambda _checked=False, selected=index: self._set_settings_page(selected))
            self._settings_nav_buttons.append(button)
            header.addWidget(button)

        header.addStretch(1)
        self.cancel_btn = self._header_icon_button("cross_two", "Cancel")
        self.save_btn = self._header_icon_button("check", "Save")
        self.cancel_btn.clicked.connect(self.reject)
        self.save_btn.clicked.connect(self._save)
        self.save_btn.setStyleSheet(
            """
            QToolButton#SettingsHeaderActionButton {
                background: transparent;
                border: none;
                border-radius: 10px;
            }
            QToolButton#SettingsHeaderActionButton:hover {
                background: rgba(15, 37, 57, 0.06);
            }
            QToolButton#SettingsHeaderActionButton:pressed {
                background: rgba(15, 37, 57, 0.12);
            }
            """
        )
        self.cancel_btn.setStyleSheet(
            """
            QToolButton#SettingsHeaderActionButton {
                background: transparent;
                border: none;
                border-radius: 10px;
                color: #64748b;
            }
            QToolButton#SettingsHeaderActionButton:hover {
                background: rgba(15, 37, 57, 0.06);
            }
            QToolButton#SettingsHeaderActionButton:pressed {
                background: rgba(15, 37, 57, 0.12);
            }
            """
        )
        header.addWidget(self.cancel_btn)
        header.addWidget(self.save_btn)
        shell.addLayout(header)
        shell.addWidget(self.pages, 1)
        self._set_settings_page(0)

    def _icon_path(self, icon_name: str) -> Path | None:
        parent = self.parentWidget()
        icons_root = getattr(getattr(parent, "paths", None), "icons", None)
        if isinstance(icons_root, Path):
            return icons_root / "common" / f"{icon_name}.png"
        fallback = Path(__file__).resolve().parents[3] / "assets" / "icons" / "common" / f"{icon_name}.png"
        return fallback if fallback.exists() else None

    def _header_icon_button(self, icon_name: str, tooltip: str, *, checkable: bool = False) -> QToolButton:
        button = QToolButton()
        button.setObjectName("SettingsNavTab" if checkable else "SettingsHeaderActionButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly if checkable else Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setToolTip(tooltip)
        button.setCheckable(checkable)
        button.setAutoRaise(False)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if checkable:
            button.setText(tooltip)
            button.setFixedSize(136, 40)
        else:
            button.setFixedSize(36, 36)
        icon_path = self._icon_path(icon_name)
        if icon_path is not None:
            if checkable:
                icon_size = QSize(18, 18)
                icon = QIcon(str(icon_path))
                button.setIcon(icon)
                button.setIconSize(icon_size)
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            else:
                icon_size = QSize(16, 16)
                padded = self._header_padded_icon(icon_path, icon_size)
                button.setIcon(padded if not padded.isNull() else QIcon(str(icon_path)))
                button.setIconSize(icon_size)
        return button

    def _header_padded_icon(self, icon_path: Path, target_size: QSize) -> QIcon:
        source = QPixmap(str(icon_path))
        if source.isNull():
            return QIcon(str(icon_path))

        width = max(1, int(target_size.width()))
        height = max(1, int(target_size.height()))

        # Keep a transparent inset so tiny antialias pixels do not touch icon bounds.
        inner = QSize(max(1, width - 2), max(1, height - 2))
        scaled = source.scaled(inner, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

        canvas = QPixmap(width, height)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        x = (width - scaled.width()) // 2
        y = (height - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        painter.end()
        return QIcon(canvas)

    def _set_settings_page(self, index: int) -> None:
        self._reset_settings_transient_state()
        self.pages.setCurrentIndex(index)
        for button_index, button in enumerate(self._settings_nav_buttons):
            button.setChecked(button_index == index)
        self._reset_settings_transient_state()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        polish_windows_window(self, rounded=False, small_corners=False, remove_border=True)
        self._position_scroll_fades()
        if not self._deferred_status_loaded:
            self._deferred_status_loaded = True
            QTimer.singleShot(250, self._refresh_model_status)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_scroll_fades()

    def _position_scroll_fades(self) -> None:
        if not hasattr(self, "_bottom_fade") or not hasattr(self, "_top_fade") or not hasattr(self, "_shell_surface"):
            return
        bottom_fade_height = 78
        top_fade_height = 34
        inset = 1
        if hasattr(self, "pages"):
            top_left = self.pages.mapTo(self._shell_surface, QPoint(0, 0))
            fade_width = self.pages.width()
            fade_x = top_left.x()
            top_y = top_left.y()
            bottom_y = top_left.y() + self.pages.height() - bottom_fade_height
        else:
            fade_width = max(0, self._shell_surface.width() - (inset * 2))
            fade_x = inset
            top_y = inset
            bottom_y = self._shell_surface.height() - bottom_fade_height - inset
        self._top_fade.setGeometry(fade_x, max(inset, top_y), max(0, fade_width), top_fade_height)
        self._bottom_fade.setGeometry(
            fade_x,
            max(inset, bottom_y),
            max(0, fade_width),
            bottom_fade_height,
        )
        self._top_fade.raise_()
        self._bottom_fade.raise_()

    def _disable_settings_motion_transforms(self) -> None:
        """Disable scale/lift/grow motion in Settings to prevent hover jitter."""
        for widget in self.findChildren(QWidget):
            if hasattr(widget, "set_motion_scale_range"):
                widget.set_motion_scale_range(0.0)
            if hasattr(widget, "set_motion_lift"):
                widget.set_motion_lift(0.0)
            if hasattr(widget, "set_motion_press_scale"):
                widget.set_motion_press_scale(0.0)
            if hasattr(widget, "set_motion_hover_grow"):
                widget.set_motion_hover_grow(0, 0)
            # Covers AnimatedButton / AnimatedToolButton-style press offset logic.
            if widget.property("disablePressMotion") is not None or hasattr(widget, "_press_animation"):
                widget.setProperty("disablePressMotion", True)
            if isinstance(widget, (QPushButton, QToolButton)):
                widget.setProperty("disablePressMotion", True)

    def _reset_settings_transient_state(self) -> None:
        """Clear stale hover/focus dynamic state when pages are swapped in/out."""
        focus_widget = self.focusWidget()
        if isinstance(focus_widget, QWidget) and (focus_widget is self or self.isAncestorOf(focus_widget)):
            focus_widget.clearFocus()

        for widget in self.findChildren(QWidget):
            changed = False
            if widget.property("hovered") is not None:
                widget.setProperty("hovered", False)
                changed = True
            if widget.property("focusRing") is not None:
                widget.setProperty("focusRing", False)
                changed = True
            if changed:
                style = widget.style()
                style.unpolish(widget)
                style.polish(widget)
                widget.update()

    def exec(self) -> int:
        self._apply_backdrop()
        try:
            self._center_on_parent()
            return super().exec()
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

    def _resolve_backdrop_target(self) -> QWidget | None:
        parent_widget = self.parentWidget()
        if parent_widget is None:
            return None
        app_shell = getattr(parent_widget, "_app_shell", None)
        if isinstance(app_shell, QWidget):
            return app_shell
        return parent_widget

    def _apply_backdrop(self) -> None:
        target = self._resolve_backdrop_target()
        parent_widget = self.parentWidget()
        if target is None or parent_widget is None:
            return
        self._backdrop_target = target
        self._backdrop_previous_effect = target.graphicsEffect()
        blur = QGraphicsBlurEffect(target)
        blur.setBlurRadius(22.0)
        target.setGraphicsEffect(blur)

        overlay = QWidget(parent_widget)
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        overlay.setStyleSheet("background: rgba(15, 23, 42, 0.18);")
        top_left = target.mapTo(parent_widget, QPoint(0, 0))
        overlay.setGeometry(QRect(top_left, target.size()))
        overlay.show()
        overlay.raise_()
        self._backdrop_overlay = overlay

    def _clear_backdrop(self) -> None:
        if self._backdrop_overlay is not None:
            self._backdrop_overlay.hide()
            self._backdrop_overlay.deleteLater()
            self._backdrop_overlay = None
        if self._backdrop_target is not None:
            try:
                self._backdrop_target.setGraphicsEffect(self._backdrop_previous_effect)
            except RuntimeError:
                pass
        self._backdrop_target = None
        self._backdrop_previous_effect = None

    def _settings_scroll_area(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("SettingsScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setViewportMargins(0, 8, 16, 0)
        scroll.viewport().setStyleSheet("background: transparent;")
        return scroll

    def _settings_card(self, layout_type: QVBoxLayout | QFormLayout | None = None, *, padding: int = 22) -> tuple[QFrame, QVBoxLayout | QFormLayout]:
        surface = QFrame()
        surface.setObjectName("SettingsCard")
        surface.setStyleSheet(
            """
            QFrame#SettingsCard {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #fafbfc);
                border: 1px solid rgba(203, 213, 225, 0.5);
                border-radius: 18px;
            }
            """
        )
        if layout_type is QFormLayout:
            layout = QFormLayout(surface)
            layout.setContentsMargins(padding, padding, padding, padding)
            layout.setHorizontalSpacing(18)
            layout.setVerticalSpacing(16)
            layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            layout.setFormAlignment(Qt.AlignTop)
        else:
            layout = QVBoxLayout(surface)
            layout.setContentsMargins(padding, padding, padding, padding)
            layout.setSpacing(12)
        return surface, layout

    def _settings_section_card(self, layout_type: QVBoxLayout | QFormLayout | None = None, *, padding: int = 20) -> tuple[QFrame, QVBoxLayout | QFormLayout]:
        surface = QFrame()
        surface.setObjectName("SettingsSectionCard")
        surface.setStyleSheet(
            """
            QFrame#SettingsSectionCard {
                background: rgba(248, 250, 252, 0.7);
                border: 1px solid rgba(226, 232, 240, 0.6);
                border-radius: 16px;
            }
            """
        )
        if layout_type is QFormLayout:
            layout = QFormLayout(surface)
            layout.setContentsMargins(padding, padding, padding, padding)
            layout.setHorizontalSpacing(16)
            layout.setVerticalSpacing(14)
            layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            layout.setFormAlignment(Qt.AlignTop)
        else:
            layout = QVBoxLayout(surface)
            layout.setContentsMargins(padding, padding, padding, padding)
            layout.setSpacing(10)
        return surface, layout

    def _build_general_tab(self) -> QWidget:
        scroll = self._settings_scroll_area()

        host = QWidget()
        host.setObjectName("SettingsTabCanvas")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 4, 82)
        layout.setSpacing(20)

        intro = QLabel("Update the basic student profile ONCard uses when generating and grading responses.")
        intro.setObjectName("SectionText")
        intro.setWordWrap(True)
        intro.setStyleSheet(
            """
            QLabel#SectionText {
                font-size: 14px;
                line-height: 1.6;
                color: #475569;
            }
            """
        )
        layout.addWidget(intro)

        # Profile card
        surface, form = self._settings_card(layout_type=QFormLayout)
        form_title = QLabel("Profile")
        form_title.setObjectName("SectionTitle")
        form_title.setStyleSheet(
            """
            QLabel#SectionTitle {
                font-family: "Nunito Sans", "Segoe UI Variable Display", "Segoe UI", sans-serif;
                font-size: 18px;
                font-weight: 700;
                color: #0f172a;
                background: transparent;
                border: none;
            }
            """
        )
        form_title.setStyleSheet(
            "QLabel#SectionTitle { font-size: 18px; font-weight: 700; color: #0f172a; background: transparent; border: none; padding: 0px 0px 12px 0px; }"
        )
        form.addRow(form_title)

        self.name_edit = AnimatedLineEdit()
        self.profile_name_edit = AnimatedLineEdit()
        self.age_spin = QSpinBox()
        self.age_spin.setRange(4, 99)
        self.hobbies_edit = AnimatedLineEdit()
        self.grade_combo = SettingsPickerButton("Choose grade")
        self.grade_combo.addItems([f"Grade {value}" for value in range(3, 13)])
        self.grade_combo.setCurrentText("Grade 3")
        self.grade_combo.clicked.connect(self._open_grade_picker)
        self.gender_combo = SettingsPickerButton("Choose gender")
        self.gender_combo.addItems(["Male", "Female", "Custom"])
        self.gender_combo.clicked.connect(self._open_gender_picker)
        self.gender_custom_edit = AnimatedLineEdit()
        self.gender_custom_edit.setMaxLength(64)
        self.gender_custom_edit.setPlaceholderText("Gender | Pronoun(s)")
        self.gender_custom_edit.setVisible(False)
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
        self.attention_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.attention_slider.setRange(1, 10)
        self.attention_slider.setSingleStep(1)
        self.attention_slider.setPageStep(1)
        self.attention_slider.setValue(5)
        self.attention_slider.setStyleSheet(
            """
            QSlider#SettingsAttentionSlider {
                min-height: 24px;
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
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
                background: #0f2539;
            }
            QSlider#SettingsAttentionSlider::handle:horizontal:hover {
                background: #13314b;
            }
            QSlider#SettingsAttentionSlider::handle:horizontal:pressed {
                background: #1a4466;
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

        # Account actions card
        account_surface, account_layout = self._settings_section_card()
        account_title = QLabel("Profile account actions")
        account_title.setObjectName("SectionTitle")
        account_title.setStyleSheet("QLabel#SectionTitle { font-size: 16px; font-weight: 700; color: #0f172a; background: transparent; border: none; padding: 0px 0px 8px 0px; }")
        account_note = QLabel("Manage your account directly from profile settings.")
        account_note.setObjectName("SectionText")
        account_note.setWordWrap(True)
        account_note.setStyleSheet("QLabel#SectionText { font-size: 13px; color: #64748b; }")
        account_layout.addWidget(account_title)
        account_layout.addWidget(account_note)

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 4, 0, 0)
        actions_row.setSpacing(12)
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
                    color: #64748b;
                    font-size: 12px;
                    padding: 4px 8px;
                    text-align: left;
                    font-weight: 500;
                    border-radius: 6px;
                }
                QPushButton#SettingsTinyLink:hover {
                    color: #0f2539;
                    background: rgba(15, 37, 57, 0.05);
                }
                QPushButton#SettingsTinyLink:pressed {
                    background: rgba(15, 37, 57, 0.10);
                }
                """
            )
            actions_row.addWidget(button, 0, Qt.AlignLeft)
            self._account_action_buttons.append(button)
        actions_row.addStretch(1)
        account_layout.addLayout(actions_row)
        layout.addWidget(account_surface)

        # FTC card
        ftc_surface, ftc_layout = self._settings_card()
        ftc_title = QLabel("FTC")
        ftc_title.setObjectName("SectionTitle")
        ftc_title.setStyleSheet("QLabel#SectionTitle { font-size: 18px; font-weight: 700; color: #0f172a; background: transparent; border: none; padding: 0px 0px 8px 0px; }")
        ftc_note = QLabel("Default Files To Cards settings. Question counts are capped by available units per run.")
        ftc_note.setObjectName("SectionText")
        ftc_note.setWordWrap(True)
        ftc_note.setStyleSheet("QLabel#SectionText { font-size: 13px; color: #64748b; }")
        ftc_layout.addWidget(ftc_title)
        ftc_layout.addWidget(ftc_note)

        ftc_form = QFormLayout()
        ftc_form.setHorizontalSpacing(18)
        ftc_form.setVerticalSpacing(16)
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
        ftc_hint.setStyleSheet("QLabel#SmallMeta { font-size: 12px; color: #94a3b8; margin-top: 8px; }")
        ftc_layout.addWidget(ftc_hint)

        layout.addWidget(ftc_surface)

        # MCQ card
        mcq_surface, mcq_layout = self._settings_card()
        mcq_title = QLabel("MCQ")
        mcq_title.setObjectName("SectionTitle")
        mcq_title.setStyleSheet("QLabel#SectionTitle { font-size: 18px; font-weight: 700; color: #0f172a; background: transparent; border: none; padding: 0px 0px 8px 0px; }")
        mcq_note = QLabel("Turn saved cards into multiple choice practice with short, similar answer choices.")
        mcq_note.setObjectName("SectionText")
        mcq_note.setWordWrap(True)
        mcq_note.setStyleSheet("QLabel#SectionText { font-size: 13px; color: #64748b; }")
        mcq_layout.addWidget(mcq_title)
        mcq_layout.addWidget(mcq_note)

        self.mcq_enabled_checkbox = QCheckBox("Enable Cards to MCQ")
        self.mcq_enabled_checkbox.setStyleSheet(
            """
            QCheckBox {
                font-size: 14px;
                color: #334155;
                spacing: 10px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 6px;
                border: 2px solid #cbd5e1;
                background: #ffffff;
            }
            QCheckBox::indicator:hover {
                border: 2px solid #94a3b8;
            }
            QCheckBox::indicator:checked {
                background: #0f2539;
                border: 2px solid #0f2539;
                image: url("__CHECK_ICON__");
            }
            """.replace("__CHECK_ICON__", CHECK_ICON_URL)
        )
        mcq_layout.addWidget(self.mcq_enabled_checkbox)

        mcq_difficulty_form = QFormLayout()
        mcq_difficulty_form.setHorizontalSpacing(18)
        mcq_difficulty_form.setVerticalSpacing(12)
        mcq_difficulty_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.mcq_difficulty = PopupMenuComboBox()
        mcq_difficulty_options = [
            ("Easier", "easier"),
            ("Standard", "standard"),
            ("Slightly harder", "slightly_harder"),
            ("Harder", "harder"),
            ("Much harder", "much_harder"),
        ]
        for label, value in mcq_difficulty_options:
            self.mcq_difficulty.addItem(label, value)
        self.mcq_difficulty.set_popup_handler(
            lambda: self._open_combo_choice_picker(
                title="MCQ difficulty",
                control=self.mcq_difficulty,
                fallback_value="slightly_harder",
            )
        )
        mcq_difficulty_form.addRow("MCQ difficulty", self.mcq_difficulty)
        mcq_layout.addLayout(mcq_difficulty_form)

        mcq_action_row = QHBoxLayout()
        self.cards_to_mcq_btn = AnimatedButton("Cards to MCQ")
        self.cards_to_mcq_btn.setStyleSheet(
            """
            QPushButton {
                background: #0f2539;
                color: #ffffff;
                border: none;
                border-radius: 10px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #13314b;
            }
            QPushButton:pressed {
                background: #1a4466;
            }
            QPushButton:disabled {
                background: #cbd5e1;
                color: #94a3b8;
            }
            """
        )
        self.cards_to_mcq_btn.clicked.connect(self._run_cards_to_mcq)
        self.mcq_status_label = QLabel("Generate choices now, or let the MCQ tab make them when needed.")
        self.mcq_status_label.setObjectName("SmallMeta")
        self.mcq_status_label.setWordWrap(True)
        self.mcq_status_label.setStyleSheet("QLabel#SmallMeta { font-size: 12px; color: #94a3b8; }")
        mcq_action_row.addWidget(self.cards_to_mcq_btn, 0)
        mcq_action_row.addWidget(self.mcq_status_label, 1)
        mcq_layout.addLayout(mcq_action_row)
        layout.addWidget(mcq_surface)

        stats_surface, stats_form = self._settings_card(layout_type=QFormLayout)
        stats_title = QLabel("Stats defaults")
        stats_title.setObjectName("SectionTitle")
        stats_title.setStyleSheet("QLabel#SectionTitle { font-size: 18px; font-weight: 700; color: #0f172a; background: transparent; border: none; padding: 0px 0px 12px 0px; }")
        stats_form.addRow(stats_title)

        self.stats_default_range = PopupMenuComboBox()
        self.stats_default_range.addItem("Hourly", "hourly")
        self.stats_default_range.addItem("Daily 3 days", "daily")
        self.stats_default_range.addItem("Weekly", "weekly")
        self.stats_default_range.addItem("2 Weeks", "2weeks")
        self.stats_default_range.addItem("Monthly", "monthly")
        self.stats_default_range.set_popup_handler(
            lambda: self._open_combo_choice_picker(
                title="Default time range",
                control=self.stats_default_range,
                fallback_value="daily",
            )
        )
        stats_form.addRow("Default time range", self.stats_default_range)
        layout.addWidget(stats_surface)

        stats_note = QLabel("This only sets the initial selection. You can still switch range in View stats anytime.")
        stats_note.setObjectName("SmallMeta")
        stats_note.setWordWrap(True)
        stats_note.setStyleSheet("QLabel#SmallMeta { font-size: 12px; color: #94a3b8; }")
        layout.addWidget(stats_note)

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
            vertical_choices=True,
        )

    def _open_ftc_choice_picker(
        self,
        *,
        title: str,
        control: QComboBox,
        fallback_value: str,
        vertical_choices: bool = False,
    ) -> None:
        self._open_combo_choice_picker(
            title=title,
            control=control,
            fallback_value=fallback_value,
            vertical_choices=vertical_choices,
        )

    def _run_cards_to_mcq(self) -> None:
        if self._mcq_bulk_worker is not None:
            return
        cards = self.datastore.list_all_cards()
        if not cards:
            self.mcq_status_label.setText("No cards are available yet.")
            return
        self.mcq_enabled_checkbox.setChecked(True)
        setup = self.datastore.load_setup()
        setup["mcq"] = {
            "enabled": True,
            "difficulty": str(self.mcq_difficulty.currentData() or "slightly_harder"),
        }
        self.datastore.save_setup(setup)
        ai_settings = self.datastore.load_ai_settings()
        model_spec = resolve_active_text_llm_spec(ai_settings)
        if not self.preflight.require_model(model_spec.key, parent=self, feature_name="Cards to MCQ"):
            return
        mcq_difficulty = str(self.mcq_difficulty.currentData() or "slightly_harder")
        worker = MCQBulkWorker(
            cards=cards,
            datastore=self.datastore,
            ollama=self.ollama,
            model=resolve_active_text_model_tag(ai_settings),
            profile_context=self.datastore.load_profile(),
            difficulty=mcq_difficulty,
        )
        self._mcq_bulk_worker = worker
        self.cards_to_mcq_btn.setEnabled(False)
        self.mcq_status_label.setText("Generating MCQs...")
        worker.progress.connect(self._on_cards_to_mcq_progress)
        worker.finished.connect(self._on_cards_to_mcq_finished)
        worker.failed.connect(self._on_cards_to_mcq_failed)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.start()

    def _on_cards_to_mcq_progress(self, current: int, total: int, generated: int, failed: int) -> None:
        self.mcq_status_label.setText(f"Generating MCQs... {current}/{total} | Generated {generated} | Failed {failed}")

    def _on_cards_to_mcq_finished(self, generated: int, skipped: int, failed: int) -> None:
        self._mcq_bulk_worker = None
        self.cards_to_mcq_btn.setEnabled(True)
        self.mcq_status_label.setText(f"MCQ generation finished. Generated {generated}, skipped {skipped}, failed {failed}.")

    def _on_cards_to_mcq_failed(self, message: str) -> None:
        self._mcq_bulk_worker = None
        self.cards_to_mcq_btn.setEnabled(True)
        self.mcq_status_label.setText(f"MCQ generation failed: {message}")

    def _open_combo_choice_picker(
        self,
        *,
        title: str,
        control: QComboBox,
        fallback_value: str,
        vertical_choices: bool = True,
    ) -> None:
        options: list[tuple[str, str]] = []
        for index in range(control.count()):
            label = str(control.itemText(index)).strip()
            value = str(control.itemData(index) or "").strip()
            if label and value:
                options.append((label, value))
        if not options:
            return
        current_value = str(control.currentData() or fallback_value).strip() or fallback_value
        parent_widget = self
        blur_target = self._settings_popup_blur_target()
        app_window = self.window() if isinstance(self.window(), QWidget) else self
        icon_provider = getattr(app_window, "icons", None) or getattr(self.parentWidget(), "icons", None)
        picker = FTCPopupChoiceDialog(
            parent=parent_widget,
            blur_target=blur_target,
            title=title,
            options=options,
            current_value=current_value,
            vertical_choices=vertical_choices,
            icon_provider=icon_provider,
        )
        if picker.exec_with_backdrop() != QDialog.DialogCode.Accepted:
            return
        selected = picker.selected_value().strip() or fallback_value
        selected_index = control.findData(selected)
        if selected_index >= 0:
            control.setCurrentIndex(selected_index)

    def _open_grade_picker(self) -> None:
        if not self.grade_combo.isEnabled():
            return
        options = [f"Grade {value}" for value in range(3, 13)]
        current_value = self.grade_combo.currentText().strip()
        selected = GradePickerDialog(
            parent=self,
            blur_target=self._settings_popup_blur_target(),
            anchor=self.grade_combo,
            options=options,
            current_value=current_value,
        ).exec_with_backdrop()
        if not selected:
            return
        if self.grade_combo.findText(selected) < 0:
            self.grade_combo.addItem(selected)
        self.grade_combo.setCurrentText(selected)
        self.grade_combo.setFocus()

    def _open_gender_picker(self) -> None:
        if not self.gender_combo.isEnabled():
            return
        selected = GenderPickerDialog(
            parent=self,
            blur_target=self._settings_popup_blur_target(),
            current_value=self._effective_gender_value(),
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
        self._on_gender_mode_changed()
        self.gender_combo.setFocus()

    def _settings_popup_blur_target(self) -> QWidget:
        return self.pages if hasattr(self, "pages") and isinstance(self.pages, QWidget) else self

    def _build_ai_tab(self) -> QWidget:
        scroll = self._settings_scroll_area()

        host = QWidget()
        host.setObjectName("SettingsTabCanvas")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 4, 82)
        layout.setSpacing(20)

        # Cloud service card
        cloud_surface, cloud_layout = self._settings_card()
        cloud_title = QLabel("Ollama cloud")
        cloud_title.setObjectName("SectionTitle")
        cloud_title.setStyleSheet("QLabel#SectionTitle { font-size: 18px; font-weight: 700; color: #0f172a; background: transparent; border: none; padding: 0px 0px 8px 0px; }")
        cloud_note = QLabel(
            "Use Ollama Cloud inference with your API key. Cloud mode is off by default. "
            "When enabled, cloud inference overrides local AI text-model selection until turned off. "
            "Embedding stays local."
        )
        cloud_note.setObjectName("SectionText")
        cloud_note.setWordWrap(True)
        cloud_note.setStyleSheet("QLabel#SectionText { font-size: 13px; color: #64748b; }")
        cloud_layout.addWidget(cloud_title)
        cloud_layout.addWidget(cloud_note)

        cloud_form = QFormLayout()
        cloud_form.setHorizontalSpacing(18)
        cloud_form.setVerticalSpacing(14)
        cloud_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.cloud_enabled_checkbox = QCheckBox("Enable cloud service")
        self.cloud_enabled_checkbox.setStyleSheet(
            """
            QCheckBox {
                font-size: 14px;
                color: #334155;
                spacing: 10px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 6px;
                border: 2px solid #cbd5e1;
                background: #ffffff;
            }
            QCheckBox::indicator:hover {
                border: 2px solid #94a3b8;
            }
            QCheckBox::indicator:checked {
                background: #0f2539;
                border: 2px solid #0f2539;
                image: url("__CHECK_ICON__");
            }
            """.replace("__CHECK_ICON__", CHECK_ICON_URL)
        )
        self.cloud_enabled_checkbox.toggled.connect(self._on_cloud_mode_toggled)
        self.cloud_api_key_edit = AnimatedLineEdit()
        self.cloud_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.cloud_api_key_edit.setPlaceholderText("Paste Ollama API key")
        self.cloud_api_key_edit.textChanged.connect(self._on_cloud_api_key_changed)
        self.cloud_model_combo = PopupMenuComboBox()
        self.cloud_model_combo.setEnabled(False)
        self.cloud_model_combo.set_popup_handler(
            lambda: self._open_combo_choice_picker(
                title="Cloud model variant",
                control=self.cloud_model_combo,
                fallback_value=str(self.cloud_model_combo.currentData() or ""),
            )
        )

        cloud_form.addRow("Cloud inference", self.cloud_enabled_checkbox)
        cloud_form.addRow("API key", self.cloud_api_key_edit)
        cloud_form.addRow("Cloud model variant", self.cloud_model_combo)
        cloud_layout.addLayout(cloud_form)

        cloud_actions = QHBoxLayout()
        cloud_actions.setContentsMargins(0, 6, 0, 0)
        cloud_actions.setSpacing(10)
        self.open_cloud_keys_btn = AnimatedButton("Open API key page")
        self.open_cloud_keys_btn.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                color: #0f2539;
                border: 1.5px solid #0f2539;
                border-radius: 10px;
                padding: 7px 14px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: rgba(15, 37, 57, 0.08);
            }
            QPushButton:pressed {
                background: rgba(15, 37, 57, 0.15);
            }
            """
        )
        self.open_cloud_keys_btn.clicked.connect(self._open_ollama_cloud_keys)
        self.refresh_cloud_models_btn = AnimatedButton("Load cloud models")
        self.refresh_cloud_models_btn.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                color: #0f2539;
                border: 1.5px solid #0f2539;
                border-radius: 10px;
                padding: 7px 14px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: rgba(15, 37, 57, 0.08);
            }
            QPushButton:pressed {
                background: rgba(15, 37, 57, 0.15);
            }
            """
        )
        self.refresh_cloud_models_btn.clicked.connect(lambda: self._refresh_cloud_models(force=True))
        cloud_actions.addWidget(self.open_cloud_keys_btn)
        cloud_actions.addWidget(self.refresh_cloud_models_btn)
        cloud_actions.addStretch(1)
        cloud_layout.addLayout(cloud_actions)

        self.cloud_status = QLabel("")
        self.cloud_status.setObjectName("SmallMeta")
        self.cloud_status.setWordWrap(True)
        self.cloud_status.setStyleSheet("QLabel#SmallMeta { font-size: 12px; color: #94a3b8; margin-top: 8px; }")
        cloud_layout.addWidget(self.cloud_status)
        layout.addWidget(cloud_surface)

        runtime_surface, runtime_layout = self._settings_section_card()
        runtime_title = QLabel("Ollama runtime")
        runtime_title.setObjectName("SectionTitle")
        runtime_title.setStyleSheet("QLabel#SectionTitle { font-size: 16px; font-weight: 700; color: #0f172a; background: transparent; border: none; padding: 0px 0px 6px 0px; }")
        self.ollama_status = QLabel("")
        self.ollama_status.setObjectName("SectionText")
        self.ollama_status.setWordWrap(True)
        self.ollama_status.setStyleSheet("QLabel#SectionText { font-size: 13px; color: #64748b; }")
        self.ollama_hint = QLabel("")
        self.ollama_hint.setObjectName("SmallMeta")
        self.ollama_hint.setWordWrap(True)
        self.ollama_hint.setStyleSheet("QLabel#SmallMeta { font-size: 12px; color: #94a3b8; }")
        self.refresh_models_btn = AnimatedButton("Refresh model status")
        self.refresh_models_btn.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                color: #0f2539;
                border: 1.5px solid #0f2539;
                border-radius: 10px;
                padding: 7px 14px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: rgba(15, 37, 57, 0.08);
            }
            QPushButton:pressed {
                background: rgba(15, 37, 57, 0.15);
            }
            """
        )
        self.refresh_models_btn.clicked.connect(self._refresh_model_status)
        runtime_layout.addWidget(runtime_title)
        runtime_layout.addWidget(self.ollama_status)
        runtime_layout.addWidget(self.ollama_hint)
        runtime_layout.addWidget(self.refresh_models_btn, 0, Qt.AlignLeft)
        layout.addWidget(runtime_surface)

        models_surface, models_layout = self._settings_card()
        models_title = QLabel("Installed Ollama models")
        models_title.setObjectName("SectionTitle")
        models_title.setStyleSheet("QLabel#SectionTitle { font-size: 18px; font-weight: 700; color: #0f172a; background: transparent; border: none; padding: 0px 0px 6px 0px; }")
        models_note = QLabel("These are the Ollama models ONCard currently uses.")
        models_note.setObjectName("SectionText")
        models_note.setWordWrap(True)
        models_note.setStyleSheet("QLabel#SectionText { font-size: 13px; color: #64748b; }")
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
        self.install_log.setStyleSheet(
            """
            QTextEdit {
                background: #f8fafc;
                border: 1px solid #e2e8f0;
                border-radius: 12px;
                padding: 12px;
                color: #475569;
                font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
                font-size: 12px;
            }
            """
        )
        models_layout.addWidget(self.install_log)
        layout.addWidget(models_surface)

        ai_surface, ai_layout = self._settings_card()
        ai_title = QLabel("AI features")
        ai_title.setObjectName("SectionTitle")
        ai_title.setStyleSheet("QLabel#SectionTitle { font-size: 18px; font-weight: 700; color: #0f172a; background: transparent; border: none; padding: 0px 0px 8px 0px; }")
        ai_note = QLabel(
            "Context lengths can only be increased above the shipped defaults. Higher values can use more memory and may slow requests on weaker devices."
        )
        ai_note.setObjectName("SectionText")
        ai_note.setWordWrap(True)
        ai_note.setStyleSheet("QLabel#SectionText { font-size: 13px; color: #64748b; }")
        ai_layout.addWidget(ai_title)
        ai_layout.addWidget(ai_note)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(16)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.followup_ctx = QSpinBox()
        self.followup_ctx.setRange(FOLLOWUP_CONTEXT_MIN, MAX_CONTEXT_LENGTH)
        self.followup_ctx.setSingleStep(1024)
        self.followup_ctx.setSuffix(" tokens")
        self.reinforcement_ctx = QSpinBox()
        self.reinforcement_ctx.setRange(REINFORCEMENT_CONTEXT_MIN, MAX_CONTEXT_LENGTH)
        self.reinforcement_ctx.setSingleStep(1024)
        self.reinforcement_ctx.setSuffix(" tokens")
        self.ask_ai_tone = PopupMenuComboBox()
        for label, value in ASK_AI_TONE_OPTIONS:
            self.ask_ai_tone.addItem(label, value)
        self.ask_ai_tone.set_popup_handler(
            lambda: self._open_combo_choice_picker(
                title="Ask AI tone",
                control=self.ask_ai_tone,
                fallback_value="warm",
            )
        )
        self.ask_ai_emoji_slider = QSlider(Qt.Orientation.Horizontal)
        self.ask_ai_emoji_slider.setObjectName("SettingsAskAiEmojiSlider")
        self.ask_ai_emoji_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
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
                background: #d4deea;
            }
            QSlider#SettingsAskAiEmojiSlider::sub-page:horizontal {
                border-radius: 3px;
                background: #0f2539;
            }
            QSlider#SettingsAskAiEmojiSlider::add-page:horizontal {
                border-radius: 3px;
                background: #d4deea;
            }
            QSlider#SettingsAskAiEmojiSlider::handle:horizontal {
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
                background: #0f2539;
            }
            QSlider#SettingsAskAiEmojiSlider::handle:horizontal:hover {
                background: #13314b;
            }
            QSlider#SettingsAskAiEmojiSlider::handle:horizontal:pressed {
                background: #1a4466;
            }
            """
        )
        self.ask_ai_emoji_slider.valueChanged.connect(self._on_ask_ai_emoji_changed)
        self.ask_ai_emoji_value = QLabel(ASK_AI_EMOJI_LABELS[2])
        self.ask_ai_emoji_value.setObjectName("SectionText")
        self.ask_ai_emoji_value.setStyleSheet("QLabel#SectionText { font-size: 13px; color: #475569; }")
        self.selected_text_llm = PopupMenuComboBox()
        self.selected_text_llm.set_popup_handler(
            lambda: self._open_combo_choice_picker(
                title="AI text model",
                control=self.selected_text_llm,
                fallback_value=str(self.selected_text_llm.currentData() or ""),
            )
        )
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
        minimum_note.setStyleSheet("QLabel#SmallMeta { font-size: 12px; color: #94a3b8; margin-top: 8px; }")
        ai_layout.addWidget(minimum_note)
        tone_note = QLabel(
            "Ask AI can use a saved tone preset and emoji intensity. The model still adapts to the situation, but this sets the default style."
        )
        tone_note.setObjectName("SmallMeta")
        tone_note.setWordWrap(True)
        tone_note.setStyleSheet("QLabel#SmallMeta { font-size: 12px; color: #94a3b8; margin-top: 6px; }")
        ai_layout.addWidget(tone_note)
        model_note = QLabel(
            "Default setup installs only Gemma3:4b and Nomic Embed. Ministral models are optional and can be installed later here. The dropdown below uses installed text models only."
        )
        model_note.setObjectName("SmallMeta")
        model_note.setWordWrap(True)
        model_note.setStyleSheet("QLabel#SmallMeta { font-size: 12px; color: #94a3b8; margin-top: 6px; }")
        ai_layout.addWidget(model_note)
        layout.addWidget(ai_surface)

        layout.addStretch(1)
        scroll.setWidget(host)
        return scroll

    def _build_audio_tab(self) -> QWidget:
        host = QWidget()
        host.setObjectName("SettingsTabCanvas")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 4, 82)
        layout.setSpacing(20)

        intro = QLabel("Choose which sounds ONCard uses for clicks, transitions, and notifications.")
        intro.setObjectName("SectionText")
        intro.setWordWrap(True)
        intro.setStyleSheet("QLabel#SectionText { font-size: 14px; line-height: 1.6; color: #475569; }")
        layout.addWidget(intro)

        surface, form = self._settings_card(layout_type=QFormLayout)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form_title = QLabel("Audio")
        form_title.setObjectName("SectionTitle")
        form_title.setStyleSheet("QLabel#SectionTitle { font-size: 18px; font-weight: 700; color: #0f172a; background: transparent; border: none; padding: 0px 0px 12px 0px; }")
        form.addRow(form_title)

        self.audio_enabled_checkbox = QCheckBox("Audio")
        self.audio_enabled_checkbox.setChecked(True)
        form.addRow("Master audio", self.audio_enabled_checkbox)

        self.click_enabled_checkbox = QCheckBox("Mouse Click")
        self.click_sound_combo = QComboBox()
        for label, value in (
            ("Soft tap", "click3"),
            ("Classic tap", "click"),
            ("Crisp tap", "click4"),
            ("Deep tap", "click5"),
        ):
            self.click_sound_combo.addItem(label, value)
        click_row = self._audio_choice_row(self.click_enabled_checkbox, self.click_sound_combo, lambda: self._test_click_sound())
        form.addRow("Mouse Click", click_row)

        self.transition_enabled_checkbox = QCheckBox("Transition")
        self.transition_sound_combo = QComboBox()
        self.transition_sound_combo.addItem("Simple woosh", "woosh")
        transition_row = self._audio_choice_row(
            self.transition_enabled_checkbox,
            self.transition_sound_combo,
            lambda: self._test_transition_sound(),
        )
        form.addRow("Transition", transition_row)

        self.notification_sound_combo = QComboBox()
        self.notification_sound_combo.addItem("Default Windows", "windows")
        self.notification_sound_combo.addItem("Notify 1", "notify1")
        self.notification_sound_combo.addItem("Notify 2", "notify2")
        notification_row = self._audio_choice_row(None, self.notification_sound_combo, lambda: self._test_notification_sound())
        form.addRow("Notification", notification_row)

        note = QLabel(
            "Mouse click sounds also apply to sliders. Custom notification sounds play with ONCard toast notifications; FTC finish notifications repeat custom sounds four times."
        )
        note.setObjectName("SmallMeta")
        note.setWordWrap(True)
        note.setStyleSheet("QLabel#SmallMeta { font-size: 12px; color: #94a3b8; }")

        layout.addWidget(surface)
        layout.addWidget(note)
        layout.addStretch(1)
        return host

    def _audio_choice_row(self, toggle: QCheckBox | None, combo: QComboBox, test_handler) -> QWidget:
        row = QWidget()
        row.setObjectName("SettingsAudioChoiceRow")
        row.setStyleSheet("QWidget#SettingsAudioChoiceRow { background: transparent; }")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        if toggle is not None:
            toggle.setMinimumWidth(124)
            layout.addWidget(toggle, 0)
        combo.setMinimumWidth(180)
        layout.addWidget(combo, 1)
        test_btn = AnimatedButton("Test")
        test_btn.setProperty("skipClickSfx", True)
        test_btn.setFixedWidth(72)
        test_btn.clicked.connect(test_handler)
        layout.addWidget(test_btn, 0)
        return row

    def _build_performance_tab(self) -> QWidget:
        host = QWidget()
        host.setObjectName("SettingsTabCanvas")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 4, 82)
        layout.setSpacing(20)

        intro = QLabel("Control how aggressively ONCard warms caches, uses background workers, and handles motion.")
        intro.setObjectName("SectionText")
        intro.setWordWrap(True)
        intro.setStyleSheet("QLabel#SectionText { font-size: 14px; line-height: 1.6; color: #475569; }")
        layout.addWidget(intro)

        perf_surface, perf_layout = self._settings_card(layout_type=QFormLayout)
        form_title = QLabel("Performance")
        form_title.setObjectName("SectionTitle")
        form_title.setStyleSheet("QLabel#SectionTitle { font-size: 18px; font-weight: 700; color: #0f172a; background: transparent; border: none; padding: 0px 0px 12px 0px; }")
        perf_layout.addRow(form_title)

        self.performance_mode = PopupMenuComboBox()
        self.performance_mode.addItem("Auto", "auto")
        self.performance_mode.addItem("Manual", "manual")
        self.performance_mode.set_popup_handler(
            lambda: self._open_combo_choice_picker(
                title="Performance mode",
                control=self.performance_mode,
                fallback_value="auto",
            )
        )
        self.performance_mode.currentIndexChanged.connect(self._refresh_performance_mode)

        self.startup_workers = QSpinBox()
        self.startup_workers.setRange(1, 8)
        self.background_workers = QSpinBox()
        self.background_workers.setRange(1, 8)
        self.warm_cache_checkbox = QCheckBox("Warm SQL, card, and vector caches during startup")
        self.warm_cache_checkbox.setStyleSheet(
            """
            QCheckBox {
                font-size: 14px;
                color: #334155;
                spacing: 10px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 6px;
                border: 2px solid #cbd5e1;
                background: #ffffff;
            }
            QCheckBox::indicator:hover {
                border: 2px solid #94a3b8;
            }
            QCheckBox::indicator:checked {
                background: #0f2539;
                border: 2px solid #0f2539;
                image: url("__CHECK_ICON__");
            }
            """.replace("__CHECK_ICON__", CHECK_ICON_URL)
        )
        self.reduced_motion_checkbox = QCheckBox("Reduce motion and transition animations")
        self.reduced_motion_checkbox.setStyleSheet(
            """
            QCheckBox {
                font-size: 14px;
                color: #334155;
                spacing: 10px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 6px;
                border: 2px solid #cbd5e1;
                background: #ffffff;
            }
            QCheckBox::indicator:hover {
                border: 2px solid #94a3b8;
            }
            QCheckBox::indicator:checked {
                background: #0f2539;
                border: 2px solid #0f2539;
                image: url("__CHECK_ICON__");
            }
            """.replace("__CHECK_ICON__", CHECK_ICON_URL)
        )

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
        note.setStyleSheet("QLabel#SmallMeta { font-size: 12px; color: #94a3b8; }")
        layout.addWidget(perf_surface)
        layout.addWidget(note)
        layout.addStretch(1)
        return host

    def _build_model_row(self, spec: ModelSpec) -> dict[str, object]:
        container = QFrame()
        container.setObjectName("SettingsCard")
        container.setStyleSheet(
            """
            QFrame#SettingsCard {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #fafbfc);
                border: 1px solid rgba(203, 213, 225, 0.5);
                border-radius: 16px;
            }
            """
        )
        layout = QHBoxLayout(container)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(16)

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
        cloud_enabled = bool(ai_settings.get("ollama_cloud_enabled", False))
        cloud_api_key = str(ai_settings.get("ollama_cloud_api_key", "")).strip()
        cloud_tag = str(ai_settings.get("ollama_cloud_selected_model_tag", "")).strip()
        self.cloud_enabled_checkbox.blockSignals(True)
        self.cloud_enabled_checkbox.setChecked(cloud_enabled)
        self.cloud_enabled_checkbox.blockSignals(False)
        self.cloud_api_key_edit.blockSignals(True)
        self.cloud_api_key_edit.setText(cloud_api_key)
        self.cloud_api_key_edit.blockSignals(False)
        self._cloud_model_tags = []
        self.cloud_model_combo.clear()
        if cloud_enabled and cloud_tag:
            self.cloud_model_combo.addItem(self._cloud_label_for_tag(cloud_tag), cloud_tag)
            self.cloud_model_combo.setCurrentIndex(0)
            self._cloud_model_tags = [cloud_tag]
        self._refresh_cloud_controls(force_reload_models=False, preferred_tag=cloud_tag)
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
        mcq_setup = dict(setup.get("mcq", {}))
        self.mcq_enabled_checkbox.setChecked(bool(mcq_setup.get("enabled", False)))
        mcq_difficulty = str(mcq_setup.get("difficulty", "slightly_harder")).strip() or "slightly_harder"
        difficulty_index = self.mcq_difficulty.findData(mcq_difficulty)
        if difficulty_index >= 0:
            self.mcq_difficulty.setCurrentIndex(difficulty_index)
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
        audio_setup = dict(setup.get("audio", {}))
        self.audio_enabled_checkbox.setChecked(bool(audio_setup.get("enabled", True)))
        self.click_enabled_checkbox.setChecked(bool(audio_setup.get("click_enabled", True)))
        self._set_combo_data(self.click_sound_combo, str(audio_setup.get("click_sound", "click3")), "click3")
        self.transition_enabled_checkbox.setChecked(bool(audio_setup.get("transition_enabled", True)))
        self._set_combo_data(self.transition_sound_combo, str(audio_setup.get("transition_sound", "woosh")), "woosh")
        self._set_combo_data(self.notification_sound_combo, str(audio_setup.get("notification_sound", "windows")), "windows")
        self._refresh_performance_mode()
        self.ollama_status.setText("Model status will load after settings opens.")
        self.ollama_hint.setText("You can keep using these settings while ONCard checks Ollama.")
        self._refresh_text_model_choices_from_saved(ai_settings)

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str, fallback: str) -> None:
        index = combo.findData(str(value or "").strip())
        if index < 0:
            index = combo.findData(fallback)
        if index < 0:
            index = 0
        combo.setCurrentIndex(index)

    def _cloud_mode_enabled(self) -> bool:
        return bool(self.cloud_enabled_checkbox.isChecked())

    def _open_ollama_cloud_keys(self) -> None:
        webbrowser.open(OLLAMA_CLOUD_KEYS_URL)

    def _on_cloud_mode_toggled(self, _checked: bool) -> None:
        self._refresh_cloud_controls(force_reload_models=self._cloud_mode_enabled())

    def _on_cloud_api_key_changed(self, _text: str) -> None:
        self._cloud_model_tags = []
        self.cloud_model_combo.clear()
        if self._cloud_mode_enabled():
            if self.cloud_api_key_edit.text().strip():
                self.cloud_status.setText("API key updated. Press Load cloud models.")
            else:
                self.cloud_status.setText("Paste your Ollama API key to load cloud models.")
        self._refresh_cloud_controls(force_reload_models=False)

    def _cloud_candidate_specs(self) -> list[ModelSpec]:
        specs: list[ModelSpec] = []
        for key in non_embedding_llm_keys():
            spec = MODELS.get(key)
            if spec is not None:
                specs.append(spec)
        return specs

    def _cloud_candidate_tags(self) -> list[str]:
        tags: list[str] = []
        seen: set[str] = set()
        for spec in self._cloud_candidate_specs():
            for tag in [spec.primary_tag, *spec.candidate_tags]:
                clean = str(tag or "").strip()
                if not clean or clean in seen:
                    continue
                seen.add(clean)
                tags.append(clean)
        return tags

    def _cloud_label_for_tag(self, model_tag: str) -> str:
        clean_tag = str(model_tag or "").strip()
        for spec in self._cloud_candidate_specs():
            if clean_tag == spec.primary_tag or clean_tag in spec.candidate_tags:
                return f"{spec.display_name} (Cloud)"
        return f"{clean_tag} (Cloud)" if clean_tag else "Cloud model"

    def _refresh_cloud_controls(self, *, force_reload_models: bool = False, preferred_tag: str = "") -> None:
        cloud_enabled = self._cloud_mode_enabled()
        key_present = bool(self.cloud_api_key_edit.text().strip())
        self.cloud_api_key_edit.setEnabled(cloud_enabled)
        self.refresh_cloud_models_btn.setEnabled(cloud_enabled and key_present and not self._loading_cloud_models)
        self.cloud_model_combo.setEnabled(cloud_enabled and self.cloud_model_combo.count() > 0)

        if not cloud_enabled:
            self.cloud_status.setText("Cloud service is off. ONCard uses local models.")
            self.selected_text_llm.setEnabled(self.selected_text_llm.count() > 0)
            return

        if not key_present:
            self.cloud_status.setText("Cloud mode is on. Paste an API key, then load cloud variants.")
            self.cloud_model_combo.setEnabled(False)
            self.selected_text_llm.setEnabled(False)
            return

        self.selected_text_llm.setEnabled(False)
        if force_reload_models:
            self._refresh_cloud_models(force=force_reload_models, preferred_tag=preferred_tag)
        elif self.cloud_model_combo.currentIndex() >= 0:
            current_label = str(self.cloud_model_combo.currentText() or "").strip()
            self.cloud_status.setText(
                f"Cloud model ready: {current_label}. Cloud mode overrides local model selection."
                if current_label
                else "Cloud model ready. Cloud mode overrides local model selection."
            )
        else:
            self.cloud_status.setText("Cloud mode is ready. Press Load cloud models.")

    def _refresh_cloud_models(self, *, force: bool = False, preferred_tag: str = "") -> None:
        if not self._cloud_mode_enabled():
            return
        api_key = self.cloud_api_key_edit.text().strip()
        if not api_key:
            self.cloud_status.setText("Paste your Ollama API key to load cloud models.")
            self.cloud_model_combo.clear()
            self.cloud_model_combo.setEnabled(False)
            return
        if self._loading_cloud_models:
            return
        if self._cloud_model_tags and not force:
            available_tags = list(self._cloud_model_tags)
        else:
            self._loading_cloud_models = True
            self.refresh_cloud_models_btn.setEnabled(False)
            self.cloud_status.setText("Loading cloud models...")
            try:
                tags = self.ollama.cloud_model_tags(api_key, timeout=8)
            except OllamaError as exc:
                self.cloud_status.setText(f"Cloud model lookup failed: {exc}")
                self.cloud_model_combo.clear()
                self.cloud_model_combo.setEnabled(False)
                self._cloud_model_tags = []
                self._loading_cloud_models = False
                self.refresh_cloud_models_btn.setEnabled(True)
                return
            available_set = {str(item).strip() for item in tags if str(item).strip()}
            available_tags = []
            for spec in self._cloud_candidate_specs():
                chosen = ""
                for tag in [spec.primary_tag, *spec.candidate_tags]:
                    clean_tag = str(tag or "").strip()
                    if clean_tag in available_set:
                        chosen = clean_tag
                        break
                if chosen:
                    available_tags.append(chosen)
            self._cloud_model_tags = list(available_tags)
            self._loading_cloud_models = False

        selected_before = preferred_tag.strip() or str(self.cloud_model_combo.currentData() or "").strip()
        self.cloud_model_combo.blockSignals(True)
        self.cloud_model_combo.clear()
        for tag in available_tags:
            self.cloud_model_combo.addItem(self._cloud_label_for_tag(tag), tag)
        chosen = selected_before if selected_before in available_tags else (available_tags[0] if available_tags else "")
        idx = self.cloud_model_combo.findData(chosen)
        if idx >= 0:
            self.cloud_model_combo.setCurrentIndex(idx)
        self.cloud_model_combo.blockSignals(False)
        self.cloud_model_combo.setEnabled(bool(available_tags))
        if available_tags:
            self.cloud_status.setText(
                f"Loaded {len(available_tags)} cloud variants for ONCard models. "
                "Cloud mode overrides local model selection."
            )
        else:
            self.cloud_status.setText("No matching cloud versions were found for ONCard's current text models.")
        self.refresh_cloud_models_btn.setEnabled(True)
        self.selected_text_llm.setEnabled(False)

    def _save(self) -> None:
        profile_name = self.name_edit.text().strip()
        if not profile_name:
            QMessageBox.warning(self, "Settings", "Name is required.")
            return
        if self.gender_combo.currentText().strip().lower() == "custom" and not self.gender_custom_edit.text().strip():
            QMessageBox.warning(self, "Settings", "Enter a custom gender and pronouns up to 64 characters.")
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
        cloud_enabled = self._cloud_mode_enabled()
        cloud_api_key = self.cloud_api_key_edit.text().strip()
        if cloud_enabled and not cloud_api_key:
            QMessageBox.warning(self, "Settings", "Cloud mode is enabled, but API key is empty.")
            return
        cloud_model_tag = str(self.cloud_model_combo.currentData() or "").strip()
        if not cloud_model_tag:
            cloud_model_tag = str(ai_settings.get("ollama_cloud_selected_model_tag", "")).strip()
        if cloud_enabled and not cloud_model_tag:
            QMessageBox.warning(self, "Settings", "Select a cloud model first, then save.")
            return
        selected_key = str(self.selected_text_llm.currentData() or "").strip()
        if cloud_enabled:
            mapped_key = text_llm_key_for_model_tag(cloud_model_tag)
            if mapped_key:
                ai_settings["selected_text_llm_key"] = mapped_key
        elif selected_key:
            ai_settings["selected_text_llm_key"] = selected_key
        ai_settings["ollama_cloud_enabled"] = cloud_enabled
        ai_settings["ollama_cloud_api_key"] = cloud_api_key
        if cloud_model_tag:
            ai_settings["ollama_cloud_selected_model_tag"] = cloud_model_tag
        ai_settings["ask_ai_tone"] = str(self.ask_ai_tone.currentData() or "warm")
        ai_settings["assistant_tone"] = ai_settings["ask_ai_tone"]
        ai_settings["ask_ai_emoji_level"] = max(1, min(4, self.ask_ai_emoji_slider.value()))
        ai_settings["files_to_cards_ocr"] = self.ftc_ocr_checkbox.isChecked()
        self.datastore.save_ai_settings(ai_settings)
        self.ollama.configure_from_ai_settings(ai_settings)
        self.preflight.invalidate()

        setup = self.datastore.load_setup()
        setup["ftc"] = {
            "default_mode": str(self.ftc_default_mode.currentData() or "standard"),
            "question_count_standard": int(self.ftc_questions_standard.value()),
            "question_count_force": int(self.ftc_questions_force.value()),
            "difficulty": str(self.ftc_difficulty.currentData() or "normal"),
            "use_ocr": bool(self.ftc_ocr_checkbox.isChecked()),
        }
        setup["mcq"] = {
            "enabled": bool(self.mcq_enabled_checkbox.isChecked()),
            "difficulty": str(self.mcq_difficulty.currentData() or "slightly_harder"),
        }
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
        setup["audio"] = self._current_audio_setup()
        self.datastore.save_setup(setup)
        self.accept()

    def _current_audio_setup(self) -> dict:
        return {
            "enabled": bool(self.audio_enabled_checkbox.isChecked()),
            "click_enabled": bool(self.click_enabled_checkbox.isChecked()),
            "click_sound": str(self.click_sound_combo.currentData() or "click3"),
            "transition_enabled": bool(self.transition_enabled_checkbox.isChecked()),
            "transition_sound": str(self.transition_sound_combo.currentData() or "woosh"),
            "notification_sound": str(self.notification_sound_combo.currentData() or "windows"),
        }

    def _apply_audio_preview_config(self) -> None:
        parent = self.parentWidget()
        sounds = getattr(parent, "sounds", None)
        if sounds is not None and hasattr(sounds, "configure"):
            sounds.configure({"audio": self._current_audio_setup()})

    def _test_click_sound(self) -> None:
        self._apply_audio_preview_config()
        parent = self.parentWidget()
        sounds = getattr(parent, "sounds", None)
        if sounds is not None:
            sounds.play("click")

    def _test_transition_sound(self) -> None:
        self._apply_audio_preview_config()
        parent = self.parentWidget()
        sounds = getattr(parent, "sounds", None)
        if sounds is not None:
            sounds.play("woosh")

    def _test_notification_sound(self) -> None:
        self._apply_audio_preview_config()
        parent = self.parentWidget()
        sound = str(self.notification_sound_combo.currentData() or "windows")
        if parent is not None and hasattr(parent, "show_audio_test_notification"):
            parent.show_audio_test_notification(sound)
            return
        sounds = getattr(parent, "sounds", None)
        if sounds is not None:
            sounds.play_notification(sound)

    def _play_click_sound(self, *, volume_scale: float = 1.0) -> None:
        if not self._sfx_ready:
            return
        self._apply_audio_preview_config()
        parent = self.parentWidget()
        sounds = getattr(parent, "sounds", None)
        if sounds is not None:
            sounds.play("click", volume_scale=volume_scale)

    def _play_slider_sound(self, *, volume_scale: float = 1.0) -> None:
        if not self._sfx_ready:
            return
        self._apply_audio_preview_config()
        parent = self.parentWidget()
        sounds = getattr(parent, "sounds", None)
        if sounds is not None and hasattr(sounds, "play_slider_click"):
            sounds.play_slider_click(volume_scale=volume_scale)
        elif sounds is not None:
            sounds.play("click", volume_scale=volume_scale)

    def _on_attention_changed(self, value: int) -> None:
        if value != self._last_attention_value:
            self._play_slider_sound(volume_scale=1.25)
        self._last_attention_value = value
        self._update_attention_label(value)

    def _on_gender_mode_changed(self) -> None:
        is_custom = self.gender_combo.currentText().strip().lower() == "custom"
        self.gender_custom_edit.setVisible(is_custom)

    def _on_ask_ai_emoji_changed(self, value: int) -> None:
        if value != self._last_ask_ai_emoji_value:
            self._play_slider_sound(volume_scale=1.1)
        self._last_ask_ai_emoji_value = value
        self._update_ask_ai_emoji_label(value)

    def _refresh_text_model_choices_from_saved(self, ai_settings: dict) -> None:
        setup = self.datastore.load_setup()
        installed_models = dict(setup.get("installed_models", {}))
        saved_key = str(ai_settings.get("selected_text_llm_key", "")).strip()
        installed_keys = [key for key in non_embedding_llm_keys() if bool(installed_models.get(key, False))]
        self.selected_text_llm.blockSignals(True)
        self.selected_text_llm.clear()
        for key in installed_keys:
            spec = MODELS.get(key)
            if spec is not None:
                self.selected_text_llm.addItem(spec.display_name, key)
        selected_index = self.selected_text_llm.findData(saved_key)
        if selected_index < 0 and self.selected_text_llm.count() > 0:
            selected_index = 0
        if selected_index >= 0:
            self.selected_text_llm.setCurrentIndex(selected_index)
        cloud_enabled = self._cloud_mode_enabled()
        self.selected_text_llm.setEnabled(self.selected_text_llm.count() > 0 and not cloud_enabled)
        self.selected_text_llm.setToolTip("Cloud mode is enabled. Use the Cloud model selector above." if cloud_enabled else "")
        self.selected_text_llm.blockSignals(False)

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
        cloud_enabled = self._cloud_mode_enabled()
        self.selected_text_llm.setEnabled(self.selected_text_llm.count() > 0 and not cloud_enabled)
        if cloud_enabled:
            self.selected_text_llm.setToolTip("Cloud mode is enabled. Use the Cloud model selector above.")
        else:
            self.selected_text_llm.setToolTip("")
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
            self.gender_custom_edit.setText(gender[:64])
        else:
            self.gender_combo.setCurrentText("Male")
            self.gender_custom_edit.clear()
        self._on_gender_mode_changed()

    def _effective_gender_value(self) -> str:
        mode = self.gender_combo.currentText().strip()
        if mode.lower() == "custom":
            return self.gender_custom_edit.text().strip()[:64]
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
        icons_root = getattr(getattr(self.parentWidget(), "paths", None), "icons", None)
        dialog = ExportAccountDialog(parent=self, blur_target=None, icons_root=icons_root)
        if dialog.exec_with_backdrop() != QDialog.DialogCode.Accepted or not dialog.download_requested():
            self._cleanup_temp_export(temp_zip)
            return False

        destination = Path.home() / "Downloads" / temp_zip.name

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

    def _confirmation_icon_button(self, icon_name: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("NewAccountConfirmIconButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedSize(34, 34)
        button.setText("")
        button.setToolTip(tooltip)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        icon_provider = getattr(self.parentWidget(), "icons", None)
        if icon_provider is not None and hasattr(icon_provider, "icon"):
            button.setIcon(icon_provider.icon("common", icon_name, tooltip[:1]))
            button.setIconSize(QSize(15, 15))
        else:
            icon_root = getattr(getattr(self.parentWidget(), "paths", None), "icons", None)
            if isinstance(icon_root, Path):
                button.setIcon(QIcon(str(icon_root / "common" / f"{icon_name}.png")))
                button.setIconSize(QSize(15, 15))
        return button

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
        yes_btn = self._confirmation_icon_button("check", "yes, I am in!")
        cancel_btn = self._confirmation_icon_button("cross_two", "cancel")
        first.addButton(yes_btn, QMessageBox.AcceptRole)
        first.addButton(cancel_btn, QMessageBox.RejectRole)
        first.exec()
        if first.clickedButton() != yes_btn:
            return

        second = QMessageBox(self)
        second.setWindowTitle("New account")
        second.setText("Nice! New account will be made. The app will open a new profile maker window for you to make a new account.")
        okay_btn = self._confirmation_icon_button("check", "Okay")
        nevermind_btn = self._confirmation_icon_button("cross_two", "nevermind, I changed my mind")
        second.addButton(okay_btn, QMessageBox.AcceptRole)
        second.addButton(nevermind_btn, QMessageBox.RejectRole)
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
        if snap.cloud_mode:
            if not snap.cloud_key_present:
                self.ollama_status.setText("Cloud mode is enabled, but API key is missing.")
                self.ollama_hint.setText("Paste your API key in the Ollama cloud section above.")
            elif snap.error and not snap.installed_tags:
                self.ollama_status.setText("Cloud mode is enabled, but ONCard could not read cloud model tags.")
                self.ollama_hint.setText(snap.error or "Check the API key and internet connection, then refresh.")
            else:
                api_text = "Cloud API reachable." if snap.api_reachable else "Cloud API not responding yet."
                self.ollama_status.setText(f"Ollama Cloud is active. {api_text}")
                self.ollama_hint.setText("Install/Reinstall/Delete actions are disabled while cloud mode is active.")
        elif not snap.cli_available:
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
        text_keys = set(non_embedding_llm_keys())
        for key, spec in MODELS.items():
            row = self._model_rows[key]
            status_label = row["status"]
            install_btn = row["install_btn"]
            reinstall_btn = row["reinstall_btn"]
            delete_btn = row["delete_btn"]
            is_installed = self._is_model_installed_ui(snap, key)
            if snap.cloud_mode:
                if key in text_keys:
                    status_text = "Available in cloud" if is_installed else "Unavailable in cloud"
                else:
                    status_text = "Installed" if is_installed else "Not installed"
                install_btn.setVisible(False)
                reinstall_btn.setVisible(False)
                delete_btn.setVisible(False)
                install_btn.setEnabled(False)
                reinstall_btn.setEnabled(False)
                delete_btn.setEnabled(False)
                status_label.setText(status_text)
                continue
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
        if self._cloud_mode_enabled():
            QMessageBox.information(self, "Cloud mode active", "Turn off cloud mode to install local Ollama models.")
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
        if self._cloud_mode_enabled():
            QMessageBox.information(self, "Cloud mode active", "Turn off cloud mode to remove local Ollama models.")
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
        cloud_mode = self._cloud_mode_enabled()
        for row in self._model_rows.values():
            row["install_btn"].setEnabled(enabled and cli_installed and not cloud_mode)
            row["reinstall_btn"].setEnabled(enabled and cli_installed and not cloud_mode)
            row["delete_btn"].setEnabled(enabled and cli_installed and not cloud_mode)
        self.refresh_models_btn.setEnabled(enabled)

    def _refresh_performance_mode(self) -> None:
        manual = str(self.performance_mode.currentData() or "auto") == "manual"
        self.startup_workers.setEnabled(manual)
        self.background_workers.setEnabled(manual)

    def reject(self) -> None:
        if self._install_worker and self._install_worker.isRunning():
            QMessageBox.information(self, "Install in progress", "Wait for the current model installation to finish first.")
            return
        parent = self.parentWidget()
        sounds = getattr(parent, "sounds", None)
        if sounds is not None and hasattr(sounds, "configure"):
            sounds.configure(self.datastore.load_setup())
        super().reject()

    @staticmethod
    def _coerce_age(value: object) -> int:
        try:
            age = int(str(value).strip())
        except (TypeError, ValueError):
            return 16
        return max(4, min(99, age))
