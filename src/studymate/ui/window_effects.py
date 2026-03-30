from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2
DWMWCP_ROUNDSMALL = 3
DWMWA_COLOR_NONE = 0xFFFFFFFE


try:
    _dwmapi = ctypes.WinDLL("dwmapi")
except OSError:  # pragma: no cover
    _dwmapi = None


def polish_windows_window(
    widget,
    *,
    rounded: bool = True,
    small_corners: bool = False,
    remove_border: bool = True,
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
        return

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
