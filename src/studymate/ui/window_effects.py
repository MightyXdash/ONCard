from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QColor, QPalette, QRegion


DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWA_NCRENDERING_POLICY = 2
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2
DWMWCP_ROUNDSMALL = 3
DWMWA_COLOR_NONE = 0xFFFFFFFE
DWMNCRP_ENABLED = 2


class _MARGINS(ctypes.Structure):
    _fields_ = [
        ("cxLeftWidth", ctypes.c_int),
        ("cxRightWidth", ctypes.c_int),
        ("cyTopHeight", ctypes.c_int),
        ("cyBottomHeight", ctypes.c_int),
    ]


try:
    _dwmapi = ctypes.WinDLL("dwmapi")
except OSError:  # pragma: no cover
    _dwmapi = None


def _apply_popup_shell_chrome(widget, *, remove_border: bool = True) -> None:
    widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
    widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
    widget.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
    widget.setAutoFillBackground(False)
    if widget.width() > 0 and widget.height() > 0:
        widget.setMask(QRegion(widget.rect()))
    if remove_border:
        polish_windows_window(widget, rounded=False, remove_border=True, native_shadow=False)


def _schedule_popup_shell_chrome(widget, *, remove_border: bool = True) -> None:
    def _refresh() -> None:
        try:
            _apply_popup_shell_chrome(widget, remove_border=remove_border)
        except RuntimeError:
            return

    QTimer.singleShot(0, _refresh)


class _PopupChromeFilter(QObject):
    def __init__(self, widget, *, remove_border: bool) -> None:
        super().__init__(widget)
        self._widget = widget
        self._remove_border = remove_border

    def eventFilter(self, watched, event) -> bool:
        if watched is self._widget and event.type() in {
            QEvent.Type.Show,
            QEvent.Type.Resize,
            QEvent.Type.WinIdChange,
            QEvent.Type.Polish,
        }:
            _schedule_popup_shell_chrome(self._widget, remove_border=self._remove_border)
        return False


def polish_windows_window(
    widget,
    *,
    rounded: bool = True,
    small_corners: bool = False,
    remove_border: bool = True,
    native_shadow: bool = False,
) -> None:
    if sys.platform != "win32" or _dwmapi is None:
        return
    try:
        hwnd = wintypes.HWND(int(widget.winId()))
    except Exception:
        return

    if not rounded:
        corner_preference = DWMWCP_DONOTROUND
    else:
        corner_preference = DWMWCP_ROUNDSMALL if small_corners else DWMWCP_ROUND

    corner_value = ctypes.c_int(corner_preference)
    try:
        _dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(corner_value),
            ctypes.sizeof(corner_value),
        )
    except Exception:
        pass

    if native_shadow:
        nc_rendering_policy = ctypes.c_int(DWMNCRP_ENABLED)
        try:
            _dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_NCRENDERING_POLICY,
                ctypes.byref(nc_rendering_policy),
                ctypes.sizeof(nc_rendering_policy),
            )
        except Exception:
            pass
        margins = _MARGINS(1, 1, 1, 1)
        try:
            _dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
        except Exception:
            pass

    if not remove_border:
        return

    border_value = ctypes.c_uint(DWMWA_COLOR_NONE)
    try:
        _dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_BORDER_COLOR,
            ctypes.byref(border_value),
            ctypes.sizeof(border_value),
        )
    except Exception:
        return


def polish_popup_window(
    widget,
    *,
    set_frameless: bool = True,
    no_native_shadow: bool = True,
    remove_border: bool = True,
) -> None:
    if set_frameless:
        widget.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    if no_native_shadow:
        widget.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)

    widget.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
    widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
    widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
    widget.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
    widget.setAutoFillBackground(False)

    palette = widget.palette()
    transparent = QColor(0, 0, 0, 0)
    for role in (
        QPalette.ColorRole.Window,
        QPalette.ColorRole.Base,
        QPalette.ColorRole.AlternateBase,
        QPalette.ColorRole.Button,
    ):
        palette.setColor(role, transparent)
    widget.setPalette(palette)
    if getattr(widget, "_oncard_popup_chrome_filter", None) is None:
        popup_filter = _PopupChromeFilter(widget, remove_border=remove_border)
        widget._oncard_popup_chrome_filter = popup_filter
        widget.installEventFilter(popup_filter)
    _apply_popup_shell_chrome(widget, remove_border=remove_border)
    _schedule_popup_shell_chrome(widget, remove_border=remove_border)
    widget.update()

    if remove_border:
        polish_windows_window(widget, rounded=False, remove_border=True, native_shadow=False)
