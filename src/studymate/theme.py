from __future__ import annotations

from pathlib import Path
from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


ThemeMode = Literal["light", "dark", "system"]
ResolvedTheme = Literal["light", "dark"]

VALID_THEME_MODES: tuple[str, ...] = ("system", "light", "dark")

LIGHT_TOKENS = {
    "bg": "#e8eef4",
    "surface": "rgba(255, 255, 255, 0.96)",
    "surface_solid": "#ffffff",
    "surface_alt": "#f8fbfd",
    "elevated": "rgba(255, 255, 255, 0.98)",
    "text": "#16202b",
    "text_strong": "#111d2a",
    "muted": "#697888",
    "border": "rgba(167, 182, 199, 0.42)",
    "primary": "#0f2539",
    "primary_hover": "#13314b",
    "hover": "#f8fbfe",
    "pressed": "#e6eef7",
    "selection": "#d6e4f1",
    "success": "#58b66f",
    "warning": "#d7a45c",
    "danger": "#d95c5c",
    "overlay": "rgba(15, 23, 42, 0.44)",
}

DARK_TOKENS = {
    "bg": "#111820",
    "surface": "rgba(26, 35, 46, 0.96)",
    "surface_solid": "#1a232e",
    "surface_alt": "#202b37",
    "elevated": "rgba(31, 42, 54, 0.98)",
    "text": "#e7edf4",
    "text_strong": "#f7fafc",
    "muted": "#9aa8b7",
    "border": "rgba(122, 142, 164, 0.34)",
    "primary": "#79b7ff",
    "primary_hover": "#9ac8ff",
    "hover": "#273545",
    "pressed": "#33455a",
    "selection": "#2d4f72",
    "success": "#75d28b",
    "warning": "#e6b96e",
    "danger": "#ff8686",
    "overlay": "rgba(0, 0, 0, 0.58)",
}


def normalize_theme_mode(mode: object) -> ThemeMode:
    clean = str(mode or "").strip().lower()
    if clean in VALID_THEME_MODES:
        return clean  # type: ignore[return-value]
    return "light"


def resolve_theme_mode(mode: object = "light", app: QApplication | None = None) -> ResolvedTheme:
    clean = normalize_theme_mode(mode)
    if clean in ("light", "dark"):
        return clean
    app = app or QApplication.instance()
    if app is not None:
        try:
            if app.styleHints().colorScheme() == Qt.ColorScheme.Dark:
                return "dark"
        except AttributeError:
            pass
    return "light"


def theme_tokens(mode: object = "light", app: QApplication | None = None) -> dict[str, str]:
    return DARK_TOKENS if resolve_theme_mode(mode, app) == "dark" else LIGHT_TOKENS


def is_dark_theme(app: QApplication | None = None) -> bool:
    app = app or QApplication.instance()
    if app is None:
        return False
    return str(app.property("oncardResolvedTheme") or "light") == "dark"


def apply_app_theme(app: QApplication, mode: object = "light") -> ResolvedTheme:
    saved_mode = normalize_theme_mode(mode)
    resolved = resolve_theme_mode(saved_mode, app)
    app.setProperty("oncardTheme", saved_mode)
    app.setProperty("oncardResolvedTheme", resolved)
    _apply_palette(app, resolved)
    app.setStyleSheet(app_stylesheet(resolved))
    return resolved


def _apply_palette(app: QApplication, resolved: ResolvedTheme) -> None:
    tokens = DARK_TOKENS if resolved == "dark" else LIGHT_TOKENS
    palette = QPalette()
    bg = QColor(tokens["bg"])
    surface = QColor(tokens["surface_solid"])
    surface_alt = QColor(tokens["surface_alt"])
    text = QColor(tokens["text"])
    muted = QColor(tokens["muted"])
    primary = QColor(tokens["primary"])
    disabled = QColor("#687586" if resolved == "dark" else "#a4afbb")
    palette.setColor(QPalette.ColorRole.Window, bg)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, surface)
    palette.setColor(QPalette.ColorRole.AlternateBase, surface_alt)
    palette.setColor(QPalette.ColorRole.ToolTipBase, surface_alt)
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, surface)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, primary)
    palette.setColor(QPalette.ColorRole.Highlight, QColor(tokens["selection"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff" if resolved == "dark" else "#132334"))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, QColor(tokens["surface_alt"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Window, bg)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, muted)
    app.setPalette(palette)


def _asset_url(relative_path: str) -> str:
    candidates = [
        Path(__file__).resolve().parents[2] / relative_path,
        Path.cwd() / relative_path,
    ]
    for path in candidates:
        if path.exists():
            return path.as_posix()
    return relative_path.replace("\\", "/")


def app_stylesheet(mode: object = "light") -> str:
    check_icon = _asset_url("assets/icons/common/check_white_small.svg")
    base = """
    * {
        font-family: "Nunito Sans", "Segoe UI Variable Text", "Segoe UI", "Noto Sans", sans-serif;
        color: #16202b;
        font-size: 13px;
        background: transparent;
    }
    QMainWindow, QDialog {
        background-color: #e8eef4;
    }
    QMainWindow#OnCardMainWindow {
        background: #e8eef4;
    }
    QWidget {
        background-color: #e8eef4;
    }
    QWidget#AppShell {
        background: transparent;
        border: none;
        border-radius: 0px;
    }
    QWidget#AppShell[windowMaximized="true"] {
        border-radius: 0px;
    }
    QLabel {
        background: transparent;
    }
    QStatusBar {
        background: rgba(244, 247, 251, 0.96);
        border-top: 1px solid rgba(163, 176, 194, 0.35);
        color: #435160;
    }
    QStatusBar::item {
        border: none;
    }
    QFrame#Surface {
        background-color: rgba(255, 255, 255, 0.96);
        border: 1px solid rgba(167, 182, 199, 0.42);
        border-radius: 26px;
    }
    QDialog#StatsDialog {
        background: transparent;
        border: none;
    }
    QDialog#StatsDialog QFrame#Surface[statsMain="true"] {
        background-color: rgba(255, 255, 255, 0.98);
        border: 1px solid rgba(167, 182, 199, 0.36);
        border-radius: 40px;
    }
    QPushButton#StatsCloseButton {
        background: transparent;
        border: none;
        border-radius: 12px;
        padding: 0px;
    }
    QPushButton#StatsCloseButton:hover {
        background-color: rgba(15, 37, 57, 0.08);
        border: none;
    }
    QPushButton#StatsCloseButton:pressed {
        background-color: rgba(15, 37, 57, 0.15);
        border: none;
    }
    QFrame#SearchSuggestionDropdown {
        background-color: rgba(255, 255, 255, 0.98);
        border: 1px solid rgba(160, 176, 194, 0.48);
        border-radius: 18px;
    }
    QFrame#CardsSearchActions {
        background-color: rgba(255, 255, 255, 0.96);
        border: 1px solid rgba(167, 182, 199, 0.42);
        border-radius: 19px;
    }
    QFrame#SearchInputShell {
        background-color: rgba(255, 255, 255, 0.98);
        border: 1px solid rgba(167, 182, 199, 0.42);
        border-radius: 20px;
    }
    QFrame#SearchInputShell[focusRing="true"] {
        border: 1px solid #7aa8dc;
        background-color: #fcfeff;
    }
    QFrame#SidebarSurface {
        background-color: rgba(247, 250, 252, 0.96);
        border: 1px solid rgba(167, 182, 199, 0.38);
        border-radius: 28px;
    }
    QFrame#RecommendationBlock {
        background-color: rgba(245, 249, 252, 0.98);
        border: 1px solid rgba(172, 188, 204, 0.34);
        border-radius: 24px;
    }
    QWidget#CardsCanvas {
        background-color: transparent;
    }
    QWidget#CardEmptyState {
        background-color: transparent;
    }
    QLabel#RecommendationTitle {
        font-family: "Nunito Sans", "Segoe UI Variable Display", "Segoe UI", sans-serif;
        font-size: 19px;
        font-weight: 700;
        color: #12202e;
    }
    QLabel#RecommendationMeta {
        font-size: 12px;
        color: #697888;
    }
    QLabel#PageTitle {
        font-family: "Nunito Sans", "Segoe UI Variable Display", "Segoe UI", sans-serif;
        font-size: 30px;
        font-weight: 800;
        color: #111d2a;
    }
    QLabel#SectionTitle {
        font-family: "Nunito Sans", "Segoe UI Variable Display", "Segoe UI", sans-serif;
        font-size: 17px;
        font-weight: 700;
        color: #1a2836;
    }
    QLabel#UpdateSubtitle {
        font-family: "Nunito Sans", "Segoe UI Variable Display", "Segoe UI", sans-serif;
        font-size: 18px;
        font-weight: 700;
        color: #465b70;
    }
    QLabel#SectionText {
        font-size: 15px;
        line-height: 1.55;
        color: #4e6072;
    }
    QLabel#SmallMeta {
        font-size: 13px;
        color: #7a8a99;
    }
    QLabel#TierBadge {
        background-color: #eff5fb;
        color: #1b2e42;
        border: 1px solid rgba(159, 182, 204, 0.55);
        border-radius: 18px;
        padding: 8px 14px;
        font-weight: 700;
    }
    QLabel#FTCBetaBadge {
        background-color: #0f2539;
        color: #ffffff;
        border: 1px solid #0f2539;
        border-radius: 12px;
        padding: 5px 11px;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: 0.08em;
    }
    QLabel#QueueStatusDotPending {
        background-color: #8c8c8c;
        min-width: 12px;
        max-width: 12px;
        min-height: 12px;
        max-height: 12px;
        border-radius: 6px;
    }
    QLabel#QueueStatusDotDone {
        background-color: #0f2539;
        min-width: 12px;
        max-width: 12px;
        min-height: 12px;
        max-height: 12px;
        border-radius: 6px;
    }
    QPushButton {
        background-color: rgba(255, 255, 255, 0.94);
        border: 1px solid rgba(166, 182, 198, 0.45);
        border-radius: 18px;
        padding: 11px 18px;
        font-size: 14px;
        font-weight: 700;
        outline: none;
    }
    QPushButton:hover {
        background-color: #f8fbfe;
        border-color: rgba(125, 162, 196, 0.78);
    }
    QPushButton:pressed {
        background-color: #e6eef7;
    }
    QPushButton:disabled {
        background-color: #f2f4f7;
        color: #a4afbb;
        border-color: #dfe5eb;
    }
    QPushButton#PrimaryButton {
        background-color: #0f2539;
        color: #ffffff;
        border: 1px solid #0f2539;
    }
    QPushButton#PrimaryButton:hover {
        background-color: #13314b;
        border-color: #13314b;
    }
    QPushButton#WizardActionButton {
        background-color: #3f739b;
        color: #ffffff;
        border: 1px solid #3f739b;
        border-radius: 18px;
    }
    QPushButton#WizardActionButton:hover {
        background-color: #0f2539;
        border-color: #0f2539;
    }
    QPushButton#DangerlessButton {
        background-color: #f4f6f8;
        border-color: #d9e0e7;
    }
    QPushButton#CompactGhostButton {
        background-color: rgba(255, 255, 255, 0.96);
        border: 1px solid rgba(170, 184, 198, 0.4);
        border-radius: 12px;
        padding: 6px 10px;
        font-size: 11px;
        font-weight: 700;
        min-width: 0px;
    }
    QPushButton#CompactGhostButton:hover {
        background-color: #f7fafc;
        border-color: rgba(130, 166, 197, 0.75);
    }
    QToolButton#CompactGhostButton {
        background-color: rgba(255, 255, 255, 0.96);
        border: 1px solid rgba(170, 184, 198, 0.4);
        border-radius: 12px;
        padding: 6px 10px;
        font-size: 11px;
        font-weight: 700;
        outline: none;
    }
    QToolButton#CompactGhostButton:hover {
        background-color: #f7fafc;
        border-color: rgba(130, 166, 197, 0.75);
    }
    QPushButton#TopNavButton {
        min-width: 78px;
        padding: 6px 10px;
        border-radius: 10px;
        background-color: rgba(255, 255, 255, 0.86);
        color: #193043;
        border-color: rgba(166, 180, 194, 0.38);
        font-size: 13px;
    }
    QToolTip {
        color: #f1f4f8;
        background-color: rgba(18, 24, 32, 0.94);
        border: 1px solid rgba(0, 0, 0, 0.35);
        border-radius: 8px;
        padding: 6px 8px;
        font-size: 12px;
    }
    QPushButton#TopNavButton:checked {
        background-color: #0f2539;
        color: #ffffff;
        border-color: #0f2539;
    }
    QPushButton#TopNavButton:hover:!checked {
        background-color: #f8fbfe;
        border-color: rgba(125, 162, 196, 0.78);
    }
    QFrame#WindowTitleBar {
        background-color: #e8eef4;
        border: none;
        border-radius: 0px;
    }
    QFrame#WindowTitleBar[windowMaximized="true"] {
        border-radius: 0px;
    }
    QWidget#WindowLeftCluster,
    QWidget#WindowModeCluster,
    QWidget#WindowRightCluster,
    QWidget#AppIconMenu {
        background: transparent;
        border: none;
    }
    QLabel#WindowControlSeparator {
        background: transparent;
        color: rgba(98, 115, 132, 0.72);
        font-size: 16px;
        font-weight: 700;
        padding: 0px 8px 1px 8px;
    }
    QPushButton#SettingsNavButton,
    QPushButton#WindowIconButton,
    QPushButton#AppIconButton,
    QPushButton#WindowControlButton,
    QPushButton#WindowControlCloseButton {
        min-width: 0px;
        padding: 0px;
        border: none;
        border-radius: 16px;
        background: transparent;
    }
    QPushButton#SettingsNavButton:hover,
    QPushButton#WindowIconButton:hover,
    QPushButton#AppIconButton:hover {
        background: transparent;
        border: none;
    }
    QPushButton#SettingsNavButton:pressed,
    QPushButton#WindowIconButton:pressed,
    QPushButton#AppIconButton:pressed {
        background: transparent;
        border: none;
    }
    QPushButton#WindowControlButton:hover,
    QPushButton#WindowControlCloseButton:hover {
        background: transparent;
        border: none;
    }
    QPushButton#WindowControlButton:pressed,
    QPushButton#WindowControlCloseButton:pressed {
        background: transparent;
        border: none;
    }
    QFrame#AppIconMenuSurface {
        background-color: rgba(255, 255, 255, 0.98);
        border: 1px solid rgba(166, 181, 197, 0.3);
        border-radius: 18px;
    }
    QFrame#UserProfileMenuSurface {
        background-color: rgba(255, 255, 255, 0.98);
        border: 1px solid rgba(166, 181, 197, 0.3);
        border-radius: 18px;
    }
    QFrame#NotificationsMenuSurface {
        background-color: rgba(255, 255, 255, 0.98);
        border: 1px solid rgba(166, 181, 197, 0.3);
        border-radius: 18px;
    }
    QPushButton#AppIconMenuButton {
        text-align: left;
        background: transparent;
        border: none;
        border-radius: 12px;
        padding: 8px 12px;
        color: #172330;
        font-size: 13px;
        font-weight: 800;
    }
    QPushButton#AppIconMenuButton:hover {
        background-color: #edf4fa;
        border: none;
    }
    QPushButton#AppIconMenuButton:pressed {
        background-color: #e3edf7;
        border: none;
    }
    QPushButton#AppIconAccountButton {
        text-align: left;
        background: transparent;
        border: none;
        border-radius: 12px;
        padding: 8px 12px;
        color: #6f7f90;
        font-size: 13px;
        font-weight: 700;
    }
    QPushButton#AppIconAccountButton:hover {
        background-color: #edf4fa;
        border: none;
        border-radius: 12px;
    }
    QPushButton#AppIconAccountButton:pressed {
        background-color: #e3edf7;
        border: none;
        border-radius: 12px;
    }
    QComboBox#AppIconAccountsCombo {
        background: rgba(255, 255, 255, 0.96);
        border: 1px solid rgba(166, 181, 197, 0.5);
        border-radius: 12px;
        padding: 6px 28px 6px 10px;
        font-size: 12px;
        color: #172330;
        min-height: 24px;
    }
    QComboBox#AppIconAccountsCombo:hover {
        border-color: rgba(122, 168, 220, 0.85);
        background: #fcfeff;
    }
    QComboBox#AppIconAccountsCombo::drop-down {
        width: 28px;
        border: none;
        subcontrol-origin: padding;
        subcontrol-position: top right;
        background: transparent;
    }
    QComboBox#AppIconAccountsCombo::drop-down:hover {
        background: transparent;
    }
    QComboBox#AppIconAccountsCombo::drop-down:on {
        background: transparent;
    }
    QToolButton#CollapseButton {
        background-color: transparent;
        border: none;
        padding: 6px;
        font-size: 18px;
        color: #274155;
        outline: none;
    }
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {
        background-color: rgba(255, 255, 255, 0.96);
        border: 1px solid rgba(166, 181, 197, 0.44);
        border-radius: 18px;
        padding: 12px 18px 12px 14px;
        font-size: 14px;
        selection-background-color: #d6e4f1;
        selection-color: #132334;
        color: #16202b;
        outline: none;
    }
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {
        border: 1px solid #7aa8dc;
        background-color: #fcfeff;
    }
    QLineEdit[focusRing="true"], QComboBox[focusRing="true"] {
        border: 1px solid #7aa8dc;
        background-color: #fcfeff;
    }
    QComboBox {
        padding-right: 34px;
    }
    QSpinBox::up-button, QSpinBox::down-button {
        width: 24px;
        border: none;
        margin-right: 2px;
    }
    QSpinBox::up-arrow, QSpinBox::down-arrow {
        width: 10px;
        height: 10px;
    }
    QTextEdit, QPlainTextEdit {
        line-height: 1.5;
    }
    QTextBrowser {
        background-color: #f8fbfd;
        border: 1px solid rgba(168, 182, 196, 0.38);
        border-radius: 20px;
        padding: 16px;
    }
    QTextEdit#CardTitleDisplay, QTextEdit#CardQuestionDisplay {
        background: transparent;
        border: none;
        padding: 0px;
        margin: 0px;
    }
    QTextEdit#CardTitleDisplay {
        font-family: "Nunito Sans", "Segoe UI Variable Display", "Segoe UI", sans-serif;
        font-size: 15px;
        font-weight: 700;
        color: #3e4955;
    }
    QTextEdit#CardQuestionDisplay {
        font-size: 13px;
        color: #6f7b88;
    }
    QLabel#CardTitleLabel {
        font-family: "Nunito Sans", "Segoe UI Variable Display", "Segoe UI", sans-serif;
        font-size: 15px;
        font-weight: 700;
        color: #3e4955;
    }
    QLabel#CardQuestionLabel {
        font-size: 13px;
        color: #6f7b88;
    }
    QLabel#CardMetaPill {
        background-color: #eff5fb;
        color: #24425b;
        border: 1px solid rgba(154, 177, 201, 0.48);
        border-radius: 13px;
        padding: 4px 10px;
        font-size: 11px;
        font-weight: 700;
    }
    QListWidget, QScrollArea {
        background-color: transparent;
        border: none;
    }
    QScrollArea > QWidget > QWidget {
        background: transparent;
    }
    QDialog QScrollBar:vertical {
        width: 12px;
        margin: 6px 0px 6px 0px;
        background: transparent;
    }
    QDialog QScrollBar::handle:vertical {
        background: rgba(137, 157, 177, 0.55);
        border-radius: 6px;
        min-height: 42px;
    }
    QDialog QScrollBar::handle:vertical:hover {
        background: rgba(103, 130, 157, 0.75);
    }
    QDialog QScrollBar::add-line:vertical, QDialog QScrollBar::sub-line:vertical,
    QDialog QScrollBar::add-page:vertical, QDialog QScrollBar::sub-page:vertical {
        height: 0px;
        background: transparent;
    }
    QListWidget::item {
        border-radius: 14px;
        padding: 10px 12px;
        margin: 4px 0px;
    }
    QListWidget#SearchSuggestionList::item {
        border-radius: 11px;
        padding: 9px 12px;
        margin: 3px 0px;
    }
    QListWidget::item:selected {
        background-color: #e3edf7;
        color: #102131;
    }
    QListWidget::item:hover {
        background-color: #edf4fa;
    }
    QTreeWidget {
        background: transparent;
        border: none;
        outline: none;
        padding: 2px 0px;
        show-decoration-selected: 0;
    }
    QTreeWidget::item {
        min-height: 26px;
        padding: 8px 12px;
        margin: 2px 0px;
        border-radius: 14px;
    }
    QTreeWidget::item:hover {
        background: #edf4fa;
    }
    QTreeWidget::item:selected {
        background: #dfeaf5;
        color: #122131;
    }
    QTreeView::branch {
        background: transparent;
    }
    QTreeView::branch:selected {
        background: transparent;
    }
    QCheckBox {
        background-color: transparent;
        spacing: 12px;
        font-size: 14px;
    }
    QCheckBox::indicator {
        width: 20px;
        height: 20px;
        border-radius: 7px;
        border: 1px solid #c5d0db;
        background: #ffffff;
    }
    QCheckBox::indicator:checked {
        background: #0f2539;
        border: 1px solid #0f2539;
        image: url("__CHECK_ICON__");
    }
    QComboBox::drop-down {
        width: 32px;
        border: none;
        subcontrol-origin: padding;
        subcontrol-position: top right;
        background: transparent;
    }
    QComboBox::drop-down:hover {
        background: transparent;
    }
    QComboBox::drop-down:on {
        background: transparent;
    }
    QComboBox QAbstractItemView {
        background-color: #ffffff;
        border: 1px solid rgba(166, 181, 197, 0.55);
        border-radius: 14px;
        padding: 8px 6px;
        outline: none;
        selection-background-color: #e4eef8;
        selection-color: #122131;
    }
    QWidget#ComboPopup {
        background-color: #ffffff;
        border: 1px solid rgba(166, 181, 197, 0.55);
        border-radius: 14px;
    }
    QComboBox QAbstractItemView::item {
        min-height: 22px;
        padding: 8px 12px;
        margin: 2px 4px;
        border-radius: 10px;
    }
    QComboBox QAbstractItemView::item:hover {
        background: #eff5fa;
    }
    QComboBox QAbstractItemView::item:selected {
        background: #e4eef8;
        color: #122131;
    }
    QSlider {
        background: transparent;
    }
    QSlider::groove:horizontal {
        height: 6px;
        border-radius: 4px;
        background: #d4deea;
    }
    QSlider::sub-page:horizontal {
        border-radius: 4px;
        background: #d4deea;
    }
    QSlider::add-page:horizontal {
        border-radius: 4px;
        background: #d4deea;
    }
    QSlider::handle:horizontal {
        width: 20px;
        height: 20px;
        margin: -7px 0;
        border-radius: 10px;
        background: #0f2539;
    }
    QProgressBar {
        background-color: #e8edf2;
        border: none;
        border-radius: 14px;
        min-height: 16px;
        text-align: center;
        font-weight: 700;
        color: #112030;
    }
    QProgressBar::chunk {
        background-color: #0f2539;
        border-radius: 14px;
    }
    QTabWidget::pane {
        border: none;
        background: transparent;
    }
    QTabWidget#SettingsTabs::pane {
        margin-top: 8px;
    }
    QTabBar::tab {
        background-color: rgba(255, 255, 255, 0.9);
        border: 1px solid rgba(166, 181, 197, 0.44);
        border-radius: 16px;
        padding: 10px 18px;
        margin-right: 8px;
        color: #2b4359;
        font-weight: 700;
        min-width: 90px;
    }
    QTabBar::tab:selected {
        background-color: #0f2539;
        border-color: #0f2539;
        color: #ffffff;
    }
    QTabBar::tab:hover:!selected {
        background-color: #f7fafc;
        border-color: rgba(125, 162, 196, 0.78);
    }
    QFrame#CardTile {
        background-color: rgba(255, 255, 255, 0.98);
        border: 1px solid rgba(168, 182, 197, 0.42);
        border-radius: 24px;
    }
    QFrame#CardTile:hover {
        background-color: #fbfdff;
        border-color: rgba(122, 168, 220, 0.66);
    }
    QFrame#CardTile[hovered="true"] {
        background-color: #fbfdff;
        border-color: rgba(122, 168, 220, 0.66);
    }
    QFrame#CardSearchSkeletonTile {
        background-color: rgba(255, 255, 255, 0.98);
        border: 1px solid rgba(168, 182, 197, 0.38);
        border-radius: 24px;
    }
    QFrame#CardSearchSkeletonBarStrong {
        background-color: rgba(213, 224, 235, 0.98);
        border: none;
        border-radius: 8px;
    }
    QFrame#CardSearchSkeletonBar {
        background-color: rgba(226, 234, 242, 0.98);
        border: none;
        border-radius: 6px;
    }
    QFrame#CardSearchSkeletonPill {
        background-color: rgba(236, 242, 248, 0.98);
        border: none;
        border-radius: 10px;
    }
    QToolButton#CardOptionsButton {
        background-color: rgba(255, 255, 255, 0.98);
        color: #2e465b;
        border: 1px solid rgba(169, 183, 197, 0.44);
        border-radius: 12px;
        padding: 5px 10px;
        font-size: 11px;
        font-weight: 700;
        outline: none;
    }
    QToolButton#CardOptionsButton:hover {
        background-color: #f8fbfe;
        border-color: rgba(125, 162, 196, 0.78);
    }
    QToolButton#CardOptionsButton::menu-indicator {
        image: none;
        width: 0px;
    }
    QFrame#CreateWorkspaceSurface, QFrame#CreateQueueSurface, QFrame#FTCWorkspaceSurface, QFrame#CreateOverlayCard {
        background-color: rgba(255, 254, 253, 0.48);
        border: 1px solid rgba(255, 255, 255, 0.68);
        border-radius: 26px;
    }
    QFrame#CreateIdleSurface {
        background-color: rgba(252, 252, 252, 0.46);
        border: 1px solid rgba(255, 255, 255, 0.62);
        border-radius: 26px;
    }
    QStackedWidget#CreateWorkspaceStack {
        background: transparent;
        border: none;
    }
    QWidget#CreateOverlayHeaderControls, QWidget#FTCHeaderControls {
        background: transparent;
        border: none;
    }
    QFrame#CreateWorkspaceSurface QLabel#PageTitle, QFrame#CreateIdleSurface QLabel#PageTitle, QFrame#CreateQueueSurface QLabel#PageTitle, QFrame#QuestionPromptCard QLabel#PageTitle {
        color: #142434;
    }
    QFrame#CreateWorkspaceSurface QLabel#SectionTitle, QFrame#CreateIdleSurface QLabel#SectionTitle, QFrame#CreateQueueSurface QLabel#SectionTitle, QFrame#QuestionPromptCard QLabel#SectionTitle {
        color: #1b2c3d;
    }
    QFrame#CreateWorkspaceSurface QLabel#SectionText, QFrame#CreateIdleSurface QLabel#SectionText, QFrame#CreateQueueSurface QLabel#SectionText, QFrame#QuestionPromptCard QLabel#SectionText {
        color: #526374;
    }
    QFrame#CreateWorkspaceSurface QLabel#SmallMeta, QFrame#CreateIdleSurface QLabel#SmallMeta, QFrame#CreateQueueSurface QLabel#SmallMeta, QFrame#QuestionPromptCard QLabel#SmallMeta, QWidget#CreateModeMenu QLabel#SmallMeta, QFrame#CreateOverlayCard QLabel#SmallMeta {
        color: #7a8896;
    }
    QFrame#CreateWorkspaceSurface QTextEdit, QFrame#QuestionPromptCard QTextEdit, QFrame#CreateQueueSurface QListWidget, QFrame#CreateQueueSurface QTextBrowser {
        background-color: rgba(255, 254, 253, 0.44);
        color: #1a2836;
        border: 1px solid rgba(255, 255, 255, 0.68);
        border-radius: 18px;
    }
    QFrame#CreateWorkspaceSurface QTextEdit:focus, QFrame#QuestionPromptCard QTextEdit:focus {
        border: 1px solid rgba(164, 169, 173, 0.58);
        background-color: rgba(255, 254, 253, 0.70);
    }
    QFrame#CreateQueueSurface QListWidget::item {
        color: #233649;
        background-color: rgba(255, 254, 253, 0.34);
        border: 1px solid rgba(255, 255, 255, 0.54);
    }
    QFrame#CreateQueueSurface QListWidget::item:selected {
        background-color: rgba(255, 254, 253, 0.70);
        color: #122131;
    }
    QFrame#CreateQueueSurface QListWidget::item:hover {
        background-color: rgba(255, 254, 253, 0.62);
    }
    QFrame#QuestionComposeShell {
        background-color: rgba(255, 254, 253, 0.44);
        border: 1px solid rgba(191, 200, 209, 0.40);
        border-radius: 22px;
    }
    QFrame#QuestionComposeShell QTextEdit {
        background: transparent;
        border: none;
        border-radius: 0px;
        padding: 2px 2px 0px 2px;
    }
    QFrame#QuestionComposeShell QTextEdit:focus {
        background: transparent;
        border: none;
    }
    QWidget#QuestionHeaderControls {
        background: transparent;
        border: none;
    }
    QToolButton#QuestionHeaderActionButton {
        background-color: rgba(255, 254, 253, 0.46);
        border: 1px solid rgba(174, 188, 202, 0.40);
        border-radius: 10px;
        padding: 5px 9px;
        color: #18293a;
    }
    QToolButton#QuestionHeaderActionButton:hover {
        background-color: rgba(255, 254, 253, 0.66);
        border-color: rgba(164, 169, 173, 0.58);
    }
    QToolButton#QuestionHeaderActionButton:disabled {
        background-color: rgba(238, 243, 248, 0.56);
        border-color: rgba(190, 200, 210, 0.3);
        color: #8f9ca8;
    }
    QPushButton#QuestionComposeButton {
        background-color: rgba(255, 254, 253, 0.62);
        color: #18293a;
        border: 1px solid rgba(174, 188, 202, 0.42);
        border-radius: 15px;
        padding: 10px 16px;
    }
    QPushButton#QuestionComposeButton:hover {
        background-color: rgba(255, 254, 253, 0.78);
        border-color: rgba(164, 169, 173, 0.62);
    }
    QPushButton#QuestionComposeButton:pressed {
        background-color: rgba(239, 244, 249, 0.94);
    }
    QWidget#CreateModeMenu, QDialog#QuestionPromptDialog, QDialog#CreateOverlayDialog {
        background: transparent;
        border: none;
    }
    QFrame#CreateModeMenuSurface {
        background-color: rgba(252, 253, 255, 0.86);
        border: 1px solid rgba(194, 202, 210, 0.58);
        border-radius: 18px;
    }
    QFrame#QuestionPromptCard {
        background-color: rgba(252, 253, 255, 0.86);
        border: 1px solid rgba(194, 202, 210, 0.58);
        border-radius: 26px;
    }
    QPushButton#CreateModeMenuButton {
        background-color: rgba(255, 255, 255, 0.68);
        color: #18293a;
        border: 1px solid rgba(194, 202, 210, 0.42);
        border-radius: 12px;
        padding: 12px 16px;
        text-align: left;
    }
    QPushButton#CreateModeMenuButton:hover {
        background-color: rgba(255, 255, 255, 0.92);
        border-color: rgba(139, 169, 199, 0.6);
    }
    QPushButton#CreateModeMenuButton:pressed {
        background-color: rgba(239, 244, 249, 0.94);
    }
    QPushButton#CreateOverlayCloseButton, QPushButton#CreateOverlayUploadButton {
        background: rgba(255, 254, 253, 0.44);
        border: 1px solid rgba(194, 202, 210, 0.38);
        border-radius: 12px;
        padding: 0px;
    }
    QPushButton#CreateOverlayCloseButton:hover, QPushButton#CreateOverlayUploadButton:hover,
    QPushButton#CreateOverlayCloseButton:pressed, QPushButton#CreateOverlayUploadButton:pressed {
        background: rgba(255, 254, 253, 0.44);
        border-color: rgba(194, 202, 210, 0.38);
    }
    QMenu {
        background-color: #ffffff;
        border: 1px solid rgba(166, 181, 197, 0.5);
        border-radius: 14px;
        padding: 6px;
        margin: 0px;
    }
    QMenu::item {
        background-color: transparent;
        color: #16202b;
        border: none;
        border-radius: 10px;
        padding: 8px 14px;
        margin: 1px 0px;
    }
    QMenu::item:selected {
        background-color: #e5eef7;
        color: #122131;
    }
    QMenu::separator {
        height: 1px;
        background: #e3e9ef;
        margin: 6px 8px;
    }
    QMenu#CardOptionsMenu {
        background-color: #ffffff;
        border: 1px solid rgba(166, 181, 197, 0.5);
        border-radius: 14px;
        padding: 8px 6px;
        margin: 0px;
    }
    QMenu#CardOptionsMenu::item {
        background: transparent;
        color: #16202b;
        border: none;
        border-radius: 10px;
        padding: 8px 12px;
        margin: 2px 4px;
    }
    QMenu#CardOptionsMenu::item:selected {
        background: #e5eef7;
        color: #122131;
    }
    QFrame#FTCSharedCanvas {
        background: transparent;
        border: none;
        border-radius: 26px;
    }
    QFrame#FTCInfoSurface {
        background-color: transparent;
        border: none;
        border-radius: 20px;
    }
    QFrame#FTCUploadSurface {
        background: transparent;
        border: none;
        border-radius: 26px;
    }
    QLabel#FTCInlineMetaChip {
        font-family: "Nunito Sans", "Segoe UI Variable Display", "Segoe UI", sans-serif;
        font-size: 11px;
        font-weight: 700;
        color: #18293a;
        background-color: rgba(255, 254, 253, 0.46);
        border: 1px solid rgba(174, 188, 202, 0.40);
        border-radius: 10px;
        padding: 0px 9px;
    }
    QToolButton#FTCMenuButton {
        background-color: rgba(255, 255, 255, 0.84);
        border: 1px solid rgba(255, 255, 255, 0.92);
        border-radius: 14px;
        padding: 0px;
    }
    QToolButton#FTCMenuButton:hover {
        background-color: rgba(255, 255, 255, 0.98);
        border-color: rgba(176, 184, 192, 0.78);
    }
    QToolButton#FTCMenuButton:pressed {
        background-color: rgba(230, 238, 247, 0.94);
    }
    QFrame#FTCUploadTile {
        background-color: rgba(255, 255, 255, 0.76);
        border: 1px dashed rgba(150, 158, 166, 0.66);
        border-radius: 22px;
    }
    QFrame#FTCUploadTile[hovered="true"] {
        background-color: rgba(255, 255, 255, 0.96);
        border-color: rgba(118, 128, 138, 0.86);
    }
    QFrame#FTCUploadTile:disabled {
        background-color: rgba(243, 246, 249, 0.78);
        border-color: rgba(216, 225, 234, 0.8);
    }
    QLabel#FTCUploadTileText {
        color: #6f7880;
        font-size: 12px;
        font-weight: 700;
        background: transparent;
        border: none;
    }
    QFrame#FTCUploadTile QLabel#FTCUploadTileText {
        color: #7a8a99;
    }
    QFrame#FTCUploadTile[hovered="true"] QLabel#FTCUploadTileText {
        color: #5f7081;
    }
    QFrame#FTCUploadTile:disabled QLabel#FTCUploadTileText {
        color: #a5b0bb;
    }
    QLabel#FTCUploadTileIcon {
        background: transparent;
        border: none;
    }
    QScrollArea#FTCHorizontalRail {
        background: transparent;
        border: none;
        border-radius: 22px;
    }
    QScrollArea#FTCHorizontalRail > QWidget > QWidget {
        background: transparent;
        border-radius: 22px;
    }
    QWidget#FTCRailCanvas {
        background: transparent;
        border: none;
    }
    QFrame#FTCFileCard, QFrame#FTCSkeletonCard {
        background-color: rgba(255, 255, 255, 0.78);
        border: 1px solid rgba(255, 255, 255, 0.88);
        border-radius: 22px;
    }
    QLabel#FTCFileCardName {
        font-size: 13px;
        font-weight: 800;
        color: #152535;
    }
    QLabel#FTCFileCardThumb {
        background: transparent;
        border: none;
        padding: 0px;
    }
    QToolButton#FTCFileRemove {
        background-color: rgba(255, 255, 255, 0.9);
        border: 1px solid rgba(175, 189, 204, 0.36);
        border-radius: 11px;
        padding: 0px;
        min-width: 22px;
        max-width: 22px;
        min-height: 22px;
        max-height: 22px;
    }
    QToolButton#FTCFileRemove:hover {
        background-color: rgba(247, 250, 252, 0.98);
        border-color: rgba(129, 165, 197, 0.72);
    }
    QFrame#FTCSkeletonThumb {
        background-color: rgba(227, 235, 243, 0.92);
        border: none;
        border-radius: 16px;
    }
    QFrame#FTCSkeletonBar {
        background-color: rgba(222, 231, 240, 0.92);
        border: none;
        border-radius: 6px;
    }
    QFrame#FTCSkeletonBarSoft {
        background-color: rgba(232, 238, 245, 0.92);
        border: none;
        border-radius: 5px;
    }
    QFrame#FTCControlsPopupCard {
        background: rgba(255, 255, 255, 0.96);
        border: 1px solid rgba(220, 228, 236, 0.88);
        border-radius: 28px;
    }
    QFrame#FTCPopupValueShell {
        background-color: rgba(250, 252, 255, 0.98);
        border: 1px solid rgba(178, 192, 207, 0.34);
        border-radius: 18px;
    }
    QLabel#FTCPopupValueText {
        font-size: 14px;
        font-weight: 700;
        color: #162432;
    }
    QFrame#FTCPopupFieldShell {
        background-color: rgba(252, 254, 255, 0.98);
        border: 1px solid rgba(178, 192, 207, 0.34);
        border-radius: 18px;
    }
    QPushButton#FTCPopupChoiceButton {
        min-height: 44px;
        border-radius: 14px;
        padding: 8px 16px;
        font-size: 15px;
        font-weight: 700;
        color: #405161;
        background-color: rgba(255, 255, 255, 0.98);
        border: 1px solid rgba(180, 194, 208, 0.34);
    }
    QPushButton#FTCPopupChoiceButton:hover {
        background-color: #f7fbff;
        border-color: rgba(125, 162, 196, 0.72);
        color: #1d3145;
    }
    QPushButton#FTCPopupChoiceButton[selected="true"] {
        background-color: #0f2539;
        border-color: #0f2539;
        color: #ffffff;
    }
    QPushButton#FTCPopupStepButton {
        min-width: 44px;
        max-width: 44px;
        min-height: 44px;
        max-height: 44px;
        border-radius: 14px;
        padding: 0px;
        font-size: 18px;
        font-weight: 800;
        color: #22384d;
        background-color: rgba(255, 255, 255, 0.98);
        border: 1px solid rgba(180, 194, 208, 0.34);
    }
    QPushButton#FTCPopupStepButton:hover {
        background-color: #f7fbff;
        border-color: rgba(125, 162, 196, 0.72);
    }
    QLabel#FTCPopupQuestionValue {
        font-family: "Nunito Sans", "Segoe UI Variable Display", "Segoe UI", sans-serif;
        font-size: 22px;
        font-weight: 800;
        color: #132334;
    }
    QToolButton#FTCPopupIconButton {
        background: transparent;
        border: 1px solid transparent;
        border-radius: 12px;
        padding: 0px;
    }
    QToolButton#FTCPopupIconButton:hover {
        background-color: rgba(15, 37, 57, 0.08);
        border-color: rgba(15, 37, 57, 0.08);
    }
    QToolButton#FTCPopupIconButton:pressed {
        background-color: rgba(15, 37, 57, 0.14);
        border-color: rgba(15, 37, 57, 0.14);
    }
    QToolButton#NewAccountConfirmIconButton {
        background: transparent;
        border: 1px solid transparent;
        border-radius: 12px;
        padding: 0px;
    }
    QToolButton#NewAccountConfirmIconButton:hover {
        background-color: rgba(15, 37, 57, 0.08);
        border-color: rgba(15, 37, 57, 0.08);
        border-radius: 12px;
    }
    QToolButton#NewAccountConfirmIconButton:pressed {
        background-color: rgba(15, 37, 57, 0.14);
        border-color: rgba(15, 37, 57, 0.14);
        border-radius: 12px;
    }
    QPushButton#FTCGenerateButton {
        min-width: 108px;
        background-color: rgba(255, 254, 253, 0.46);
        color: #18293a;
        border: 1px solid rgba(174, 188, 202, 0.40);
        border-radius: 10px;
        padding: 6px 12px;
    }
    QPushButton#FTCGenerateButton:hover {
        background-color: rgba(255, 254, 253, 0.66);
        color: #18293a;
        border-color: rgba(164, 169, 173, 0.58);
    }
    QPushButton#FTCGenerateButton:disabled {
        background-color: rgba(244, 244, 244, 0.76);
        color: #a4afbb;
        border-color: rgba(255, 255, 255, 0.66);
    }
    QTextEdit#FTCInlineInstructions {
        background-color: rgba(255, 255, 255, 0.72);
        color: #1a2836;
        border: 1px solid rgba(255, 255, 255, 0.88);
        border-radius: 18px;
        padding: 12px 14px;
    }
    QTextEdit#FTCInlineInstructions:focus {
        background-color: rgba(255, 255, 255, 0.88);
        border-color: rgba(154, 164, 174, 0.7);
    }
    QWidget#FTCFileRow {
        background-color: rgba(255, 255, 255, 0.98);
        border: 1px solid rgba(171, 186, 201, 0.3);
        border-radius: 18px;
    }
    QWidget#FTCFileBody, QWidget#FTCFileActions {
        background: transparent;
        border: none;
    }
    QWidget#FTCFileName {
        color: #1c2d3d;
        font-size: 13px;
        font-weight: 700;
        background: transparent;
    }
    QListWidget#FTCFileList {
        background: transparent;
        border: none;
    }
    QListWidget#FTCFileList::item {
        background: transparent;
        border: none;
        padding: 0px;
        margin: 0px;
    }
    QListWidget#FTCFileList::item:selected, QListWidget#FTCFileList::item:hover {
        background: transparent;
    }
    QFrame#DropZone {
        background-color: rgba(252, 254, 255, 0.98);
        border: 1px dashed #bcc9d7;
        border-radius: 20px;
    }
    QFrame#DropZone:disabled {
        background-color: #f2f5f8;
        border-color: #d5dee7;
    }
    QLabel#FTCPreviewThumb {
        background-color: #f5f8fb;
        border: 1px solid #dce5ee;
        border-radius: 12px;
        color: #67798a;
        font-size: 11px;
        font-weight: 800;
        padding: 4px;
    }
    QLabel#FTCPreviewDialog {
        background-color: #f7fafc;
        border: 1px solid #dde5ec;
        border-radius: 18px;
        padding: 12px;
    }
    QLineEdit#SearchInputField {
        min-height: 0px;
        padding: 0px;
        border: none;
        border-radius: 0px;
        background: transparent;
        font-size: 14px;
        color: #16202b;
    }
    QLineEdit#SearchInputField:focus {
        border: none;
        background: transparent;
    }
    QToolButton#SearchInputButton {
        background: transparent;
        border: none;
        border-radius: 15px;
        padding: 0px;
        min-width: 30px;
        min-height: 30px;
    }
    QToolButton#SearchInputButton:hover {
        background-color: rgba(235, 242, 248, 0.9);
    }
    QToolButton#SearchInputButton:pressed {
        background-color: rgba(222, 232, 241, 0.95);
    }
    QScrollArea {
        background: transparent;
        border: none;
    }
    QScrollBar:vertical {
        background: transparent;
        width: 14px;
        margin: 8px 3px 8px 3px;
    }
    QScrollBar::handle:vertical {
        background: #c7d3df;
        min-height: 56px;
        border-radius: 7px;
    }
    QScrollBar::handle:vertical:hover {
        background: #aebdcb;
    }
    QScrollBar::handle:vertical:pressed {
        background: #97aabd;
    }
    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {
        background: transparent;
        border: none;
        height: 0px;
    }
    QScrollBar::up-arrow:vertical,
    QScrollBar::down-arrow:vertical,
    QScrollBar::up-arrow:horizontal,
    QScrollBar::down-arrow:horizontal,
    QScrollBar::left-arrow:horizontal,
    QScrollBar::right-arrow:horizontal {
        width: 0px;
        height: 0px;
        background: transparent;
    }
    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical,
    QScrollBar::add-page:horizontal,
    QScrollBar::sub-page:horizontal {
        background: transparent;
    }
    QScrollBar:horizontal {
        background: transparent;
        height: 14px;
        margin: 3px 8px 3px 8px;
    }
    QScrollBar::handle:horizontal {
        background: #c7d3df;
        min-width: 56px;
        border-radius: 7px;
    }
    QScrollBar::handle:horizontal:hover {
        background: #aebdcb;
    }
    QScrollBar::handle:horizontal:pressed {
        background: #97aabd;
    }
    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal {
        background: transparent;
        border: none;
        width: 0px;
    }
    QPushButton#FTCToggle {
        background-color: rgba(255, 255, 255, 0.92);
        border: 1px solid rgba(166, 181, 197, 0.42);
        border-radius: 20px;
        padding: 10px 16px;
        font-size: 13px;
        font-weight: 700;
        color: #415466;
    }
    QPushButton#FTCToggle:hover {
        background-color: #f8fbfe;
        border-color: rgba(125, 162, 196, 0.78);
    }
    QPushButton#FTCToggle:checked {
        background-color: #0f2539;
        border-color: #0f2539;
        color: #ffffff;
    }
    QPushButton#FTCToggle:disabled {
        background-color: #f2f4f7;
        color: #a8b3bf;
        border-color: #dfe5eb;
    }
    """.replace("__CHECK_ICON__", check_icon)
    if resolve_theme_mode(mode) != "dark":
        return base
    return base + _dark_stylesheet(check_icon)


def _dark_stylesheet(check_icon: str) -> str:
    t = DARK_TOKENS
    return f"""
    * {{
        color: {t["text"]};
        selection-background-color: {t["selection"]};
        selection-color: #ffffff;
    }}
    QMainWindow, QDialog, QWidget {{
        background-color: {t["bg"]};
        color: {t["text"]};
    }}
    QMainWindow#OnCardMainWindow, QFrame#WindowTitleBar {{
        background: {t["bg"]};
    }}
    QWidget#AppShell, QLabel, QWidget#CardsCanvas, QWidget#CardEmptyState,
    QWidget#WindowLeftCluster, QWidget#WindowModeCluster, QWidget#WindowRightCluster,
    QWidget#AppIconMenu, QWidget#CreateOverlayHeaderControls, QWidget#FTCHeaderControls,
    QWidget#QuestionHeaderControls, QWidget#FTCFileBody, QWidget#FTCFileActions,
    QWidget#FTCRailCanvas {{
        background: transparent;
    }}
    QFrame#Surface, QFrame#SettingsWindowShell, QFrame#SettingsCard,
    QFrame#SettingsSectionCard, QFrame#SidebarSurface, QFrame#RecommendationBlock,
    QFrame#CardsSearchActions, QFrame#SearchInputShell, QFrame#SearchSuggestionDropdown,
    QFrame#AppIconMenuSurface, QFrame#UserProfileMenuSurface, QFrame#NotificationsMenuSurface,
    QFrame#CreateModeMenuSurface, QFrame#QuestionPromptCard, QFrame#FTCControlsPopupCard,
    QFrame#FTCPopupValueShell, QFrame#FTCPopupFieldShell {{
        background-color: {t["surface"]};
        border-color: {t["border"]};
    }}
    QStatusBar {{
        background: rgba(26, 35, 46, 0.96);
        border-top-color: {t["border"]};
        color: {t["muted"]};
    }}
    QLabel#PageTitle, QLabel#SectionTitle, QLabel#RecommendationTitle,
    QLabel#CardTitleLabel, QLabel#FTCFileCardName, QLabel#FTCPopupQuestionValue,
    QTextEdit#CardTitleDisplay {{
        color: {t["text_strong"]};
    }}
    QLabel#SectionText, QLabel#RecommendationMeta, QLabel#SmallMeta,
    QLabel#CardQuestionLabel, QLabel#FTCUploadTileText, QTextEdit#CardQuestionDisplay {{
        color: {t["muted"]};
    }}
    QLabel#TierBadge, QLabel#CardMetaPill, QLabel#FTCInlineMetaChip {{
        background-color: {t["surface_alt"]};
        color: {t["text"]};
        border-color: {t["border"]};
    }}
    QPushButton, QToolButton#CompactGhostButton, QToolButton#CardOptionsButton,
    QToolButton#FTCMenuButton, QToolButton#FTCFileRemove, QPushButton#FTCToggle,
    QPushButton#QuestionComposeButton, QToolButton#QuestionHeaderActionButton,
    QPushButton#CreateModeMenuButton, QPushButton#FTCPopupChoiceButton,
    QPushButton#FTCPopupStepButton, QPushButton#FTCGenerateButton {{
        background-color: {t["surface"]};
        border-color: {t["border"]};
        color: {t["text"]};
    }}
    QPushButton:hover, QToolButton#CompactGhostButton:hover, QToolButton#CardOptionsButton:hover,
    QToolButton#FTCMenuButton:hover, QToolButton#FTCFileRemove:hover,
    QPushButton#FTCToggle:hover, QPushButton#QuestionComposeButton:hover,
    QToolButton#QuestionHeaderActionButton:hover, QPushButton#CreateModeMenuButton:hover,
    QPushButton#FTCPopupChoiceButton:hover, QPushButton#FTCPopupStepButton:hover,
    QPushButton#FTCGenerateButton:hover {{
        background-color: {t["hover"]};
        border-color: rgba(121, 183, 255, 0.62);
        color: {t["text_strong"]};
    }}
    QPushButton:pressed, QPushButton#QuestionComposeButton:pressed,
    QPushButton#CreateModeMenuButton:pressed {{
        background-color: {t["pressed"]};
    }}
    QPushButton:disabled, QToolButton:disabled {{
        background-color: rgba(39, 51, 64, 0.78);
        color: #687586;
        border-color: rgba(104, 117, 134, 0.30);
    }}
    QPushButton#PrimaryButton, QPushButton#TopNavButton:checked, QPushButton#FTCToggle:checked,
    QPushButton#FTCPopupChoiceButton[selected="true"], QTabBar::tab:selected {{
        background-color: {t["primary"]};
        border-color: {t["primary"]};
        color: #07111b;
    }}
    QPushButton#PrimaryButton:hover {{
        background-color: {t["primary_hover"]};
        border-color: {t["primary_hover"]};
        color: #07111b;
    }}
    QPushButton#TopNavButton {{
        background-color: rgba(26, 35, 46, 0.86);
        color: {t["text"]};
        border-color: {t["border"]};
    }}
    QPushButton#TopNavButton:hover:!checked, QPushButton#AppIconMenuButton:hover,
    QPushButton#AppIconAccountButton:hover {{
        background-color: {t["hover"]};
        border-color: rgba(121, 183, 255, 0.62);
    }}
    QPushButton#AppIconMenuButton, QPushButton#AppIconAccountButton {{
        color: {t["text"]};
    }}
    QLineEdit, QTextEdit, QPlainTextEdit, QTextBrowser, QComboBox, QSpinBox {{
        background-color: {t["elevated"]};
        border-color: {t["border"]};
        color: {t["text"]};
        selection-background-color: {t["selection"]};
        selection-color: #ffffff;
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
    QSpinBox:focus, QLineEdit[focusRing="true"], QComboBox[focusRing="true"],
    QFrame#SearchInputShell[focusRing="true"] {{
        background-color: #223044;
        border-color: {t["primary"]};
    }}
    QLineEdit#SearchInputField {{
        background: transparent;
        border: none;
        color: {t["text"]};
    }}
    QComboBox QAbstractItemView, QWidget#ComboPopup, QMenu, QMenu#CardOptionsMenu {{
        background-color: {t["surface_solid"]};
        border-color: {t["border"]};
        color: {t["text"]};
        selection-background-color: {t["selection"]};
        selection-color: #ffffff;
    }}
    QComboBox QAbstractItemView::item:hover, QListWidget::item:hover,
    QListWidget#SearchSuggestionList::item:hover, QTreeWidget::item:hover,
    QMenu::item:selected, QMenu#CardOptionsMenu::item:selected {{
        background: {t["hover"]};
        color: {t["text_strong"]};
    }}
    QListWidget::item:selected, QTreeWidget::item:selected,
    QComboBox QAbstractItemView::item:selected {{
        background: {t["selection"]};
        color: #ffffff;
    }}
    QCheckBox::indicator {{
        background: {t["surface_solid"]};
        border-color: {t["border"]};
    }}
    QCheckBox::indicator:checked {{
        background: {t["primary"]};
        border-color: {t["primary"]};
        image: url("{check_icon}");
    }}
    QSlider::groove:horizontal, QSlider::sub-page:horizontal, QSlider::add-page:horizontal,
    QProgressBar {{
        background: #344253;
        color: {t["text"]};
    }}
    QSlider::handle:horizontal, QProgressBar::chunk {{
        background: {t["primary"]};
    }}
    QFrame#CardTile, QFrame#FTCUploadTile, QFrame#FTCFileCard, QFrame#FTCSkeletonCard,
    QWidget#FTCFileRow, QFrame#DropZone, QLabel#FTCPreviewThumb, QLabel#FTCPreviewDialog,
    QFrame#CreateWorkspaceSurface, QFrame#CreateQueueSurface, QFrame#FTCWorkspaceSurface,
    QFrame#CreateOverlayCard, QFrame#CreateIdleSurface, QFrame#QuestionComposeShell {{
        background-color: rgba(26, 35, 46, 0.78);
        border-color: {t["border"]};
    }}
    QFrame#FTCSkeletonThumb, QFrame#FTCSkeletonBar, QFrame#FTCSkeletonBarSoft {{
        background-color: #344253;
    }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal,
    QDialog QScrollBar::handle:vertical {{
        background: #46586c;
    }}
    QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover,
    QDialog QScrollBar::handle:vertical:hover {{
        background: #5b7087;
    }}
    QMenu::separator {{
        background: rgba(122, 142, 164, 0.28);
    }}
    QToolTip {{
        color: {t["text_strong"]};
        background-color: #0b1118;
        border-color: rgba(122, 142, 164, 0.42);
    }}
    """

