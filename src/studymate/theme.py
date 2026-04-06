from __future__ import annotations


def app_stylesheet() -> str:
    return """
    * {
        font-family: "Nunito Sans", "Segoe UI Variable Text", "Segoe UI", "Noto Sans", sans-serif;
        color: #16202b;
        font-size: 13px;
        background: transparent;
    }
    QMainWindow, QDialog {
        background-color: #edf2f7;
    }
    QMainWindow#OnCardMainWindow {
        background: #edf2f7;
    }
    QWidget {
        background-color: #edf2f7;
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
        border-radius: 19px;
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
        min-width: 92px;
        padding: 6px 14px;
        border-radius: 15px;
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
        background-color: #edf2f7;
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
        color: #172330;
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
        color: #141414;
    }
    QTextEdit#CardQuestionDisplay {
        font-size: 13px;
        color: #5b5b5b;
    }
    QLabel#CardTitleLabel {
        font-family: "Nunito Sans", "Segoe UI Variable Display", "Segoe UI", sans-serif;
        font-size: 15px;
        font-weight: 700;
        color: #141414;
    }
    QLabel#CardQuestionLabel {
        font-size: 13px;
        color: #5b5b5b;
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
    QFrame#QueueRow {
        background-color: rgba(248, 251, 253, 0.98);
        border: 1px solid rgba(167, 182, 199, 0.32);
        border-radius: 18px;
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
    QFrame#FTCControlsSurface {
        background-color: rgba(252, 253, 255, 0.98);
        border: 1px solid rgba(171, 186, 201, 0.26);
        border-radius: 18px;
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
    """

