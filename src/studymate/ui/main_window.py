from __future__ import annotations

import random

from PySide6.QtCore import QEvent, QParallelAnimationGroup, QPoint, QPropertyAnimation, QRect, QSize, Qt, QEasingCurve, QUrl, QTimer, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QIcon, QImage, QKeySequence, QMouseEvent, QPainter, QPainterPath, QPixmap, QShortcut, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QGraphicsBlurEffect,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from studymate.services.data_store import DataStore
from studymate.services.model_preflight import ModelPreflightService
from studymate.services.ollama_service import OllamaService
from studymate.services.web_lesson_server import WebLessonServer
from studymate.theme import apply_app_theme
from studymate.ui.animated import AnimatedButton, AnimatedStackedWidget
from studymate.ui.audio import ClickSoundFilter, UiSoundBank
from studymate.ui.create_tab import CreateTab
from studymate.ui.icon_helper import IconHelper
from studymate.ui.mcq_tab import MCQTab
from studymate.ui.settings_dialog import SettingsDialog
from studymate.ui.stats_dialog import StatsDialog
from studymate.ui.study_tab import StudyTab
from studymate.ui.windows_toast import set_windows_app_user_model_id, show_windows_toast
from studymate.ui.window_effects import polish_popup_window, polish_windows_window
from studymate.version import app_name_with_release_channel


def _motion_duration(duration: int) -> int:
    app = QApplication.instance()
    if app is not None and bool(app.property("reducedMotion")):
        return 1
    return duration


class WindowDragBar(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._drag_offset: QPoint | None = None

    def _toggle_window_state(self) -> None:
        window = self.window()
        if isinstance(window, QMainWindow):
            window._toggle_maximize_restore()  # type: ignore[attr-defined]

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            window = self.window()
            handle = window.windowHandle() if window is not None else None
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
            if window is not None and not window.isMaximized():
                self._drag_offset = event.globalPosition().toPoint() - window.frameGeometry().topLeft()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        window = self.window()
        if self._drag_offset is not None and window is not None and not window.isMaximized():
            window.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_window_state()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class AppIconMenu(QWidget):
    profiles_requested = Signal()

    LINKS = (
        ("ONCard", "https://github.com/MightyXdash/ONCard"),
        ("Releases", "https://github.com/MightyXdash/ONCard/releases"),
        ("Ollama", "https://ollama.com/search"),
        ("NomicEmbed", "https://ollama.com/library/nomic-embed-text-v2-moe"),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setObjectName("AppIconMenu")
        polish_popup_window(self, set_frameless=False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._animation_group: QParallelAnimationGroup | None = None
        self._accounts: list[dict] = []
        self._active_id = ""

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.surface = QFrame(self)
        self.surface.setObjectName("AppIconMenuSurface")
        root_layout.addWidget(self.surface)

        surface_layout = QVBoxLayout(self.surface)
        surface_layout.setContentsMargins(8, 8, 8, 8)
        surface_layout.setSpacing(4)

        self.profiles_btn = AnimatedButton("Profiles")
        self.profiles_btn.setObjectName("AppIconMenuButton")
        self.profiles_btn.setProperty("skipClickSfx", True)
        self.profiles_btn.setMinimumWidth(176)
        self.profiles_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.profiles_btn.set_motion_scale_range(0.012)
        self.profiles_btn.clicked.connect(self._open_profiles)
        surface_layout.addWidget(self.profiles_btn)

        links_header = QLabel("Links")
        links_header.setObjectName("SmallMeta")
        surface_layout.addWidget(links_header)

        for label, url in self.LINKS:
            button = AnimatedButton(label)
            button.setObjectName("AppIconMenuButton")
            button.setProperty("skipClickSfx", True)
            button.setMinimumWidth(176)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.set_motion_scale_range(0.012)
            button.clicked.connect(lambda _checked=False, target=url: self._open_url(target))
            surface_layout.addWidget(button)

    def set_accounts(self, accounts: list[dict], active_id: str) -> None:
        self._accounts = [dict(account) for account in accounts]
        self._active_id = str(active_id or "")

    def popup_from(self, anchor: QWidget) -> None:
        if self.isVisible():
            self.hide()
            return

        self.adjustSize()
        end_rect = QRect(anchor.mapToGlobal(QPoint(0, anchor.height() + 2)), self.sizeHint())
        screen = QGuiApplication.screenAt(end_rect.center()) or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            if end_rect.right() > available.right() - 8:
                end_rect.moveRight(available.right() - 8)
            if end_rect.bottom() > available.bottom() - 8:
                end_rect.moveBottom(available.bottom() - 8)
            if end_rect.left() < available.left() + 8:
                end_rect.moveLeft(available.left() + 8)

        start_rect = QRect(end_rect)
        start_rect.translate(0, -2)

        self.setGeometry(start_rect)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()

        if self._animation_group is not None:
            self._animation_group.stop()

        geometry_animation = QPropertyAnimation(self, b"geometry", self)
        geometry_animation.setDuration(_motion_duration(180))
        geometry_animation.setStartValue(start_rect)
        geometry_animation.setEndValue(end_rect)
        geometry_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        opacity_animation = QPropertyAnimation(self, b"windowOpacity", self)
        opacity_animation.setDuration(_motion_duration(170))
        opacity_animation.setStartValue(0.0)
        opacity_animation.setEndValue(1.0)
        opacity_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._animation_group = QParallelAnimationGroup(self)
        self._animation_group.addAnimation(geometry_animation)
        self._animation_group.addAnimation(opacity_animation)
        self._animation_group.start()

    def _open_url(self, url: str) -> None:
        self.hide()
        QDesktopServices.openUrl(QUrl(url))

    def _open_profiles(self) -> None:
        self.hide()
        self.profiles_requested.emit()


class ProfilesOverlayDialog(QDialog):
    def __init__(
        self,
        *,
        parent: QWidget,
        icons: IconHelper,
        accounts: list[dict],
        active_id: str,
        blur_target: QWidget | None,
        anchor: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        polish_popup_window(self)
        self._accounts = [dict(account) for account in accounts]
        self._active_id = str(active_id or "")
        self._blur_target = blur_target or parent
        self._overlay_target = parent
        self._anchor = anchor
        self._overlay: QWidget | None = None
        self._previous_effect = None
        self._selected_account_id = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        card = QFrame(self)
        card.setObjectName("AppIconMenuSurface")
        root.addWidget(card)
        self._card = card

        body = QVBoxLayout(card)
        body.setContentsMargins(18, 16, 18, 16)
        body.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QLabel("Profiles")
        title.setObjectName("SectionTitle")
        header.addWidget(title)
        header.addStretch(1)

        self.close_btn = AnimatedButton("")
        self.close_btn.setObjectName("ProfilesOverlayCloseButton")
        self.close_btn.setFixedSize(28, 28)
        self.close_btn.setIcon(icons.icon("common", "cross_two", "X"))
        self.close_btn.setIconSize(QSize(11, 11))
        self.close_btn.setToolTip("Close")
        self.close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_btn.setProperty("disablePressMotion", True)
        self.close_btn.set_motion_scale_range(0.0)
        self.close_btn.set_motion_hover_grow(0, 0)
        self.close_btn.set_motion_lift(0.0)
        self.close_btn.set_motion_press_scale(0.0)
        self.close_btn.setStyleSheet(
            """
            QPushButton#ProfilesOverlayCloseButton {
                background: transparent;
                border: none;
                border-radius: 10px;
            }
            QPushButton#ProfilesOverlayCloseButton:hover {
                background: transparent;
                border: none;
                border-radius: 10px;
            }
            QPushButton#ProfilesOverlayCloseButton:pressed {
                background: rgba(218, 229, 240, 0.98);
                border: 1px solid rgba(159, 177, 196, 0.82);
                border-radius: 10px;
            }
            """
        )
        self.close_btn.clicked.connect(self.reject)
        header.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)
        body.addLayout(header)

        if self._accounts:
            for account in self._accounts:
                account_id = str(account.get("id", "")).strip()
                if not account_id:
                    continue
                name = str(account.get("name", "")).strip() or f"Account {account_id[:6]}"
                if account_id == self._active_id:
                    name = f"{name} (Current)"
                button = AnimatedButton(name)
                button.setObjectName("AppIconAccountButton")
                button.setProperty("skipClickSfx", True)
                button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                button.set_motion_scale_range(0.012)
                button.clicked.connect(lambda _checked=False, target=account_id: self._select_account(target))
                body.addWidget(button)
        else:
            empty = QLabel("No profiles available.")
            empty.setObjectName("SmallMeta")
            body.addWidget(empty)

        self.setMinimumWidth(420)

    def exec_with_backdrop(self) -> str:
        self._apply_backdrop()
        try:
            self.adjustSize()
            self._position_near_anchor()
            self.exec()
            return self._selected_account_id
        finally:
            self._clear_backdrop()

    def mousePressEvent(self, event) -> None:
        if not self._card.geometry().contains(event.position().toPoint()):
            self.reject()
            event.accept()
            return
        super().mousePressEvent(event)

    def _select_account(self, account_id: str) -> None:
        self._selected_account_id = str(account_id or "")
        self.accept()

    def _center_on_parent(self) -> None:
        parent_widget = self.parentWidget()
        if parent_widget is None:
            return
        parent_rect = parent_widget.frameGeometry()
        self.move(
            int(parent_rect.center().x() - (self.width() / 2)),
            int(parent_rect.center().y() - (self.height() / 2)),
        )

    def _position_near_anchor(self) -> None:
        if self._anchor is None:
            self._center_on_parent()
            return
        anchor_top_left = self._anchor.mapToGlobal(QPoint(0, 0))
        x = int(anchor_top_left.x())
        y = int(anchor_top_left.y() + self._anchor.height() + 10)
        target = QRect(x, y, self.width(), self.height())
        screen = QGuiApplication.screenAt(target.center()) or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            if target.right() > available.right() - 8:
                target.moveRight(available.right() - 8)
            if target.bottom() > available.bottom() - 8:
                target.moveBottom(available.bottom() - 8)
            if target.left() < available.left() + 8:
                target.moveLeft(available.left() + 8)
            if target.top() < available.top() + 8:
                target.moveTop(available.top() + 8)
        self.move(target.topLeft())

    def _apply_backdrop(self) -> None:
        if self._blur_target is None:
            return
        self._previous_effect = self._blur_target.graphicsEffect()
        blur = QGraphicsBlurEffect(self._blur_target)
        blur.setBlurRadius(12.0)
        self._blur_target.setGraphicsEffect(blur)

        overlay = QWidget(self._overlay_target)
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        overlay.setStyleSheet("background: rgba(255, 255, 255, 0.22);")
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


class UserProfileMenu(QWidget):
    view_stats_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setObjectName("UserProfileMenu")
        polish_popup_window(self, set_frameless=False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._animation_group: QParallelAnimationGroup | None = None

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.surface = QFrame(self)
        self.surface.setObjectName("UserProfileMenuSurface")
        root_layout.addWidget(self.surface)

        surface_layout = QVBoxLayout(self.surface)
        surface_layout.setContentsMargins(12, 12, 12, 12)
        surface_layout.setSpacing(6)

        header = QLabel("Profile")
        header.setObjectName("SmallMeta")
        surface_layout.addWidget(header)

        self.name_label = QLabel("Student")
        self.name_label.setObjectName("SectionTitle")
        surface_layout.addWidget(self.name_label)

        self.meta_label = QLabel("Tap View stats")
        self.meta_label.setObjectName("SmallMeta")
        surface_layout.addWidget(self.meta_label)

        self.stats_btn = AnimatedButton("View stats")
        self.stats_btn.setObjectName("AppIconMenuButton")
        self.stats_btn.setProperty("skipClickSfx", True)
        self.stats_btn.setMinimumWidth(176)
        self.stats_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.stats_btn.set_motion_scale_range(0.012)
        self.stats_btn.clicked.connect(self._request_stats)
        surface_layout.addWidget(self.stats_btn)

    def set_profile(self, profile: dict) -> None:
        name = str(profile.get("name", "")).strip() or "Student"
        grade = str(profile.get("grade", "")).strip()
        age = str(profile.get("age", "")).strip()
        meta_parts: list[str] = []
        if grade:
            meta_parts.append(grade)
        if age:
            meta_parts.append(f"Age {age}")
        self.name_label.setText(name)
        self.meta_label.setText(" \u00b7 ".join(meta_parts) if meta_parts else "Tap View stats")

    def popup_from(self, anchor: QWidget) -> None:
        if self.isVisible():
            self.hide()
            return

        self.adjustSize()
        end_rect = QRect(anchor.mapToGlobal(QPoint(0, anchor.height() + 2)), self.sizeHint())
        screen = QGuiApplication.screenAt(end_rect.center()) or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            if end_rect.right() > available.right() - 8:
                end_rect.moveRight(available.right() - 8)
            if end_rect.bottom() > available.bottom() - 8:
                end_rect.moveBottom(available.bottom() - 8)
            if end_rect.left() < available.left() + 8:
                end_rect.moveLeft(available.left() + 8)

        start_rect = QRect(end_rect)
        start_rect.translate(0, -2)

        self.setGeometry(start_rect)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()

        if self._animation_group is not None:
            self._animation_group.stop()

        geometry_animation = QPropertyAnimation(self, b"geometry", self)
        geometry_animation.setDuration(_motion_duration(170))
        geometry_animation.setStartValue(start_rect)
        geometry_animation.setEndValue(end_rect)
        geometry_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        opacity_animation = QPropertyAnimation(self, b"windowOpacity", self)
        opacity_animation.setDuration(_motion_duration(160))
        opacity_animation.setStartValue(0.0)
        opacity_animation.setEndValue(1.0)
        opacity_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._animation_group = QParallelAnimationGroup(self)
        self._animation_group.addAnimation(geometry_animation)
        self._animation_group.addAnimation(opacity_animation)
        self._animation_group.start()

    def _request_stats(self) -> None:
        self.hide()
        self.view_stats_requested.emit()


class NotificationsMenu(QWidget):
    notifications_toggled = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setObjectName("NotificationsMenu")
        polish_popup_window(self, set_frameless=False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._animation_group: QParallelAnimationGroup | None = None

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.surface = QFrame(self)
        self.surface.setObjectName("NotificationsMenuSurface")
        root_layout.addWidget(self.surface)

        surface_layout = QVBoxLayout(self.surface)
        surface_layout.setContentsMargins(12, 12, 12, 12)
        surface_layout.setSpacing(8)

        header = QLabel("Notifications")
        header.setObjectName("SmallMeta")
        surface_layout.addWidget(header)

        self.toggle = QCheckBox("Notifications")
        self.toggle.setObjectName("NotificationsToggle")
        self.toggle.stateChanged.connect(lambda _state: self.notifications_toggled.emit(self.toggle.isChecked()))
        surface_layout.addWidget(self.toggle)

    def set_enabled(self, enabled: bool) -> None:
        self.toggle.blockSignals(True)
        self.toggle.setChecked(enabled)
        self.toggle.blockSignals(False)

    def popup_from(self, anchor: QWidget) -> None:
        if self.isVisible():
            self.hide()
            return

        self.adjustSize()
        end_rect = QRect(anchor.mapToGlobal(QPoint(0, anchor.height() + 2)), self.sizeHint())
        screen = QGuiApplication.screenAt(end_rect.center()) or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            if end_rect.right() > available.right() - 8:
                end_rect.moveRight(available.right() - 8)
            if end_rect.bottom() > available.bottom() - 8:
                end_rect.moveBottom(available.bottom() - 8)
            if end_rect.left() < available.left() + 8:
                end_rect.moveLeft(available.left() + 8)

        start_rect = QRect(end_rect)
        start_rect.translate(0, -2)

        self.setGeometry(start_rect)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()

        if self._animation_group is not None:
            self._animation_group.stop()

        geometry_animation = QPropertyAnimation(self, b"geometry", self)
        geometry_animation.setDuration(_motion_duration(170))
        geometry_animation.setStartValue(start_rect)
        geometry_animation.setEndValue(end_rect)
        geometry_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        opacity_animation = QPropertyAnimation(self, b"windowOpacity", self)
        opacity_animation.setDuration(_motion_duration(160))
        opacity_animation.setStartValue(0.0)
        opacity_animation.setEndValue(1.0)
        opacity_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._animation_group = QParallelAnimationGroup(self)
        self._animation_group.addAnimation(geometry_animation)
        self._animation_group.addAnimation(opacity_animation)
        self._animation_group.start()


class CreateModeMenu(QWidget):
    question_requested = Signal()
    ftc_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setObjectName("CreateModeMenu")
        polish_popup_window(self, set_frameless=False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._animation_group: QParallelAnimationGroup | None = None

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.surface = QFrame(self)
        self.surface.setObjectName("CreateModeMenuSurface")
        root_layout.addWidget(self.surface)

        surface_layout = QVBoxLayout(self.surface)
        surface_layout.setContentsMargins(10, 10, 10, 10)
        surface_layout.setSpacing(6)

        header = QLabel("Create")
        header.setObjectName("SmallMeta")
        surface_layout.addWidget(header)

        self.question_btn = AnimatedButton("Question")
        self.question_btn.setObjectName("CreateModeMenuButton")
        self.question_btn.setProperty("skipClickSfx", True)
        self.question_btn.setProperty("disablePressMotion", True)
        self.question_btn.setMinimumWidth(196)
        self.question_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.question_btn.set_motion_scale_range(0.0)
        self.question_btn.set_motion_press_scale(0.0)
        self.question_btn.clicked.connect(self._request_question)
        surface_layout.addWidget(self.question_btn)

        self.ftc_btn = AnimatedButton("FTC")
        self.ftc_btn.setObjectName("CreateModeMenuButton")
        self.ftc_btn.setProperty("skipClickSfx", True)
        self.ftc_btn.setProperty("disablePressMotion", True)
        self.ftc_btn.setMinimumWidth(196)
        self.ftc_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.ftc_btn.set_motion_scale_range(0.0)
        self.ftc_btn.set_motion_press_scale(0.0)
        self.ftc_btn.clicked.connect(self._request_ftc)
        surface_layout.addWidget(self.ftc_btn)

    def popup_from(self, anchor: QWidget) -> None:
        if self.isVisible():
            self.hide()
            return

        self.adjustSize()
        end_rect = QRect(anchor.mapToGlobal(QPoint(0, anchor.height() + 6)), self.sizeHint())
        screen = QGuiApplication.screenAt(end_rect.center()) or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            if end_rect.right() > available.right() - 8:
                end_rect.moveRight(available.right() - 8)
            if end_rect.bottom() > available.bottom() - 8:
                end_rect.moveBottom(available.bottom() - 8)
            if end_rect.left() < available.left() + 8:
                end_rect.moveLeft(available.left() + 8)

        start_rect = QRect(end_rect)
        start_rect.translate(0, -4)

        self.setGeometry(start_rect)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()

        if self._animation_group is not None:
            self._animation_group.stop()

        geometry_animation = QPropertyAnimation(self, b"geometry", self)
        geometry_animation.setDuration(_motion_duration(170))
        geometry_animation.setStartValue(start_rect)
        geometry_animation.setEndValue(end_rect)
        geometry_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        opacity_animation = QPropertyAnimation(self, b"windowOpacity", self)
        opacity_animation.setDuration(_motion_duration(160))
        opacity_animation.setStartValue(0.0)
        opacity_animation.setEndValue(1.0)
        opacity_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._animation_group = QParallelAnimationGroup(self)
        self._animation_group.addAnimation(geometry_animation)
        self._animation_group.addAnimation(opacity_animation)
        self._animation_group.start()

    def _request_question(self) -> None:
        self.hide()
        self.question_requested.emit()

    def _request_ftc(self) -> None:
        self.hide()
        self.ftc_requested.emit()


class QuickAddMenu(QWidget):
    web_lesson_requested = Signal()
    wikipedia_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setObjectName("QuickAddMenu")
        polish_popup_window(self, set_frameless=False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._animation_group: QParallelAnimationGroup | None = None

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.surface = QFrame(self)
        self.surface.setObjectName("CreateModeMenuSurface")
        root_layout.addWidget(self.surface)

        surface_layout = QVBoxLayout(self.surface)
        surface_layout.setContentsMargins(10, 10, 10, 10)
        surface_layout.setSpacing(6)

        header = QLabel("Add")
        header.setObjectName("SmallMeta")
        surface_layout.addWidget(header)

        self.web_lesson_btn = AnimatedButton("Web Lesson")
        self.web_lesson_btn.setObjectName("CreateModeMenuButton")
        self.web_lesson_btn.setProperty("skipClickSfx", True)
        self.web_lesson_btn.setProperty("disablePressMotion", True)
        self.web_lesson_btn.setMinimumWidth(196)
        self.web_lesson_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.web_lesson_btn.set_motion_scale_range(0.0)
        self.web_lesson_btn.set_motion_press_scale(0.0)
        self.web_lesson_btn.clicked.connect(self._request_web_lesson)
        surface_layout.addWidget(self.web_lesson_btn)

        self.wikipedia_btn = AnimatedButton("Wikipedia")
        self.wikipedia_btn.setObjectName("CreateModeMenuButton")
        self.wikipedia_btn.setProperty("skipClickSfx", True)
        self.wikipedia_btn.setProperty("disablePressMotion", True)
        self.wikipedia_btn.setMinimumWidth(196)
        self.wikipedia_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.wikipedia_btn.set_motion_scale_range(0.0)
        self.wikipedia_btn.set_motion_press_scale(0.0)
        self.wikipedia_btn.clicked.connect(self._request_wikipedia)
        surface_layout.addWidget(self.wikipedia_btn)

    def popup_from(self, anchor: QWidget) -> None:
        if self.isVisible():
            self.hide()
            return

        self.adjustSize()
        end_rect = QRect(anchor.mapToGlobal(QPoint(0, anchor.height() + 6)), self.sizeHint())
        screen = QGuiApplication.screenAt(end_rect.center()) or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            if end_rect.right() > available.right() - 8:
                end_rect.moveRight(available.right() - 8)
            if end_rect.bottom() > available.bottom() - 8:
                end_rect.moveBottom(available.bottom() - 8)
            if end_rect.left() < available.left() + 8:
                end_rect.moveLeft(available.left() + 8)

        start_rect = QRect(end_rect)
        start_rect.translate(0, -4)

        self.setGeometry(start_rect)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()

        if self._animation_group is not None:
            self._animation_group.stop()

        geometry_animation = QPropertyAnimation(self, b"geometry", self)
        geometry_animation.setDuration(_motion_duration(170))
        geometry_animation.setStartValue(start_rect)
        geometry_animation.setEndValue(end_rect)
        geometry_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        opacity_animation = QPropertyAnimation(self, b"windowOpacity", self)
        opacity_animation.setDuration(_motion_duration(160))
        opacity_animation.setStartValue(0.0)
        opacity_animation.setEndValue(1.0)
        opacity_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._animation_group = QParallelAnimationGroup(self)
        self._animation_group.addAnimation(geometry_animation)
        self._animation_group.addAnimation(opacity_animation)
        self._animation_group.start()

    def _request_web_lesson(self) -> None:
        self.hide()
        self.web_lesson_requested.emit()

    def _request_wikipedia(self) -> None:
        self.hide()
        self.wikipedia_requested.emit()


class WebLessonDialog(QDialog):
    def __init__(self, *, parent: "MainWindow", url: str) -> None:
        super().__init__(parent, Qt.Dialog)
        self.setModal(False)
        self.setObjectName("WebLessonDialog")
        self._url = url
        self.setWindowTitle("ONCard Web Lesson")
        self.setStyleSheet(
            """
            QDialog#WebLessonDialog {
                background: #f6f8fb;
            }
            QFrame#WebLessonCard {
                background: #ffffff;
                border: 1px solid rgba(26, 39, 64, 0.10);
                border-radius: 18px;
            }
            QLabel#WebLessonTitle {
                color: #172033;
                font-size: 24px;
                font-weight: 800;
            }
            QLabel#WebLessonText {
                color: #526275;
                font-size: 13px;
                line-height: 1.35;
            }
            QLabel#WebLessonWarning {
                color: #5f4415;
                background: rgba(255, 214, 125, 0.32);
                border: 1px solid rgba(183, 130, 35, 0.24);
                border-radius: 16px;
                padding: 12px;
            }
            QLabel#WebLessonQr {
                background: #ffffff;
                border: 1px solid rgba(26, 39, 64, 0.10);
                border-radius: 14px;
                padding: 0px;
            }
            QLineEdit#WebLessonLink {
                background: #ffffff;
                border: 1px solid rgba(26, 39, 64, 0.12);
                border-radius: 14px;
                padding: 10px 12px;
                color: #172033;
            }
            QPushButton#WebLessonPrimaryButton {
                background: #172033;
                color: white;
                border: none;
                border-radius: 14px;
                padding: 10px 16px;
                font-weight: 700;
            }
            QPushButton#WebLessonGhostButton {
                background: #ffffff;
                color: #172033;
                border: 1px solid rgba(26, 39, 64, 0.12);
                border-radius: 14px;
                padding: 10px 16px;
                font-weight: 700;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        card = QFrame(self)
        card.setObjectName("WebLessonCard")
        root.addWidget(card)

        body = QVBoxLayout(card)
        body.setContentsMargins(24, 22, 24, 22)
        body.setSpacing(16)

        top = QHBoxLayout()
        top.setSpacing(12)
        title_group = QVBoxLayout()
        title_group.setSpacing(5)
        title = QLabel("Web Lesson")
        title.setObjectName("WebLessonTitle")
        title_group.addWidget(title)
        status = QLabel("Hosted by this ONCard desktop app")
        status.setObjectName("WebLessonText")
        title_group.addWidget(status)
        top.addLayout(title_group, 1)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("WebLessonGhostButton")
        close_btn.clicked.connect(self.close)
        top.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)
        body.addLayout(top)

        copy = QLabel("Open this link in your browser, or scan the QR code, to study on another device connected to this network.")
        copy.setObjectName("WebLessonText")
        copy.setWordWrap(True)
        body.addWidget(copy)

        qr_label = QLabel()
        qr_label.setObjectName("WebLessonQr")
        qr_label.setFixedSize(284, 284)
        qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_label.setPixmap(self._qr_pixmap(url))
        body.addWidget(qr_label, 0, Qt.AlignmentFlag.AlignCenter)

        link_row = QHBoxLayout()
        link_row.setSpacing(10)
        link_field = QLineEdit(url)
        link_field.setObjectName("WebLessonLink")
        link_field.setReadOnly(True)
        link_field.selectAll()
        link_row.addWidget(link_field, 1)
        copy_btn = QPushButton("Copy")
        copy_btn.setObjectName("WebLessonPrimaryButton")
        copy_btn.clicked.connect(lambda: self._copy_link(copy_btn))
        link_row.addWidget(copy_btn)
        body.addLayout(link_row)

        warning = QLabel("Keep ONCard running and do not shut down this computer during a Web Lesson. After opening the lesson on another device, you can safely close this window.")
        warning.setObjectName("WebLessonWarning")
        warning.setWordWrap(True)
        body.addWidget(warning)

        self.resize(520, 620)

    def _copy_link(self, button: QPushButton) -> None:
        app = QApplication.instance()
        if app is not None:
            app.clipboard().setText(self._url)
        button.setText("Copied")
        QTimer.singleShot(1300, lambda: button.setText("Copy"))

    def _qr_pixmap(self, url: str) -> QPixmap:
        try:
            import cv2

            encoder = cv2.QRCodeEncoder_create()
            image = encoder.encode(url)
            if image is None or image.size <= 0:
                raise RuntimeError("OpenCV returned an empty QR image.")
            height, width = image.shape[:2]
            if len(image.shape) == 2:
                qimage = QImage(image.data, width, height, image.strides[0], QImage.Format.Format_Grayscale8).copy()
            else:
                rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                qimage = QImage(rgb.data, width, height, rgb.strides[0], QImage.Format.Format_RGB888).copy()
            pixmap = QPixmap.fromImage(qimage)
            return pixmap.scaled(260, 260, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        except Exception as exc:
            pixmap = QPixmap(260, 260)
            pixmap.fill(QColor("#ffffff"))
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(QColor("#526275"))
            painter.drawText(
                pixmap.rect().adjusted(18, 18, -18, -18),
                int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                f"QR unavailable.\nUse the link below.\n\n{str(exc)[:90]}",
            )
            painter.end()
            return pixmap


class CreateOverlayDialog(QDialog):
    def __init__(self, *, parent: "MainWindow", create_tab: CreateTab, blur_target: QWidget) -> None:
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        polish_popup_window(self)
        self.setObjectName("CreateOverlayDialog")
        self._create_tab = create_tab
        self._blur_target = blur_target
        self._overlay_target = parent
        self._overlay: QWidget | None = None
        self._previous_effect = None
        self._active_session = "idle"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.card = QFrame(self)
        self.card.setObjectName("CreateOverlayCard")
        root.addWidget(self.card)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(18, 18, 18, 18)
        card_layout.setSpacing(12)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        self.header_label = QLabel("Create")
        self.header_label.setObjectName("SmallMeta")
        header.addWidget(self.header_label)
        self.header_controls_host = QWidget()
        self.header_controls_host.setObjectName("CreateOverlayHeaderControls")
        self.header_controls_layout = QHBoxLayout(self.header_controls_host)
        self.header_controls_layout.setContentsMargins(0, 0, 0, 0)
        self.header_controls_layout.setSpacing(10)
        header.addWidget(self.header_controls_host, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)

        self.header_ftc_menu_btn = QPushButton("")
        self.header_ftc_menu_btn.setObjectName("CreateOverlayUploadButton")
        self.header_ftc_menu_btn.setFixedSize(32, 32)
        self.header_ftc_menu_btn.setIcon(parent.icons.icon("common", "menu", "M"))
        self.header_ftc_menu_btn.setIconSize(QSize(16, 16))
        self.header_ftc_menu_btn.setToolTip("FTC controls")
        self.header_ftc_menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header_ftc_menu_btn.clicked.connect(self._create_tab.open_ftc_controls_dialog)
        header.addWidget(self.header_ftc_menu_btn, 0, Qt.AlignmentFlag.AlignTop)

        self.header_upload_btn = QPushButton("")
        self.header_upload_btn.setObjectName("CreateOverlayUploadButton")
        self.header_upload_btn.setFixedSize(32, 32)
        self.header_upload_btn.setIcon(parent.icons.icon("common", "upload", "U"))
        self.header_upload_btn.setIconSize(QSize(16, 16))
        self.header_upload_btn.setToolTip("Add files")
        self.header_upload_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header_upload_btn.clicked.connect(self._create_tab.browse_ftc_files)
        header.addWidget(self.header_upload_btn, 0, Qt.AlignmentFlag.AlignTop)

        self.close_btn = QPushButton("")
        self.close_btn.setObjectName("CreateOverlayCloseButton")
        self.close_btn.setFixedSize(32, 32)
        self.close_btn.setIcon(parent.icons.icon("common", "cross_two", "X"))
        self.close_btn.setIconSize(QSize(12, 12))
        self.close_btn.setToolTip("Close")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.reject)
        header.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)
        card_layout.addLayout(header)

        self.content_layout = QHBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(16)
        card_layout.addLayout(self.content_layout, 1)

        self.resize(1180, 760)

    def open_session(self, session_kind: str) -> int:
        self._active_session = session_kind
        self.header_label.setText("Question" if session_kind == "question" else "Files To Cards")
        self.resize(980, 650 if session_kind == "question" else 740)
        self._clear_content_layout()
        self._clear_header_controls()
        self._create_tab.mount_overlay_content(self.content_layout, session_kind, self.header_controls_layout)
        ftc_active = session_kind == "ftc"
        question_active = session_kind == "question"
        self.header_controls_host.setVisible(ftc_active or question_active)
        self.header_upload_btn.setVisible(ftc_active)
        self.header_ftc_menu_btn.setVisible(ftc_active)
        self._apply_backdrop()
        try:
            self._resize_for_available_space()
            self._center_on_target()
            return self.exec()
        finally:
            self._create_tab.restore_overlay_content()
            self._clear_header_controls()
            self._clear_content_layout()
            self._clear_backdrop()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self.card.geometry().contains(event.position().toPoint()):
            self.reject()
            event.accept()
            return
        super().mousePressEvent(event)

    def _center_on_target(self) -> None:
        target_rect = self._blur_target.geometry()
        top_left = self._blur_target.mapToGlobal(QPoint(0, 0))
        frame = QRect(top_left, target_rect.size())
        self.move(
            int(frame.center().x() - (self.width() / 2)),
            int(frame.center().y() - (self.height() / 2)),
        )

    def _resize_for_available_space(self) -> None:
        layout = self.layout()
        if layout is not None:
            layout.activate()
        card_layout = self.card.layout()
        if card_layout is not None:
            card_layout.activate()
        screen = self.screen() or QGuiApplication.primaryScreen()
        content_hint = self.sizeHint()
        if screen is None:
            self.resize(content_hint)
            return
        available = screen.availableGeometry()
        target_width = min(max(900, content_hint.width()), max(820, available.width() - 120))
        target_height = min(max(580, content_hint.height()), max(520, available.height() - 130))
        self.resize(target_width, target_height)

    def _apply_backdrop(self) -> None:
        self._previous_effect = self._blur_target.graphicsEffect()
        blur = QGraphicsBlurEffect(self._blur_target)
        blur.setBlurRadius(13.0)
        self._blur_target.setGraphicsEffect(blur)

        overlay = QWidget(self._overlay_target)
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        overlay.setObjectName("CreateOverlayBackdrop")
        overlay.setStyleSheet("QWidget#CreateOverlayBackdrop { background: rgba(148, 148, 148, 0.30); }")
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
        try:
            self._blur_target.setGraphicsEffect(self._previous_effect)
        except RuntimeError:
            self._blur_target.setGraphicsEffect(None)
        self._previous_effect = None

    def _clear_content_layout(self) -> None:
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

    def _clear_header_controls(self) -> None:
        while self.header_controls_layout.count():
            item = self.header_controls_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        self.header_controls_host.setVisible(False)
        self.header_upload_btn.setVisible(False)
        self.header_ftc_menu_btn.setVisible(False)


class MainWindow(QMainWindow):
    AUDIO_TEST_MESSAGES = (
        "I got rick rolled.",
        "So... you are testing me...",
        "I LOVE BEING TESTING.",
        "To the glory...",
        "This toast has achieved lift-off.",
        "Your ears have entered the chat.",
        "Beep responsibly.",
        "I am definitely not a microwave.",
        "Professional toast reporting for duty.",
        "This is only a drill, probably.",
        "Tiny sound, enormous confidence.",
        "The button has been perceived.",
        "One ping to rule them all.",
        "Certified ding moment.",
        "I came. I saw. I toasted.",
        "Sound check: emotionally available.",
        "This notification believes in you.",
        "The toast council approves.",
        "Do not feed after midnight.",
        "Another test? Bold. I respect it.",
    )

    def __init__(
        self,
        paths,
        datastore: DataStore,
        ollama: OllamaService,
        icons: IconHelper,
        preflight: ModelPreflightService,
        session_controller=None,
    ) -> None:
        super().__init__()
        self.paths = paths
        self.datastore = datastore
        self.ollama = ollama
        self.icons = icons
        self.preflight = preflight
        self.session_controller = session_controller
        self.sounds = UiSoundBank(self.paths.assets / "sfx")
        self.sounds.configure(self.datastore.load_setup())
        self._click_sfx_filter = ClickSoundFilter(self.sounds, self)
        self._app_menu = AppIconMenu(self)
        self._profile_menu = UserProfileMenu(self)
        self._notifications_menu = NotificationsMenu(self)
        self._create_mode_menu = CreateModeMenu(self)
        self._quick_add_menu = QuickAddMenu(self)
        self._web_lesson_server: WebLessonServer | None = None
        self._web_lesson_dialog: WebLessonDialog | None = None
        self._app_menu.profiles_requested.connect(self._open_profiles_overlay)
        self._profile_menu.view_stats_requested.connect(self._open_stats_dialog)
        self._notifications_menu.notifications_toggled.connect(self._set_notifications_enabled)
        self._create_mode_menu.question_requested.connect(self._begin_question_create_flow)
        self._create_mode_menu.ftc_requested.connect(self._begin_ftc_create_flow)
        self._quick_add_menu.web_lesson_requested.connect(self._open_web_lesson)
        self._quick_add_menu.wikipedia_requested.connect(self._open_wikipedia_search_entry)
        self._profile_hover_timer = QTimer(self)
        self._profile_hover_timer.setSingleShot(True)
        self._profile_hover_timer.timeout.connect(self._show_profile_menu_from_hover)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self._click_sfx_filter)
        self._update_shutdown_requested = False
        self._start_maximized = True
        self._pseudo_maximized = False
        self._mcq_startup_generation_scheduled = False
        self._sizing_pseudo = False
        self._normal_geometry: QRect | None = None
        self._maximized_geometry: QRect | None = None
        self._window_anim: QPropertyAnimation | None = None
        self._opacity_anim: QPropertyAnimation | None = None
        self._closing = False
        self._close_anim: QParallelAnimationGroup | None = None
        self.setWindowTitle(app_name_with_release_channel("ONCard"))
        self.setObjectName("OnCardMainWindow")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setMinimumSize(760, 540)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self._apply_initial_geometry()
        self._init_tray_icon()
        self._ensure_notification_defaults()
        self._build_ui()
        self._wiki_search_shortcut = QShortcut(QKeySequence("Ctrl+Space"), self)
        self._wiki_search_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._wiki_search_shortcut.activated.connect(self._open_wikipedia_search_entry)
        self._create_overlay_dialog = CreateOverlayDialog(parent=self, create_tab=self.create_tab, blur_target=self._app_shell)
        self._apply_native_window_chrome()

    def _apply_initial_geometry(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1480, 920)
            return
        available = screen.availableGeometry()
        width = min(1600, max(self.minimumWidth(), int(available.width() * 0.93)))
        height = min(980, max(self.minimumHeight(), int(available.height() * 0.93)))
        width = min(width, max(self.minimumWidth(), available.width()))
        height = min(height, max(self.minimumHeight(), available.height()))
        self.resize(width, height)

    def _build_ui(self) -> None:
        shell = QWidget()
        shell.setObjectName("AppShell")
        shell.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._app_shell = shell
        layout = QVBoxLayout(shell)
        layout.setContentsMargins(22, 12, 22, 22)
        layout.setSpacing(14)

        self.title_bar = WindowDragBar(self)
        self.title_bar.setObjectName("WindowTitleBar")
        self.title_bar.setFixedHeight(44)
        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(6, 4, 6, 4)
        title_layout.setSpacing(8)

        left_cluster = QWidget(self.title_bar)
        left_cluster.setObjectName("WindowLeftCluster")
        left_layout = QHBoxLayout(left_cluster)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)

        self.app_icon_btn = AnimatedButton("")
        self.app_icon_btn.setObjectName("AppIconButton")
        self.app_icon_btn.setFixedSize(34, 34)
        self.app_icon_btn.setIcon(self._rounded_app_icon())
        self.app_icon_btn.setIconSize(QSize(22, 22))
        self.app_icon_btn.setToolTip("Open ONCard links")
        self.app_icon_btn.setProperty("skipClickSfx", True)
        self.app_icon_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.app_icon_btn.set_motion_scale_range(0.12)
        self.app_icon_btn.set_motion_lift(2.0)
        self.app_icon_btn.clicked.connect(self._toggle_app_menu)
        left_layout.addWidget(self.app_icon_btn, 0, Qt.AlignmentFlag.AlignLeft)

        self.settings_btn = self._build_icon_button("settings_info", "Settings", self._open_settings)
        left_layout.addWidget(self.settings_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.user_btn = self._build_icon_button("user", "Profile", self._toggle_profile_menu)
        self.user_btn.setToolTip("")
        self.user_btn.installEventFilter(self)
        left_layout.addWidget(self.user_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.feedback_btn = self._build_icon_button(
            "bug",
            "Feedback",
            lambda: QDesktopServices.openUrl(QUrl("https://github.com/MightyXdash/ONCard/issues/new")),
        )
        left_layout.addWidget(self.feedback_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.envelope_btn = self._build_icon_button("envelope", "Notifications", self._toggle_notifications_menu)
        left_layout.addWidget(self.envelope_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.quick_add_btn = self._build_icon_button("plus", "Quick add", self._toggle_quick_add_menu)
        left_layout.addWidget(self.quick_add_btn, 0, Qt.AlignmentFlag.AlignLeft)
        title_layout.addWidget(left_cluster, 0, Qt.AlignmentFlag.AlignLeft)

        title_layout.addStretch(1)

        mode_cluster = QWidget(self.title_bar)
        mode_cluster.setObjectName("WindowModeCluster")
        mode_layout = QHBoxLayout(mode_cluster)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(16)

        self.create_btn = AnimatedButton("Create")
        self.create_btn.setObjectName("TopNavButton")
        self.create_btn.setCheckable(True)
        self.create_btn.setChecked(True)
        self.create_btn.setProperty("skipClickSfx", True)
        self.create_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.create_btn.setMinimumHeight(30)
        self.create_btn.set_motion_scale_range(0.0)
        self.create_btn.set_motion_hover_grow(0, 0)
        self.create_btn.set_motion_lift(0.0)
        self.create_btn.set_motion_press_scale(0.06)

        self.cards_btn = AnimatedButton("Cards")
        self.cards_btn.setObjectName("TopNavButton")
        self.cards_btn.setCheckable(True)
        self.cards_btn.setProperty("skipClickSfx", True)
        self.cards_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.cards_btn.setMinimumHeight(30)
        self.cards_btn.set_motion_scale_range(0.0)
        self.cards_btn.set_motion_hover_grow(0, 0)
        self.cards_btn.set_motion_lift(0.0)
        self.cards_btn.set_motion_press_scale(0.06)

        self.mcq_btn = AnimatedButton("MCQs")
        self.mcq_btn.setObjectName("TopNavButton")
        self.mcq_btn.setCheckable(True)
        self.mcq_btn.setProperty("skipClickSfx", True)
        self.mcq_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.mcq_btn.setMinimumHeight(30)
        self.mcq_btn.set_motion_scale_range(0.0)
        self.mcq_btn.set_motion_hover_grow(0, 0)
        self.mcq_btn.set_motion_lift(0.0)
        self.mcq_btn.set_motion_press_scale(0.06)

        self.create_btn.clicked.connect(self._handle_create_button)
        self.cards_btn.clicked.connect(lambda: self._play_and_switch(1))
        self.mcq_btn.clicked.connect(lambda: self._play_and_switch(2))
        mode_layout.addWidget(self.create_btn)
        mode_layout.addWidget(self.cards_btn)
        mode_layout.addWidget(self.mcq_btn)
        title_layout.addWidget(mode_cluster, 0, Qt.AlignmentFlag.AlignRight)

        separator = QLabel("|")
        separator.setObjectName("WindowControlSeparator")
        separator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_layout.addWidget(separator, 0, Qt.AlignmentFlag.AlignVCenter)

        right_cluster = QWidget(self.title_bar)
        right_cluster.setObjectName("WindowRightCluster")
        right_layout = QHBoxLayout(right_cluster)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(20)

        self.minimize_btn = self._build_window_button("minimize", "Minimize", self._minimize_with_animation)
        right_layout.addWidget(self.minimize_btn, 0, Qt.AlignmentFlag.AlignRight)
        self.max_restore_btn = self._build_window_button("expand", "Maximize", self._toggle_maximize_restore)
        right_layout.addWidget(self.max_restore_btn, 0, Qt.AlignmentFlag.AlignRight)
        self.close_btn = self._build_window_button("close", "Close", self.close, close_role=True)
        right_layout.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignRight)
        title_layout.addWidget(right_cluster, 0, Qt.AlignmentFlag.AlignRight)

        layout.addWidget(self.title_bar)

        self.stack = AnimatedStackedWidget()
        self.create_tab = CreateTab(self.datastore, self.ollama, self.icons, self.preflight)
        self.study_tab = StudyTab(self.datastore, self.ollama, self.icons, self.preflight)
        self.mcq_tab = MCQTab(self.datastore, self.ollama, self.icons, self.preflight)
        self.create_tab.card_saved.connect(self.study_tab.mark_cards_dirty)
        self.create_tab.card_saved.connect(self.mcq_tab.mark_cards_dirty)
        self.create_tab.ftc_completed.connect(self._notify_ftc_completed)
        self.stack.addWidget(self.create_tab)
        self.stack.addWidget(self.study_tab)
        self.stack.addWidget(self.mcq_tab)
        layout.addWidget(self.stack, 1)

        self.setCentralWidget(shell)
        self._stats_overlay = QWidget(shell)
        self._stats_overlay.setObjectName("StatsBackdropOverlay")
        self._stats_overlay.setStyleSheet("QWidget#StatsBackdropOverlay { background: rgba(255, 255, 255, 0.44); border: none; }")
        self._stats_overlay.hide()
        self._stats_overlay.raise_()
        self._position_stats_overlay()
        self.statusBar().setSizeGripEnabled(False)
        self._sync_nav_icons()
        self._sync_window_controls()
        self._switch_tab(1)

    def _position_stats_overlay(self) -> None:
        overlay = getattr(self, "_stats_overlay", None)
        shell = getattr(self, "_app_shell", None)
        if overlay is None or shell is None:
            return
        overlay.setGeometry(shell.rect())

    def _apply_native_window_chrome(self) -> None:
        rounded = not (self._pseudo_maximized or self.isMaximized())
        polish_windows_window(self, rounded=rounded, small_corners=False, remove_border=True, native_shadow=True)

    def _build_icon_button(self, icon_name: str, label: str, callback) -> AnimatedButton:
        button = AnimatedButton("")
        button.setObjectName("WindowIconButton")
        button.setFixedSize(30, 30)
        button.setIcon(self.icons.icon("common", icon_name, label[:1]))
        button.setIconSize(QSize(16, 16))
        button.setToolTip(label)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.set_motion_scale_range(0.12)
        button.set_motion_lift(2.0)
        button.clicked.connect(callback)
        return button

    def _build_window_button(self, icon_name: str, label: str, callback, *, close_role: bool = False) -> AnimatedButton:
        button = AnimatedButton("")
        button.setObjectName("WindowControlCloseButton" if close_role else "WindowControlButton")
        button.setFixedSize(32, 32)
        button.setIcon(self.icons.icon("common", icon_name, label[:1]))
        button.setIconSize(QSize(16, 16))
        button.setToolTip(label)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.set_motion_scale_range(0.1)
        button.set_motion_lift(2.0)
        button.clicked.connect(callback)
        return button

    def _rounded_app_icon(self) -> QIcon:
        icon_path = self.paths.icons / "app" / "app_logo.png"
        if not icon_path.exists():
            return self.icons.icon("app", "app_logo", "O")

        source = QPixmap(str(icon_path))
        if source.isNull():
            return self.icons.icon("app", "app_logo", "O")

        target = QPixmap(64, 64)
        target.fill(Qt.GlobalColor.transparent)
        painter = QPainter(target)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        path = QPainterPath()
        path.addRoundedRect(QRect(0, 0, 64, 64), 16, 16)
        painter.setClipPath(path)
        painter.drawPixmap(target.rect(), source, source.rect())
        painter.end()
        return QIcon(target)

    def _toggle_app_menu(self) -> None:
        if self._create_mode_menu.isVisible():
            self._create_mode_menu.hide()
        if self._quick_add_menu.isVisible():
            self._quick_add_menu.hide()
        if self._profile_menu.isVisible():
            self._profile_menu.hide()
        if self._notifications_menu.isVisible():
            self._notifications_menu.hide()
        if self.session_controller is not None:
            self._app_menu.set_accounts(self.session_controller.list_accounts(), self.session_controller.active_account_id())
        self._app_menu.popup_from(self.app_icon_btn)

    def _open_profiles_overlay(self) -> None:
        if self.session_controller is None:
            return
        if self._profile_menu.isVisible():
            self._profile_menu.hide()
        if self._notifications_menu.isVisible():
            self._notifications_menu.hide()
        accounts = self.session_controller.list_accounts()
        active_id = self.session_controller.active_account_id()
        selected_id = ProfilesOverlayDialog(
            parent=self,
            icons=self.icons,
            accounts=accounts,
            active_id=active_id,
            blur_target=self._app_shell,
            anchor=self.app_icon_btn,
        ).exec_with_backdrop()
        if selected_id and selected_id != active_id:
            self._on_account_selected(selected_id)

    def _toggle_profile_menu(self) -> None:
        if self._create_mode_menu.isVisible():
            self._create_mode_menu.hide()
        if self._quick_add_menu.isVisible():
            self._quick_add_menu.hide()
        if self._app_menu.isVisible():
            self._app_menu.hide()
        if self._notifications_menu.isVisible():
            self._notifications_menu.hide()
        self._profile_menu.set_profile(self.datastore.load_profile())
        self._profile_menu.popup_from(self.user_btn)

    def _toggle_notifications_menu(self) -> None:
        if self._create_mode_menu.isVisible():
            self._create_mode_menu.hide()
        if self._quick_add_menu.isVisible():
            self._quick_add_menu.hide()
        if self._app_menu.isVisible():
            self._app_menu.hide()
        if self._profile_menu.isVisible():
            self._profile_menu.hide()
        enabled = bool(self.datastore.load_setup().get("notifications", {}).get("enabled", False))
        self._notifications_menu.set_enabled(enabled)
        self._notifications_menu.popup_from(self.envelope_btn)

    def _handle_create_button(self) -> None:
        current_index = self.stack.currentIndex()
        self.create_btn.setChecked(current_index == 0)
        self.cards_btn.setChecked(current_index == 1)
        self.mcq_btn.setChecked(current_index == 2)
        self._sync_nav_icons()
        if self.create_tab.should_show_create_selector():
            self._create_mode_menu.popup_from(self.create_btn)
            return
        self._open_create_overlay(self.create_tab.reopen_session_kind())

    def _begin_question_create_flow(self) -> None:
        self.create_tab.begin_question_session()
        self._open_create_overlay("question")

    def _begin_ftc_create_flow(self) -> None:
        self.create_tab.begin_ftc_session()
        self._open_create_overlay("ftc")

    def _open_create_overlay(self, session_kind: str) -> None:
        if session_kind not in {"question", "ftc"}:
            return
        self._create_mode_menu.hide()
        self._create_overlay_dialog.open_session(session_kind)

    def _toggle_quick_add_menu(self) -> None:
        if self._create_mode_menu.isVisible():
            self._create_mode_menu.hide()
        if self._app_menu.isVisible():
            self._app_menu.hide()
        if self._profile_menu.isVisible():
            self._profile_menu.hide()
        if self._notifications_menu.isVisible():
            self._notifications_menu.hide()
        self._quick_add_menu.popup_from(self.quick_add_btn)

    def _open_wikipedia_search_entry(self) -> None:
        overlay = self.study_tab.ai_response_overlay
        if overlay is not None:
            if overlay.is_wikipedia_search_entry_open():
                return
            if bool(getattr(overlay, "_closing", False)):
                return
        self._quick_add_menu.hide()
        self._switch_tab(1)
        self.study_tab.open_wikipedia_search_entry()

    def keyPressEvent(self, event) -> None:
        super().keyPressEvent(event)

    def _open_web_lesson(self) -> None:
        try:
            if self._web_lesson_server is None:
                self._web_lesson_server = WebLessonServer(self.datastore, self.ollama)
            url = self._web_lesson_server.start()
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Web Lesson unavailable",
                f"ONCard could not start the Web Lesson server.\n\n{exc}\n\nCheck that your firewall allows ONCard on this network.",
            )
            return
        if self._web_lesson_dialog is not None:
            self._web_lesson_dialog.close()
            self._web_lesson_dialog.deleteLater()
        dialog = WebLessonDialog(parent=self, url=url)
        self._web_lesson_dialog = dialog
        dialog.finished.connect(lambda _result: self._clear_web_lesson_dialog(dialog))
        dialog.show()
        dialog.raise_()

    def _clear_web_lesson_dialog(self, dialog: WebLessonDialog) -> None:
        if self._web_lesson_dialog is dialog:
            self._web_lesson_dialog = None

    def _show_profile_menu_from_hover(self) -> None:
        if self._profile_menu.isVisible():
            return
        if not self.user_btn.underMouse():
            return
        self._profile_menu.set_profile(self.datastore.load_profile())
        self._profile_menu.popup_from(self.user_btn)

    def _sync_nav_icons(self) -> None:
        self.create_btn.setIcon(
            self.icons.icon(
                "create",
                "autofill_magic_white" if self.create_btn.isChecked() else "autofill_magic",
                "C",
            )
        )
        self.cards_btn.setIcon(
            self.icons.icon(
                "study",
                "flashcard_white" if self.cards_btn.isChecked() else "flashcard",
                "C",
            )
        )
        self.mcq_btn.setIcon(
            self.icons.icon(
                "common",
                "mcq_white" if self.mcq_btn.isChecked() else "mcq",
                "M",
            )
        )

    def _sync_window_controls(self) -> None:
        maximized = self.isMaximized() or self._pseudo_maximized
        self.max_restore_btn.setIcon(self.icons.icon("common", "shrink" if maximized else "expand", "M"))
        self.max_restore_btn.setToolTip("Restore Down" if maximized else "Maximize")
        self.max_restore_btn.setEnabled(True)
        self.title_bar.setProperty("windowMaximized", maximized)
        self.title_bar.style().unpolish(self.title_bar)
        self.title_bar.style().polish(self.title_bar)
        self.title_bar.update()
        shell = self.centralWidget()
        if shell is not None:
            shell.setProperty("windowMaximized", maximized)
            shell.style().unpolish(shell)
            shell.style().polish(shell)
            shell.update()

    def _switch_tab(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.create_btn.setChecked(index == 0)
        self.cards_btn.setChecked(index == 1)
        self.mcq_btn.setChecked(index == 2)
        self._sync_nav_icons()
        if index == 1:
            self.study_tab.activate_view()
        elif index == 2:
            self.mcq_tab.activate_view()

    def _play_and_switch(self, index: int) -> None:
        if self._create_mode_menu.isVisible():
            self._create_mode_menu.hide()
        if self.stack.currentIndex() != index:
            self.sounds.play("woosh")
        self._switch_tab(index)

    def _toggle_maximize_restore(self) -> None:
        if self.isMaximized():
            self.showNormal()
        if self._pseudo_maximized:
            if self._normal_geometry is not None:
                self._animate_window_geometry(self._normal_geometry)
            self._pseudo_maximized = False
        else:
            self._apply_pseudo_maximize()
        self._sync_window_controls()

    def _open_settings(self, *, auto_install_model_key: str = "") -> None:
        dialog = SettingsDialog(
            self.datastore,
            self.ollama,
            self.preflight,
            self,
            session_controller=self.session_controller,
            auto_install_model_key=auto_install_model_key,
        )
        result = dialog.exec()
        if result:
            setup = self.datastore.load_setup()
            app = QApplication.instance()
            if app is not None:
                apply_app_theme(app, dict(setup.get("appearance", {})).get("theme", "light"))
            self.sounds.configure(setup)
            self.create_tab.refresh_ftc_defaults()
            self.mcq_tab.activate_view()

    def _open_stats_dialog(self) -> None:
        if self.session_controller is None:
            return
        self._position_stats_overlay()
        self._stats_overlay.show()
        self._stats_overlay.raise_()
        blur = QGraphicsBlurEffect(self._app_shell)
        blur.setBlurRadius(14.0)
        self._app_shell.setGraphicsEffect(blur)
        dialog = StatsDialog(
            self.datastore,
            self.ollama,
            self.session_controller,
            self,
            close_icon_path=self.paths.icons / "common" / "close.png",
        )
        try:
            dialog.exec()
        finally:
            self._stats_overlay.hide()
            try:
                self._app_shell.setGraphicsEffect(None)
            except RuntimeError:
                pass

    def _on_account_selected(self, account_id: str) -> None:
        if self.session_controller is None:
            return
        try:
            self.session_controller.switch_to_account(account_id)
        except Exception as exc:
            QMessageBox.warning(self, "Accounts", str(exc))

    def _set_notifications_enabled(self, enabled: bool) -> None:
        setup = self.datastore.load_setup()
        notifications = dict(setup.get("notifications", {}))
        notifications["enabled"] = bool(enabled)
        setup["notifications"] = notifications
        self.datastore.save_setup(setup)

    def _ensure_notification_defaults(self) -> None:
        setup = self.datastore.load_setup()
        notifications = dict(setup.get("notifications", {}))
        if "enabled" not in notifications:
            notifications["enabled"] = True
            setup["notifications"] = notifications
            self.datastore.save_setup(setup)

    def _init_tray_icon(self) -> None:
        self._tray_icon: QSystemTrayIcon | None = None
        set_windows_app_user_model_id()
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray_icon = self.windowIcon()
        if tray_icon.isNull():
            tray_icon = self.icons.icon("app", "app_logo", "O")
        self._tray_icon = QSystemTrayIcon(tray_icon, self)
        self._tray_icon.setToolTip(app_name_with_release_channel("ONCard"))
        self._tray_icon.show()

    def _notify_ftc_completed(self, subject: str) -> None:
        setup = self.datastore.load_setup()
        enabled = bool(setup.get("notifications", {}).get("enabled", False))
        if not enabled:
            return
        message_subject = str(subject).strip() or "study"
        message_text = f"We have completed making your {message_subject} slides"
        notification_sound = str(setup.get("audio", {}).get("notification_sound", "windows")).strip().lower()
        custom_sound = notification_sound and notification_sound != "windows"
        toast_shown = show_windows_toast("ONCard - FTC", message_text, silent=bool(custom_sound))
        if not toast_shown and self._tray_icon is not None and self._tray_icon.isVisible():
            self._tray_icon.showMessage(
                "ONCard - FTC",
                message_text,
                QSystemTrayIcon.MessageIcon.Information,
                6000,
            )
        if custom_sound:
            for index in range(4):
                QTimer.singleShot(index * 650, lambda sound=notification_sound: self.sounds.play_notification(sound))
        self.show_update_notice(message_text, 6000)

    def show_audio_test_notification(self, sound: str) -> None:
        clean_sound = str(sound or "windows").strip().lower()
        message = random.choice(self.AUDIO_TEST_MESSAGES)
        custom_sound = clean_sound != "windows"
        toast_shown = show_windows_toast("ONCard Dummy Notification", message, silent=custom_sound)
        if not toast_shown and self._tray_icon is not None and self._tray_icon.isVisible():
            self._tray_icon.showMessage(
                "ONCard Dummy Notification",
                message,
                QSystemTrayIcon.MessageIcon.Information,
                4000,
            )
        if custom_sound:
            self.sounds.play_notification(clean_sound)

    def begin_update_shutdown(self) -> None:
        self._update_shutdown_requested = True

    def show_update_notice(self, message: str, timeout_ms: int = 6000) -> None:
        self.statusBar().showMessage(message, timeout_ms)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.WindowStateChange:
            if self.isMaximized() and not self._pseudo_maximized:
                self.showNormal()
                self._apply_pseudo_maximize()
                return
            if not self.isMinimized() and self.windowOpacity() < 1.0:
                self.setWindowOpacity(1.0)
            self._sync_window_controls()
            self._apply_native_window_chrome()
        super().changeEvent(event)

    def moveEvent(self, event) -> None:
        if self._app_menu.isVisible():
            self._app_menu.hide()
        if self._profile_menu.isVisible():
            self._profile_menu.hide()
        if self._notifications_menu.isVisible():
            self._notifications_menu.hide()
        if self._pseudo_maximized and self._maximized_geometry is not None and not self._sizing_pseudo:
            if self.geometry().topLeft() != self._maximized_geometry.topLeft():
                self._pseudo_maximized = False
                self._sync_window_controls()
        super().moveEvent(event)

    def resizeEvent(self, event) -> None:
        if self._app_menu.isVisible():
            self._app_menu.hide()
        if self._profile_menu.isVisible():
            self._profile_menu.hide()
        if self._notifications_menu.isVisible():
            self._notifications_menu.hide()
        if self._pseudo_maximized and self._maximized_geometry is not None and not self._sizing_pseudo:
            if self.geometry().size() != self._maximized_geometry.size():
                self._pseudo_maximized = False
                self._sync_window_controls()
        super().resizeEvent(event)
        self._position_stats_overlay()
        self._apply_native_window_chrome()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._start_maximized:
            self._start_maximized = False
            QTimer.singleShot(0, self._apply_pseudo_maximize)
        self._apply_native_window_chrome()
        if not self._mcq_startup_generation_scheduled:
            self._mcq_startup_generation_scheduled = True
            QTimer.singleShot(3500, self._start_background_mcq_generation)

    def _model_work_busy(self) -> bool:
        if self.create_tab.has_pending_work():
            return True
        study_workers = [
            self.study_tab.grade_worker,
            self.study_tab.queued_grade_worker,
            self.study_tab.followup_worker,
            self.study_tab.reinforcement_worker,
            self.study_tab.session_prep_worker,
            self.study_tab.topic_cluster_worker,
            self.study_tab.ai_query_planner_worker,
            self.study_tab.ai_query_answer_worker,
        ]
        mcq_workers = [
            self.mcq_tab.mcq_worker,
            self.mcq_tab.followup_worker,
        ]
        for worker in study_workers + mcq_workers:
            if worker is not None and worker.isRunning():
                return True
        return False

    def _start_background_mcq_generation(self) -> None:
        if self._model_work_busy():
            QTimer.singleShot(5000, self._start_background_mcq_generation)
            return
        self.mcq_tab.reload_cards(force=True)
        if self._model_work_busy():
            QTimer.singleShot(5000, self._start_background_mcq_generation)
            return
        QTimer.singleShot(250, self.mcq_tab._fill_missing_mcqs_in_background)

    def _animate_window_geometry(self, target: QRect) -> None:
        if self._window_anim is None:
            self._window_anim = QPropertyAnimation(self, b"geometry", self)
            self._window_anim.setDuration(_motion_duration(170))
            self._window_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._window_anim.finished.connect(self._end_window_anim)
        self._sizing_pseudo = True
        self._window_anim.stop()
        self._window_anim.setStartValue(self.geometry())
        self._window_anim.setEndValue(target)
        self._window_anim.start()

    def _end_window_anim(self) -> None:
        self._sizing_pseudo = False

    def _minimize_with_animation(self) -> None:
        if self._opacity_anim is None:
            self._opacity_anim = QPropertyAnimation(self, b"windowOpacity", self)
            self._opacity_anim.setDuration(_motion_duration(140))
            self._opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._opacity_anim.finished.connect(self._finish_minimize)
        self._opacity_anim.stop()
        self._opacity_anim.setStartValue(self.windowOpacity())
        self._opacity_anim.setEndValue(0.0)
        self._opacity_anim.start()

    def _finish_minimize(self) -> None:
        self.showMinimized()
        self.setWindowOpacity(1.0)

    def _start_close_animation(self) -> None:
        if self._closing:
            return
        self._closing = True
        start_geom = self.geometry()
        scale = 0.92
        end_w = max(int(start_geom.width() * scale), 200)
        end_h = max(int(start_geom.height() * scale), 200)
        center = start_geom.center()
        end_geom = QRect(
            center.x() - end_w // 2,
            center.y() - end_h // 2,
            end_w,
            end_h,
        )

        geo_anim = QPropertyAnimation(self, b"geometry", self)
        geo_anim.setDuration(_motion_duration(170))
        geo_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        geo_anim.setStartValue(start_geom)
        geo_anim.setEndValue(end_geom)

        opacity_anim = QPropertyAnimation(self, b"windowOpacity", self)
        opacity_anim.setDuration(_motion_duration(160))
        opacity_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        opacity_anim.setStartValue(self.windowOpacity())
        opacity_anim.setEndValue(0.0)

        group = QParallelAnimationGroup(self)
        group.addAnimation(geo_anim)
        group.addAnimation(opacity_anim)

        def _finish() -> None:
            self._close_anim = None
            QMainWindow.close(self)

        group.finished.connect(_finish)
        self._close_anim = group
        group.start()

    def _apply_pseudo_maximize(self) -> None:
        screen = QGuiApplication.screenAt(self.frameGeometry().center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        margin = 2
        target = QRect(available)
        target.setHeight(max(self.minimumHeight(), available.height() - margin))
        if self._normal_geometry is None or not self._pseudo_maximized:
            self._normal_geometry = self.geometry()
        self._animate_window_geometry(target)
        self._maximized_geometry = target
        self._pseudo_maximized = True
        self._apply_native_window_chrome()
        self._sync_window_controls()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.user_btn:
            if event.type() == QEvent.Type.Enter:
                self._profile_hover_timer.start(1650)
            elif event.type() == QEvent.Type.Leave:
                self._profile_hover_timer.stop()
        return super().eventFilter(watched, event)

    def closeEvent(self, event) -> None:
        if self._closing:
            if self._web_lesson_server is not None:
                self._web_lesson_server.stop()
                self._web_lesson_server = None
            super().closeEvent(event)
            return
        self._app_menu.hide()
        self._profile_menu.hide()
        self._notifications_menu.hide()
        self._create_mode_menu.hide()
        self._quick_add_menu.hide()
        if not self._update_shutdown_requested and self.create_tab.has_pending_work():
            answer = QMessageBox.question(
                self,
                "Force quit?",
                "ONCard is still processing queued work. Do you want to force quit?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        if self._update_shutdown_requested:
            if self._web_lesson_server is not None:
                self._web_lesson_server.stop()
                self._web_lesson_server = None
            super().closeEvent(event)
            return
        event.ignore()
        self._start_close_animation()
