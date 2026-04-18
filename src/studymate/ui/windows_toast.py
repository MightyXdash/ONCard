from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
from xml.sax.saxutils import escape


APP_USER_MODEL_ID = "QyrouLabs.ONCard"
_APP_SHORTCUT_NAME = "ONCard.lnk"

_CLSID_SHELL_LINK = "{00021401-0000-0000-C000-000000000046}"
_IID_ISHELL_LINKW = "{000214F9-0000-0000-C000-000000000046}"
_IID_IPERSIST_FILE = "{0000010b-0000-0000-C000-000000000046}"
_IID_IPROPERTY_STORE = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
_PKEY_APP_USER_MODEL_ID_FMTID = "{9F4C2855-9F79-4B39-A8D0-4E1C3E6CBB03}"
_PKEY_APP_USER_MODEL_ID_PID = 5
_CLSCTX_INPROC_SERVER = 0x1
_STGM_READWRITE = 0x2
_VT_LPWSTR = 31


def show_windows_toast(title: str, message: str, *, silent: bool = False) -> bool:
    if os.name != "nt":
        return False

    ensure_windows_toast_shortcut()
    toast_xml = _toast_xml(title, message, silent=silent)
    command = _toast_powershell_command(toast_xml)
    encoded_command = base64.b64encode(command.encode("utf-16le")).decode("ascii")
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0

    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded_command,
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=startupinfo,
            timeout=4,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def set_windows_app_user_model_id() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)  # type: ignore[attr-defined]
    except Exception:
        return
    ensure_windows_toast_shortcut()


def ensure_windows_toast_shortcut() -> bool:
    if os.name != "nt":
        return False
    shortcut_path = _start_menu_shortcut_path()
    if shortcut_path is None:
        return False
    target_path = _app_target_path()
    if not target_path:
        return False
    try:
        shortcut_path.parent.mkdir(parents=True, exist_ok=True)
        _create_app_user_model_shortcut(shortcut_path, target_path)
    except Exception:
        return False
    return shortcut_path.exists()


def _toast_xml(title: str, message: str, *, silent: bool) -> str:
    audio = '<audio silent="true" />' if silent else ""
    return (
        '<toast duration="short">'
        "<visual>"
        '<binding template="ToastGeneric">'
        f"<text>{escape(str(title or 'ONCard'))}</text>"
        f"<text>{escape(str(message or ''))}</text>"
        "</binding>"
        "</visual>"
        f"{audio}"
        "</toast>"
    )


def _toast_powershell_command(toast_xml: str) -> str:
    return f"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml(@'
{toast_xml}
'@)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{APP_USER_MODEL_ID}')
$notifier.Show($toast)
"""


def _start_menu_shortcut_path() -> Path | None:
    appdata = os.getenv("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "ONCard" / _APP_SHORTCUT_NAME


def _app_target_path() -> str:
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve())
    return str(Path(sys.executable).resolve())


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", wintypes.DWORD)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [
        ("vt", wintypes.USHORT),
        ("wReserved1", wintypes.USHORT),
        ("wReserved2", wintypes.USHORT),
        ("wReserved3", wintypes.USHORT),
        ("pwszVal", wintypes.LPWSTR),
    ]


def _guid(value: str) -> _GUID:
    guid = _GUID()
    ctypes.oledll.ole32.CLSIDFromString(wintypes.LPCWSTR(value), ctypes.byref(guid))
    return guid


def _create_app_user_model_shortcut(shortcut_path: Path, target_path: str) -> None:
    ole32 = ctypes.oledll.ole32
    ole32.CoInitialize(None)
    shell_link = ctypes.c_void_p()
    try:
        ole32.CoCreateInstance(
            ctypes.byref(_guid(_CLSID_SHELL_LINK)),
            None,
            _CLSCTX_INPROC_SERVER,
            ctypes.byref(_guid(_IID_ISHELL_LINKW)),
            ctypes.byref(shell_link),
        )
        if not shell_link.value:
            return
        _shell_link_set_path(shell_link, target_path)
        _shell_link_set_arguments(shell_link, "")

        property_store = _com_query_interface(shell_link, _IID_IPROPERTY_STORE)
        if property_store.value:
            prop_key = _PROPERTYKEY(_guid(_PKEY_APP_USER_MODEL_ID_FMTID), _PKEY_APP_USER_MODEL_ID_PID)
            prop_value = _PROPVARIANT(_VT_LPWSTR, 0, 0, 0, APP_USER_MODEL_ID)
            _property_store_set_value(property_store, prop_key, prop_value)
            _property_store_commit(property_store)
            _com_release(property_store)

        persist_file = _com_query_interface(shell_link, _IID_IPERSIST_FILE)
        if persist_file.value:
            _persist_file_save(persist_file, str(shortcut_path), True)
            _com_release(persist_file)
    finally:
        if shell_link.value:
            _com_release(shell_link)
        ole32.CoUninitialize()


def _com_method(obj: ctypes.c_void_p, index: int, restype, *argtypes):
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])


def _raise_failed(result: int) -> None:
    if result < 0:
        raise OSError(result)


def _com_query_interface(obj: ctypes.c_void_p, iid: str) -> ctypes.c_void_p:
    target = ctypes.c_void_p()
    method = _com_method(obj, 0, ctypes.HRESULT, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))
    _raise_failed(method(obj, ctypes.byref(_guid(iid)), ctypes.byref(target)))
    return target


def _shell_link_set_path(obj: ctypes.c_void_p, path: str) -> None:
    method = _com_method(obj, 20, ctypes.HRESULT, wintypes.LPCWSTR)
    _raise_failed(method(obj, path))


def _shell_link_set_arguments(obj: ctypes.c_void_p, args: str) -> None:
    method = _com_method(obj, 11, ctypes.HRESULT, wintypes.LPCWSTR)
    _raise_failed(method(obj, args))


def _property_store_set_value(obj: ctypes.c_void_p, key: _PROPERTYKEY, value: _PROPVARIANT) -> None:
    method = _com_method(obj, 6, ctypes.HRESULT, ctypes.POINTER(_PROPERTYKEY), ctypes.POINTER(_PROPVARIANT))
    _raise_failed(method(obj, ctypes.byref(key), ctypes.byref(value)))


def _property_store_commit(obj: ctypes.c_void_p) -> None:
    method = _com_method(obj, 7, ctypes.HRESULT)
    _raise_failed(method(obj))


def _persist_file_save(obj: ctypes.c_void_p, path: str, remember: bool) -> None:
    method = _com_method(obj, 6, ctypes.HRESULT, wintypes.LPCWSTR, wintypes.BOOL)
    _raise_failed(method(obj, path, bool(remember)))


def _com_release(obj: ctypes.c_void_p) -> None:
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    release = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(vtbl[2])
    release(obj)
