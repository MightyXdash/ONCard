from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, QRect, Qt, QVariantAnimation, QSize
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
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


def _refresh_style(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def polish_surface(widget: QWidget, *, sidebar: bool = False) -> None:
    del sidebar
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)


def fade_widget_visibility(widget: QWidget, visible: bool, duration: int = 170) -> None:
    animation = getattr(widget, "_height_animation", None)
    if animation is None:
        animation = QPropertyAnimation(widget, b"maximumHeight", widget)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _finish() -> None:
            target_visible = bool(getattr(widget, "_height_target_visible", widget.isVisible()))
            widget.setMaximumHeight(16777215)
            if not target_visible:
                widget.setVisible(False)

        animation.finished.connect(_finish)
        widget._height_animation = animation  # type: ignore[attr-defined]

    animation.stop()
    animation.setDuration(duration)
    widget._height_target_visible = visible  # type: ignore[attr-defined]

    if visible:
        target_height = max(int(widget.sizeHint().height()), int(widget.height()), 1)
        widget._expanded_height = target_height  # type: ignore[attr-defined]
        widget.setVisible(True)
        widget.setMaximumHeight(max(0, min(widget.maximumHeight(), target_height)))
        animation.setStartValue(0 if widget.height() <= 0 else widget.height())
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
        popup_view.setSpacing(2)
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
        popup = self.view().window()
        if popup is None:
            return
        popup.setObjectName("ComboPopup")
        popup.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        popup.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        popup.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        popup.show()


class AnimatedStackedWidget(QStackedWidget):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._page_animation: QParallelAnimationGroup | None = None
        self._animating = False

    def setCurrentIndex(self, index: int) -> None:
        current_index = self.currentIndex()
        if self._animating or current_index < 0 or index == current_index:
            super().setCurrentIndex(index)
            return

        current = self.currentWidget()
        target = self.widget(index)
        if current is None or target is None:
            super().setCurrentIndex(index)
            return

        direction = 1 if index > current_index else -1
        frame = self.rect()
        current_rect = QRect(frame)
        target_rect = QRect(frame.translated(direction * frame.width(), 0))
        exit_rect = QRect(frame.translated(-direction * frame.width(), 0))

        target.setGeometry(target_rect)
        target.show()
        target.raise_()

        group = QParallelAnimationGroup(self)
        for widget, start_rect, end_rect in (
            (current, current_rect, exit_rect),
            (target, target_rect, current_rect),
        ):
            animation = QPropertyAnimation(widget, b"geometry", self)
            animation.setDuration(180)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            animation.setStartValue(start_rect)
            animation.setEndValue(end_rect)
            group.addAnimation(animation)

        self._page_animation = group
        self._animating = True

        def _finish() -> None:
            super(AnimatedStackedWidget, self).setCurrentIndex(index)
            current.setGeometry(frame)
            target.setGeometry(frame)
            self._animating = False

        group.finished.connect(_finish)
        group.start()


class CardHoverChrome:
    def __init__(self, widget: QWidget) -> None:
        self.widget = widget

    def set_hovered(self, hovered: bool) -> None:
        self.widget.setProperty("hovered", hovered)
        _refresh_style(self.widget)


class _MotionMixin:
    def _init_motion(self) -> None:
        self._press_progress = 0.0
        self._press_animation = QVariantAnimation(self)
        self._press_animation.setDuration(150)
        self._press_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._press_animation.valueChanged.connect(self._set_press_progress)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _set_press_progress(self, value) -> None:
        self._press_progress = float(value)
        self.update()

    def _animate_press_state(self, pressed: bool) -> None:
        self._press_animation.stop()
        self._press_animation.setStartValue(self._press_progress)
        self._press_animation.setEndValue(1.0 if pressed else 0.0)
        self._press_animation.start()

    def _press_offset(self) -> int:
        return int(round(2 * self._press_progress))


class AnimatedButton(QPushButton, _MotionMixin):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._init_motion()

    def mousePressEvent(self, event) -> None:
        self._animate_press_state(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        self._animate_press_state(False)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.setProperty("hovered", False)
        _refresh_style(self)
        if not self.isDown():
            self._animate_press_state(False)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.setProperty("hovered", True)
        _refresh_style(self)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.state = option.state & ~QStyle.StateFlag.State_HasFocus
        offset = self._press_offset()
        if offset:
            option.rect = self.rect().adjusted(0, offset, 0, -offset)
        painter = QStylePainter(self)
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)


class AnimatedToolButton(QToolButton, _MotionMixin):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._init_motion()

    def mousePressEvent(self, event) -> None:
        self._animate_press_state(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        self._animate_press_state(False)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.setProperty("hovered", False)
        _refresh_style(self)
        if not self.isDown():
            self._animate_press_state(False)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.setProperty("hovered", True)
        _refresh_style(self)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        option.state = option.state & ~QStyle.StateFlag.State_HasFocus
        offset = self._press_offset()
        if offset:
            option.rect = self.rect().adjusted(0, offset, 0, -offset)
        painter = QStylePainter(self)
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
        self._animation.setDuration(170)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(46, 28)
        self.toggled.connect(self._animate_checked_state)

    def sizeHint(self) -> QSize:
        return QSize(46, 28)

    def _animate_checked_state(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

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
