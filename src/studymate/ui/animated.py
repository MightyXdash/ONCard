from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, QRect, Qt, QVariantAnimation, QSize, QTimer, QPointF
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPalette, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QLabel,
    QLineEdit,
    QListView,
    QPushButton,
    QStackedWidget,
    QStyle,
    QStyleOptionButton,
    QStyleOptionToolButton,
    QStylePainter,
    QToolButton,
    QWidget,
)

from studymate.ui.window_effects import polish_popup_window


def _refresh_style(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def polish_surface(widget: QWidget, *, sidebar: bool = False) -> None:
    del sidebar
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)


def _reduced_motion_enabled() -> bool:
    app = QApplication.instance()
    return bool(app.property("reducedMotion")) if app is not None else False


def _motion_duration(duration: int) -> int:
    return 1 if _reduced_motion_enabled() else duration


def fade_widget_visibility(widget: QWidget, visible: bool, duration: int = 180) -> None:
    if _reduced_motion_enabled():
        widget.setVisible(visible)
        widget.setMaximumHeight(16777215)
        return

    animation = getattr(widget, "_height_animation", None)
    if animation is None:
        animation = QPropertyAnimation(widget, b"maximumHeight", widget)
        animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

        def _finish() -> None:
            target_visible = bool(getattr(widget, "_height_target_visible", widget.isVisible()))
            widget.setMaximumHeight(16777215)
            if not target_visible:
                widget.setVisible(False)

        animation.finished.connect(_finish)
        widget._height_animation = animation  # type: ignore[attr-defined]

    animation.stop()
    animation.setDuration(_motion_duration(duration))
    widget._height_target_visible = visible  # type: ignore[attr-defined]

    if visible:
        start_height = max(int(widget.height()), 0)
        target_height = max(int(widget.sizeHint().height()), start_height, 1)
        widget._expanded_height = target_height  # type: ignore[attr-defined]
        widget.setVisible(True)
        widget.setMaximumHeight(start_height)
        animation.setStartValue(start_height)
        animation.setEndValue(target_height)
        animation.start()
        return

    if not widget.isVisible():
        return
    expanded_height = int(getattr(widget, "_expanded_height", max(widget.sizeHint().height(), widget.height(), 1)))
    animation.setStartValue(max(widget.height(), expanded_height))
    animation.setEndValue(0)
    animation.start()


class AnimatedLineEdit(QLineEdit):
    def focusInEvent(self, event) -> None:
        self.setProperty("focusRing", True)
        _refresh_style(self)
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.setProperty("focusRing", False)
        _refresh_style(self)


class AnimatedComboBox(QComboBox):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        popup_view = QListView()
        popup_view.setObjectName("DropdownView")
        popup_view.setSpacing(6)
        popup_view.setFrameShape(QFrame.Shape.NoFrame)
        popup_view.setViewportMargins(10, 10, 10, 10)
        popup_view.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        popup_view.setAutoFillBackground(True)
        popup_view.viewport().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        popup_view.viewport().setAutoFillBackground(True)
        popup_palette = popup_view.palette()
        popup_palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        popup_palette.setColor(QPalette.ColorRole.Window, QColor("#ffffff"))
        popup_palette.setColor(QPalette.ColorRole.Text, QColor("#122131"))
        popup_palette.setColor(QPalette.ColorRole.Highlight, QColor("#e4eef8"))
        popup_palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#122131"))
        popup_view.setPalette(popup_palette)
        popup_view.viewport().setPalette(popup_palette)
        popup_shadow = QGraphicsDropShadowEffect(popup_view)
        popup_shadow.setBlurRadius(26)
        popup_shadow.setOffset(0, 8)
        popup_shadow.setColor(QColor(17, 35, 54, 38))
        popup_view.setGraphicsEffect(popup_shadow)
        popup_view.setStyleSheet(
            """
            QListView#DropdownView {
                background-color: #ffffff;
                color: #122131;
                border: 1px solid rgba(166, 181, 197, 0.58);
                border-radius: 18px;
                padding: 0px;
                outline: none;
            }
            QListView#DropdownView::viewport {
                background: transparent;
                border: none;
                border-radius: 14px;
            }
            QListView#DropdownView::item {
                min-height: 24px;
                padding: 10px 16px;
                margin: 0px 0px 2px 0px;
                border-radius: 12px;
            }
            QListView#DropdownView::item:hover {
                background: transparent;
            }
            QListView#DropdownView::item:selected {
                background: #dbe8f6;
                color: #122131;
            }
            QScrollBar:vertical {
                width: 10px;
                margin: 10px 8px 10px 0px;
                background: transparent;
            }
            QScrollBar::handle:vertical {
                background: rgba(150, 170, 191, 0.75);
                border-radius: 5px;
                min-height: 42px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(150, 170, 191, 0.75);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                height: 0px;
                background: transparent;
            }
            """
        )
        self.setView(popup_view)

    def focusInEvent(self, event) -> None:
        self.setProperty("focusRing", True)
        _refresh_style(self)
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.setProperty("focusRing", False)
        _refresh_style(self)

    def showPopup(self) -> None:
        super().showPopup()
        popup_view = self.view()
        popup_view.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        popup_view.setAutoFillBackground(True)
        popup_view.viewport().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        popup_view.viewport().setAutoFillBackground(True)
        popup = popup_view.window()
        if popup is None:
            return
        popup.setObjectName("ComboPopup")
        polish_popup_window(popup, set_frameless=False)
        popup_palette = popup.palette()
        popup_palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 0))
        popup_palette.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
        popup.setPalette(popup_palette)
        popup.setStyleSheet(
            """
            QWidget#ComboPopup {
                background: transparent;
                border: none;
            }
            """
        )
        model = popup_view.model()
        visible_rows = min(max(self.maxVisibleItems(), 1), model.rowCount() if model is not None else 0)
        if visible_rows > 0:
            row_height = max(popup_view.sizeHintForRow(0), 44)
            spacing = max(popup_view.spacing(), 0)
            margins = popup_view.viewportMargins()
            content_height = (row_height * visible_rows) + (spacing * max(visible_rows - 1, 0))
            desired_height = content_height + margins.top() + margins.bottom() + 4
            popup.resize(popup.width(), max(desired_height, popup.height() - 12))


class AnimatedStackedWidget(QStackedWidget):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._page_animation: QParallelAnimationGroup | None = None
        self._animating = False
        self._transition_overlays: list[QLabel] = []

    def setCurrentIndex(self, index: int) -> None:
        current_index = self.currentIndex()
        if self._animating or current_index < 0 or index == current_index or _reduced_motion_enabled():
            super().setCurrentIndex(index)
            return

        current = self.currentWidget()
        target = self.widget(index)
        if current is None or target is None:
            super().setCurrentIndex(index)
            return

        direction = 1 if index > current_index else -1
        frame = self.rect()
        travel = max(28, min(56, frame.width() // 18))
        current.setGeometry(frame)
        target.setGeometry(frame)
        target.show()

        current_pixmap = current.grab()
        target_pixmap = target.grab()
        target.hide()
        current.raise_()

        current_overlay = QLabel(self)
        current_overlay.setPixmap(current_pixmap)
        current_overlay.setScaledContents(True)
        current_overlay.setGeometry(frame)
        current_overlay.show()
        current_overlay.raise_()

        target_overlay = QLabel(self)
        target_overlay.setPixmap(target_pixmap)
        target_overlay.setScaledContents(True)
        target_overlay.setGeometry(frame.translated(direction * travel, 0))
        target_overlay.show()
        target_overlay.raise_()

        current_opacity = QGraphicsOpacityEffect(current_overlay)
        current_opacity.setOpacity(1.0)
        current_overlay.setGraphicsEffect(current_opacity)

        target_opacity = QGraphicsOpacityEffect(target_overlay)
        target_opacity.setOpacity(0.82)
        target_overlay.setGraphicsEffect(target_opacity)

        self._transition_overlays = [current_overlay, target_overlay]

        group = QParallelAnimationGroup(self)
        for widget, start_rect, end_rect in (
            (current_overlay, QRect(frame), QRect(frame.translated(-direction * travel, 0))),
            (target_overlay, QRect(frame.translated(direction * travel, 0)), QRect(frame)),
        ):
            animation = QPropertyAnimation(widget, b"geometry", self)
            animation.setDuration(_motion_duration(190))
            animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
            animation.setStartValue(start_rect)
            animation.setEndValue(end_rect)
            group.addAnimation(animation)

        for overlay, effect, start_value, end_value in (
            (current_overlay, current_opacity, 1.0, 0.56),
            (target_overlay, target_opacity, 0.82, 1.0),
        ):
            animation = QVariantAnimation(self)
            animation.setDuration(_motion_duration(190))
            animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
            animation.setStartValue(start_value)
            animation.setEndValue(end_value)
            animation.valueChanged.connect(
                lambda value, owner=overlay, opacity_effect=effect: opacity_effect.setOpacity(float(value))
                if owner.graphicsEffect() is opacity_effect
                else None
            )
            group.addAnimation(animation)

        self._page_animation = group
        self._animating = True

        def _finish() -> None:
            super(AnimatedStackedWidget, self).setCurrentIndex(index)
            current.setGeometry(frame)
            target.setGeometry(frame)
            for overlay in self._transition_overlays:
                overlay.hide()
                overlay.deleteLater()
            self._transition_overlays = []
            self._animating = False

        group.finished.connect(_finish)
        group.start()


class CardHoverChrome:
    def __init__(self, widget: QWidget) -> None:
        self.widget = widget

    def set_hovered(self, hovered: bool) -> None:
        del hovered


class _MotionMixin:
    def _init_motion(self) -> None:
        self._press_progress = 0.0
        self._hover_progress = 0.0
        self._motion_scale_range = 0.0
        self._motion_lift = 0.0
        self._motion_press_scale = 0.0
        self._motion_hover_grow_x = 0
        self._motion_hover_grow_y = 0
        self._base_size: QSize | None = None
        self._size_animation = QVariantAnimation(self)
        self._size_animation.setDuration(_motion_duration(140))
        self._size_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._size_animation.valueChanged.connect(self._apply_size_value)
        self._press_animation = QVariantAnimation(self)
        self._press_animation.setDuration(_motion_duration(90))
        self._press_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._press_animation.valueChanged.connect(self._set_press_progress)
        self._hover_animation = QVariantAnimation(self)
        self._hover_animation.setDuration(_motion_duration(150))
        self._hover_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_animation.valueChanged.connect(self._set_hover_progress)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _set_press_progress(self, value) -> None:
        self._press_progress = float(value)
        self.update()

    def _set_hover_progress(self, value) -> None:
        self._hover_progress = float(value)
        self.update()

    def set_motion_scale_range(self, amount: float) -> None:
        self._motion_scale_range = max(0.0, float(amount))

    def set_motion_lift(self, amount: float) -> None:
        self._motion_lift = max(0.0, float(amount))

    def set_motion_press_scale(self, amount: float) -> None:
        self._motion_press_scale = max(0.0, float(amount))

    def set_motion_hover_grow(self, width: int, height: int = 0) -> None:
        self._motion_hover_grow_x = max(0, int(width))
        self._motion_hover_grow_y = max(0, int(height))

    def _ensure_base_size(self) -> QSize:
        current = self.size()
        if current.isEmpty():
            current = self.sizeHint()
        if self._base_size is None or self._base_size.isEmpty() or (self._hover_progress == 0.0 and current != self._base_size):
            self._base_size = current
        return self._base_size

    def _apply_size_value(self, value) -> None:
        if isinstance(value, QSize):
            self.setFixedSize(value)

    def _animate_hover_state(self, hovered: bool) -> None:
        del hovered
        self._hover_animation.stop()
        self._size_animation.stop()
        self._hover_progress = 0.0

    def _animate_press_state(self, pressed: bool) -> None:
        self._press_animation.stop()
        self._press_animation.setStartValue(self._press_progress)
        self._press_animation.setEndValue(1.0 if pressed else 0.0)
        self._press_animation.start()

    def _press_offset(self) -> int:
        return 0

    def _lift_offset(self) -> float:
        return self._motion_lift * self._hover_progress

    def _draw_scale(self) -> float:
        if self._motion_scale_range <= 0.0:
            return max(0.9, 1.0 - (self._motion_press_scale * self._press_progress))
        return max(
            0.9,
            1.0
            + (self._motion_scale_range * self._hover_progress)
            - (self._motion_press_scale * self._press_progress)
            - (min(0.02, self._motion_scale_range * 0.45) * self._press_progress),
        )


class AnimatedButton(QPushButton, _MotionMixin):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._init_motion()

    def mousePressEvent(self, event) -> None:
        if self.property("disablePressMotion") is not True:
            self._animate_press_state(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if self.property("disablePressMotion") is not True:
            self._animate_press_state(False)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._animate_hover_state(False)
        if not self.isDown() and self.property("disablePressMotion") is not True:
            self._animate_press_state(False)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self._animate_hover_state(True)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.state = option.state & ~QStyle.StateFlag.State_HasFocus
        painter = QStylePainter(self)
        scale = self._draw_scale()
        if scale != 1.0:
            center = self.rect().center()
            painter.translate(center)
            painter.scale(scale, scale)
            painter.translate(-center)
        lift = self._lift_offset()
        if lift:
            painter.translate(0, -lift)
        offset = self._press_offset()
        if offset:
            painter.translate(0, offset)
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)


class AnimatedToolButton(QToolButton, _MotionMixin):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._init_motion()

    def mousePressEvent(self, event) -> None:
        if self.property("disablePressMotion") is not True:
            self._animate_press_state(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if self.property("disablePressMotion") is not True:
            self._animate_press_state(False)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._animate_hover_state(False)
        if not self.isDown() and self.property("disablePressMotion") is not True:
            self._animate_press_state(False)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self._animate_hover_state(True)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        option.state = option.state & ~QStyle.StateFlag.State_HasFocus
        painter = QStylePainter(self)
        scale = self._draw_scale()
        if scale != 1.0:
            center = self.rect().center()
            painter.translate(center)
            painter.scale(scale, scale)
            painter.translate(-center)
        lift = self._lift_offset()
        if lift:
            painter.translate(0, -lift)
        offset = self._press_offset()
        if offset:
            painter.translate(0, offset)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, option)
        painter.drawControl(QStyle.ControlElement.CE_ToolButtonLabel, option)


def _mix_color(start: QColor, end: QColor, amount: float) -> QColor:
    return QColor(
        int(start.red() + (end.red() - start.red()) * amount),
        int(start.green() + (end.green() - start.green()) * amount),
        int(start.blue() + (end.blue() - start.blue()) * amount),
        int(start.alpha() + (end.alpha() - start.alpha()) * amount),
    )


class AnimatedToggle(QAbstractButton):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._position = 0.0
        self._animation = QPropertyAnimation(self, b"position", self)
        self._animation.setDuration(_motion_duration(170))
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(46, 28)
        self.toggled.connect(self._animate_checked_state)
        self.set_position(1.0 if self.isChecked() else 0.0)

    def sizeHint(self) -> QSize:
        return QSize(46, 28)

    def _animate_checked_state(self, checked: bool) -> None:
        if _reduced_motion_enabled():
            self.set_position(1.0 if checked else 0.0)
            return
        self._animation.stop()
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def setChecked(self, checked: bool) -> None:
        super().setChecked(checked)
        self.set_position(1.0 if checked else 0.0)

    def get_position(self) -> float:
        return self._position

    def set_position(self, value: float) -> None:
        self._position = max(0.0, min(1.0, float(value)))
        self.update()

    position = Property(float, get_position, set_position)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect().adjusted(1, 1, -1, -1)
        radius = rect.height() / 2
        off_color = QColor("#c7d3df")
        on_color = QColor("#0f2539")
        track_color = _mix_color(off_color, on_color, self._position)
        border_color = _mix_color(QColor("#b1bfcd"), QColor("#0f2539"), self._position)
        painter.setPen(border_color)
        painter.setBrush(track_color)
        painter.drawRoundedRect(rect, radius, radius)

        knob_size = rect.height() - 4
        travel = rect.width() - knob_size - 4
        knob_x = rect.x() + 2 + int(round(travel * self._position))
        knob_rect = QRect(knob_x, rect.y() + 2, knob_size, knob_size)
        painter.setPen(QColor(255, 255, 255, 40))
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(knob_rect)

        if self.hasFocus():
            focus_rect = self.rect().adjusted(0, 0, -1, -1)
            painter.setPen(QColor("#7aa8dc"))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(focus_rect, radius + 1, radius + 1)


class ConcentricRingLoader(QWidget):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        size: int = 60,
        color: QColor | str = "#524656",
        accent_color: QColor | str = "#CF4647",
        stroke_width: float = 2.0,
    ) -> None:
        super().__init__(parent)
        self._phase = 0.0
        self._cycle_ms = 500.0
        self._stroke_width = max(1.0, float(stroke_width))
        self._color = QColor(color)
        self._accent_color = QColor(accent_color)
        self.setObjectName("ConcentricRingLoader")
        self.setFixedSize(size, size)

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def sizeHint(self) -> QSize:
        return self.size()

    def setColor(self, color: QColor | str) -> None:
        self._color = QColor(color)
        self.update()

    def setAccentColor(self, color: QColor | str) -> None:
        self._accent_color = QColor(color)
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + (float(self._timer.interval()) / self._cycle_ms)) % 1.0
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        side = float(min(self.width(), self.height()))
        width = side * 0.5
        height = side
        center_x = self.width() / 2.0
        center_y = self.height() / 2.0
        phase = self._phase

        if phase <= 0.05:
            rotation_progress = 0.0
        elif phase >= 0.95:
            rotation_progress = 1.0
        else:
            rotation_progress = (phase - 0.05) / 0.9
        angle = -60.0 * max(0.0, min(1.0, rotation_progress))

        if phase <= 0.02:
            bounce = 0.0
        elif phase >= 0.98:
            bounce = 1.0
        else:
            bounce = (phase - 0.02) / 0.96
        dot_lift = side * 0.002 * max(0.0, min(1.0, bounce))

        diamond_size = width * 0.9
        diamond_center_y = center_y + (height * 0.18)
        dot_radius = max(3.0, width * 0.15)
        dot_center_y = center_y - (height * 0.3) - dot_lift

        painter.save()
        painter.translate(center_x, diamond_center_y)
        painter.rotate(angle)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        half = diamond_size / 2.0
        diamond = QPolygonF(
            [
                QPointF(0.0, -half),
                QPointF(half, 0.0),
                QPointF(0.0, half),
                QPointF(-half, 0.0),
            ]
        )
        painter.drawPolygon(diamond)
        painter.restore()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._accent_color)
        painter.drawEllipse(
            QRect(
                int(round(center_x - dot_radius)),
                int(round(dot_center_y - dot_radius)),
                int(round(dot_radius * 2.0)),
                int(round(dot_radius * 2.0)),
            )
        )
