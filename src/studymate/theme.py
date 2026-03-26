from __future__ import annotations


def app_stylesheet() -> str:
    return """
    * {
        font-family: "Nunito Sans", "Segoe UI Variable Text", "Segoe UI", "Noto Sans", sans-serif;
        color: #141414;
        font-size: 13px;
        background: transparent;
    }
    QMainWindow, QDialog, QWidget {
        background-color: #f4f4f4;
    }
    QLabel {
        background: transparent;
    }
    QFrame#Surface {
        background-color: #ffffff;
        border: 1px solid #e4e4e4;
        border-radius: 22px;
    }
    QFrame#SidebarSurface {
        background-color: #f0f0f0;
        border: 1px solid #dddddd;
        border-radius: 24px;
    }
    QFrame#RecommendationBlock {
        background-color: #f7f7f7;
        border: 1px solid #e8e8e8;
        border-radius: 22px;
    }
    QWidget#CardsCanvas {
        background-color: #f7f7f7;
    }
    QLabel#RecommendationTitle {
        font-family: "Nunito Sans", "Segoe UI Variable Display", "Segoe UI", sans-serif;
        font-size: 18px;
        font-weight: 700;
        color: #141414;
    }
    QLabel#RecommendationMeta {
        font-size: 12px;
        color: #6e6e6e;
    }
    QLabel#PageTitle {
        font-family: "Nunito Sans", "Segoe UI Variable Display", "Segoe UI", sans-serif;
        font-size: 28px;
        font-weight: 700;
        color: #111111;
    }
    QLabel#SectionTitle {
        font-family: "Nunito Sans", "Segoe UI Variable Display", "Segoe UI", sans-serif;
        font-size: 16px;
        font-weight: 650;
        color: #1c1c1c;
    }
    QLabel#SectionText {
        font-size: 13px;
        line-height: 1.45;
        color: #5b5b5b;
    }
    QLabel#SmallMeta {
        font-size: 13px;
        color: #7b7b7b;
    }
    QLabel#TierBadge {
        background-color: #efefef;
        color: #1f1f1f;
        border: 1px solid #d8d8d8;
        border-radius: 18px;
        padding: 8px 14px;
        font-weight: 700;
    }
    QLabel#FTCBetaBadge {
        background-color: #151515;
        color: #ffffff;
        border: 1px solid #151515;
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
        background-color: #1f1f1f;
        min-width: 12px;
        max-width: 12px;
        min-height: 12px;
        max-height: 12px;
        border-radius: 6px;
    }
    QPushButton {
        background-color: #ececec;
        border: 1px solid #d7d7d7;
        border-radius: 16px;
        padding: 10px 16px;
        font-size: 14px;
        font-weight: 600;
    }
    QPushButton:hover {
        background-color: #e1e1e1;
        border-color: #c8c8c8;
    }
    QPushButton:pressed {
        background-color: #d8d8d8;
    }
    QPushButton:disabled {
        background-color: #ededed;
        color: #a5a5a5;
        border-color: #e3e3e3;
    }
    QPushButton#PrimaryButton {
        background-color: #111111;
        color: #ffffff;
        border: 1px solid #111111;
    }
    QPushButton#PrimaryButton:hover {
        background-color: #222222;
        border-color: #222222;
    }
    QPushButton#DangerlessButton {
        background-color: #f1f1f1;
        border-color: #dcdcdc;
    }
    QPushButton#CompactGhostButton {
        background-color: #ffffff;
        border: 1px solid #e4e4e4;
        border-radius: 10px;
        padding: 6px 10px;
        font-size: 11px;
        font-weight: 700;
        min-width: 0px;
    }
    QPushButton#CompactGhostButton:hover {
        background-color: #f4f4f4;
        border-color: #d8d8d8;
    }
    QToolButton#CompactGhostButton {
        background-color: #ffffff;
        border: 1px solid #e4e4e4;
        border-radius: 10px;
        padding: 6px 10px;
        font-size: 11px;
        font-weight: 700;
    }
    QToolButton#CompactGhostButton:hover {
        background-color: #f4f4f4;
        border-color: #d8d8d8;
    }
    QPushButton#TopNavButton {
        min-width: 110px;
        padding: 12px 18px;
        border-radius: 18px;
        background-color: #f2f2f2;
        color: #141414;
        border-color: #dddddd;
    }
    QPushButton#TopNavButton:checked {
        background-color: #dddddd;
        color: #111111;
        border-color: #cfcfcf;
    }
    QPushButton#SettingsNavButton {
        min-width: 0px;
        padding: 0px;
        border: none;
        border-radius: 0px;
        background: transparent;
    }
    QPushButton#SettingsNavButton:hover {
        background: transparent;
        border: none;
    }
    QPushButton#SettingsNavButton:pressed {
        background: transparent;
        border: none;
    }
    QToolButton#CollapseButton {
        background-color: transparent;
        border: none;
        padding: 6px;
        font-size: 18px;
        color: #222222;
    }
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {
        background-color: #ffffff;
        border: 1px solid #e2e2e2;
        border-radius: 16px;
        padding: 12px 14px;
        font-size: 14px;
        selection-background-color: #cfcfcf;
    }
    QComboBox {
        padding-right: 34px;
    }
    QSpinBox::up-button, QSpinBox::down-button {
        width: 24px;
        border: none;
        margin-right: 8px;
    }
    QSpinBox::up-arrow, QSpinBox::down-arrow {
        width: 10px;
        height: 10px;
    }
    QTextEdit, QPlainTextEdit {
        line-height: 1.5;
    }
    QTextBrowser {
        background-color: #fafafa;
        border: 1px solid #e4e4e4;
        border-radius: 18px;
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
        background-color: #f1f1f1;
        color: #343434;
        border: 1px solid #e3e3e3;
        border-radius: 12px;
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
    QListWidget::item {
        border-radius: 14px;
        padding: 10px 12px;
        margin: 4px 0px;
    }
    QListWidget::item:selected {
        background-color: #dddddd;
        color: #111111;
    }
    QListWidget::item:hover {
        background-color: #e9e9e9;
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
        background: #e8e8e8;
    }
    QTreeWidget::item:selected {
        background: #dcdcdc;
        color: #111111;
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
        border: 1px solid #cfcfcf;
        background: #ffffff;
    }
    QCheckBox::indicator:checked {
        background: #111111;
        border: 1px solid #111111;
    }
    QComboBox::drop-down {
        width: 34px;
        border: none;
        subcontrol-origin: padding;
        subcontrol-position: top right;
        background: transparent;
    }
    QComboBox QAbstractItemView {
        background-color: #ffffff;
        border: 1px solid #e3e3e3;
        border-radius: 10px;
        padding: 8px 6px;
        outline: none;
        selection-background-color: #ececec;
        selection-color: #111111;
    }
    QComboBox QAbstractItemView::item {
        min-height: 22px;
        padding: 8px 12px;
        margin: 2px 4px;
        border-radius: 10px;
    }
    QComboBox QAbstractItemView::item:hover {
        background: #f2f2f2;
    }
    QComboBox QAbstractItemView::item:selected {
        background: #e8e8e8;
        color: #111111;
    }
    QSlider::groove:horizontal {
        height: 6px;
        border-radius: 4px;
        background: #d6d6d6;
    }
    QSlider::handle:horizontal {
        width: 20px;
        height: 20px;
        margin: -7px 0;
        border-radius: 10px;
        background: #111111;
    }
    QProgressBar {
        background-color: #ededed;
        border: none;
        border-radius: 14px;
        min-height: 16px;
        text-align: center;
        font-weight: 700;
        color: #111111;
    }
    QProgressBar::chunk {
        background-color: #111111;
        border-radius: 14px;
    }
    QTabWidget::pane {
        border: none;
        background: transparent;
    }
    QTabBar::tab {
        background-color: #efefef;
        border: 1px solid #dcdcdc;
        border-radius: 14px;
        padding: 10px 18px;
        margin-right: 8px;
        color: #2b2b2b;
        font-weight: 700;
        min-width: 90px;
    }
    QTabBar::tab:selected {
        background-color: #111111;
        border-color: #111111;
        color: #ffffff;
    }
    QTabBar::tab:hover:!selected {
        background-color: #e7e7e7;
        border-color: #d1d1d1;
    }
    QFrame#CardTile {
        background-color: #ffffff;
        border: 1px solid #e2e2e2;
        border-radius: 20px;
    }
    QFrame#CardTile:hover {
        background-color: #fafafa;
        border-color: #cfcfcf;
    }
    QToolButton#CardOptionsButton {
        background-color: #ffffff;
        color: #343434;
        border: 1px solid #e4e4e4;
        border-radius: 10px;
        padding: 5px 10px;
        font-size: 11px;
        font-weight: 700;
    }
    QToolButton#CardOptionsButton:hover {
        background-color: #f4f4f4;
        border-color: #d7d7d7;
    }
    QToolButton#CardOptionsButton::menu-indicator {
        image: none;
        width: 0px;
    }
    QFrame#QueueRow {
        background-color: #fafafa;
        border: 1px solid #e6e6e6;
        border-radius: 16px;
    }
    QMenu {
        background-color: #ffffff;
        border: 1px solid #dcdcdc;
        border-radius: 10px;
        padding: 6px;
        margin: 0px;
    }
    QMenu::item {
        background-color: #ffffff;
        color: #141414;
        border: none;
        border-radius: 8px;
        padding: 8px 14px;
        margin: 1px 0px;
    }
    QMenu::item:selected {
        background-color: #efefef;
        color: #111111;
    }
    QMenu::separator {
        height: 1px;
        background: #ececec;
        margin: 6px 8px;
    }
    QMenu#CardOptionsMenu {
        background-color: #ffffff;
        border: 1px solid #e3e3e3;
        border-radius: 10px;
        padding: 8px 6px;
        margin: 0px;
    }
    QMenu#CardOptionsMenu::item {
        background: transparent;
        color: #141414;
        border: none;
        border-radius: 10px;
        padding: 8px 12px;
        margin: 2px 4px;
    }
    QMenu#CardOptionsMenu::item:selected {
        background: #e8e8e8;
        color: #111111;
    }
    QFrame#FTCControlsSurface {
        background-color: #fcfcfc;
        border: 1px solid #ececec;
        border-radius: 16px;
    }
    QWidget#FTCFileRow {
        background-color: #ffffff;
        border: 1px solid #ececec;
        border-radius: 16px;
    }
    QWidget#FTCFileBody, QWidget#FTCFileActions {
        background: transparent;
        border: none;
    }
    QWidget#FTCFileName {
        color: #232323;
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
        background-color: #fbfbfb;
        border: 1px dashed #cfcfcf;
        border-radius: 18px;
    }
    QFrame#DropZone:disabled {
        background-color: #f2f2f2;
        border-color: #dddddd;
    }
    QLabel#FTCPreviewThumb {
        background-color: #f6f6f6;
        border: 1px solid #e6e6e6;
        border-radius: 12px;
        color: #666666;
        font-size: 11px;
        font-weight: 800;
        padding: 4px;
    }
    QLabel#FTCPreviewDialog {
        background-color: #fafafa;
        border: 1px solid #e6e6e6;
        border-radius: 18px;
        padding: 12px;
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
        background: #d1d1d1;
        min-height: 56px;
        border-radius: 7px;
    }
    QScrollBar::handle:vertical:hover {
        background: #bdbdbd;
    }
    QScrollBar::handle:vertical:pressed {
        background: #ababab;
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
        background: #d1d1d1;
        min-width: 56px;
        border-radius: 7px;
    }
    QScrollBar::handle:horizontal:hover {
        background: #bdbdbd;
    }
    QScrollBar::handle:horizontal:pressed {
        background: #ababab;
    }
    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal {
        background: transparent;
        border: none;
        width: 0px;
    }
    QPushButton#FTCToggle {
        background-color: #f2f2f2;
        border: 1px solid #dddddd;
        border-radius: 18px;
        padding: 10px 16px;
        font-size: 13px;
        font-weight: 700;
        color: #494949;
    }
    QPushButton#FTCToggle:hover {
        background-color: #ebebeb;
        border-color: #d3d3d3;
    }
    QPushButton#FTCToggle:checked {
        background-color: #111111;
        border-color: #111111;
        color: #ffffff;
    }
    QPushButton#FTCToggle:disabled {
        background-color: #ededed;
        color: #a8a8a8;
        border-color: #e3e3e3;
    }
    """
