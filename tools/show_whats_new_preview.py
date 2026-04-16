from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from studymate.services.update_content import load_packaged_update_content  # noqa: E402
from studymate.theme import app_stylesheet  # noqa: E402
from studymate.ui.update_dialog import WhatsNewDialog, WhatsNewSummaryDialog  # noqa: E402


def main() -> int:
    version = sys.argv[1] if len(sys.argv) > 1 else "1.4.7"
    app = QApplication(sys.argv)
    fonts_dir = ROOT / "assets" / "fonts" / "NunitoSans"
    if fonts_dir.exists():
        for font_path in fonts_dir.glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont("Nunito Sans", 10))
    app.setStyleSheet(app_stylesheet())
    app_icon = ROOT / "assets" / "icons" / "app" / "app_logo.png"
    if app_icon.exists():
        app.setWindowIcon(QIcon(str(app_icon)))
    content = load_packaged_update_content(ROOT / "assets", version)
    intro = WhatsNewSummaryDialog(version=version, content=content)
    result = intro.exec()
    if intro.dive_deeper_requested:
        dialog = WhatsNewDialog(version=version, content=content)
        return dialog.exec()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
