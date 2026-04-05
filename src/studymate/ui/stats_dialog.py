from __future__ import annotations

from pathlib import Path
import re
import shutil

from PySide6.QtCore import QEasingCurve, QPointF, Property, QPropertyAnimation, QRectF, QSize, Qt, QVariantAnimation, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QFileDialog,
    QTextBrowser,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from studymate.services.data_store import DataStore
from studymate.services.ollama_service import OllamaService
from studymate.services.stats_service import RANGE_CONFIGS, StatsService
from studymate.ui.animated import AnimatedComboBox, polish_surface
from studymate.workers.stats_summary_worker import StatsSummaryWorker


class GradientGlowLabel(QWidget):
    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self._text = text
        self.setMinimumHeight(52)

    def setText(self, text: str) -> None:
        self._text = text
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        font = QFont(self.font())
        font.setPointSize(24)
        font.setWeight(QFont.Weight.ExtraBold)
        painter.setFont(font)
        text_rect = self.rect().adjusted(2, 2, -2, -2)

        shadow_color = QColor(67, 210, 255, 70)
        painter.setPen(shadow_color)
        painter.drawText(text_rect.translated(2, 2), Qt.AlignLeft | Qt.AlignVCenter, self._text)

        gradient = QLinearGradient(0, 0, self.width(), 0)
        gradient.setColorAt(0.0, QColor("#57F2FF"))
        gradient.setColorAt(0.5, QColor("#57A8FF"))
        gradient.setColorAt(1.0, QColor("#4BE08A"))
        painter.setPen(QPen(gradient, 1.2))
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, self._text)


class AnimatedLineChart(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._points: list[dict] = []
        self._progress = 0.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(1420)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.valueChanged.connect(self._on_progress)
        self.setMinimumHeight(180)

    def _on_progress(self, value) -> None:
        try:
            self._progress = float(value)
        except (TypeError, ValueError):
            self._progress = 1.0
        self.update()

    def set_points(self, points: list[dict]) -> None:
        self._points = list(points or [])
        self._animation.stop()
        self._progress = 0.0
        self._animation.start()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(8, 10, -8, -28)
        if rect.width() <= 12 or rect.height() <= 12:
            return

        painter.setPen(QPen(QColor("#D7E2EE"), 1))
        for row in range(6):
            y = rect.top() + (rect.height() * row / 5.0)
            painter.drawLine(rect.left(), int(y), rect.right(), int(y))

        values = [float(item.get("value", 0.0) or 0.0) for item in self._points]
        if not values:
            return
        max_value = max(max(values), 10.0)
        min_value = 0.0
        span = max(max_value - min_value, 1.0)
        points: list[QPointF] = []
        total = max(len(values) - 1, 1)
        for idx, value in enumerate(values):
            x = rect.left() + rect.width() * (idx / total)
            normalized = (value - min_value) / span
            y = rect.bottom() - (rect.height() * normalized)
            points.append(QPointF(float(x), float(y)))
        if len(points) == 1:
            points.append(QPointF(rect.right(), points[0].y()))

        progress = max(0.0, min(self._progress, 1.0))
        visible = [
            QPointF(
                point.x(),
                rect.bottom() - ((rect.bottom() - point.y()) * progress),
            )
            for point in points
        ]

        if len(visible) >= 2:
            path = QPainterPath(visible[0])
            for point in visible[1:]:
                path.lineTo(point)
            painter.setPen(QPen(QColor("#3A97FF"), 2.2))
            painter.drawPath(path)

            area = QPainterPath(path)
            area.lineTo(visible[-1].x(), rect.bottom())
            area.lineTo(visible[0].x(), rect.bottom())
            area.closeSubpath()
            fill = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
            fill.setColorAt(0.0, QColor(58, 151, 255, 76))
            fill.setColorAt(1.0, QColor(58, 151, 255, 10))
            painter.fillPath(area, fill)

        for point in visible[-4:]:
            painter.setBrush(QColor("#3A97FF"))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(point, 3.2, 3.2)

        painter.setPen(QColor("#6F7B88"))
        label_count = min(len(self._points), 6)
        if label_count <= 1:
            label_count = len(self._points)
        for idx in range(label_count):
            source_index = int((len(self._points) - 1) * (idx / max(label_count - 1, 1)))
            raw_label = str(self._points[source_index].get("label", "")).strip()
            # Guard against accidental non-axis text leaking into chart labels.
            text = raw_label if re.fullmatch(r"[A-Za-z0-9:\-]{1,8}", raw_label) else f"D{source_index + 1}"
            x = rect.left() + rect.width() * (source_index / max(len(self._points) - 1, 1))
            painter.drawText(QRectF(x - 26, rect.bottom() + 5, 52, 16), Qt.AlignCenter, text)


class AnimatedBarChart(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._bars: list[dict] = []
        self._progress = 0.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(940)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.valueChanged.connect(self._on_progress)
        self.setMinimumHeight(220)

    def _on_progress(self, value) -> None:
        try:
            self._progress = float(value)
        except (TypeError, ValueError):
            self._progress = 1.0
        self.update()

    def set_bars(self, bars: list[dict]) -> None:
        self._bars = list(bars or [])
        self._animation.stop()
        self._progress = 0.0
        self._animation.start()

    @staticmethod
    def _ease_out_cubic(value: float) -> float:
        clamped = max(0.0, min(value, 1.0))
        return 1.0 - ((1.0 - clamped) ** 3)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(8, 10, -8, -40)
        if rect.width() <= 12 or rect.height() <= 12:
            return
        painter.setPen(QPen(QColor("#D7E2EE"), 1))
        for row in range(6):
            y = rect.top() + (rect.height() * row / 5.0)
            painter.drawLine(rect.left(), int(y), rect.right(), int(y))
        if not self._bars:
            return
        max_value = max(10.0, max(float(item.get("avg_marks", 0.0) or 0.0) for item in self._bars))
        bar_count = len(self._bars)
        slot_width = rect.width() / max(bar_count, 1)
        bar_width = min(28.0, slot_width * 0.58)

        for idx, item in enumerate(self._bars):
            value = float(item.get("avg_marks", 0.0) or 0.0)
            ratio = max(0.0, min(value / max_value, 1.0))
            stagger = idx * 0.045
            denom = max(0.18, 1.0 - stagger)
            local_progress = (self._progress - stagger) / denom
            eased_progress = self._ease_out_cubic(local_progress)
            bar_height = rect.height() * ratio * eased_progress
            x_center = rect.left() + slot_width * (idx + 0.5)
            bar_rect = QRectF(x_center - bar_width / 2, rect.bottom() - bar_height, bar_width, bar_height)

            gradient = QLinearGradient(bar_rect.left(), bar_rect.top(), bar_rect.left(), bar_rect.bottom())
            gradient.setColorAt(0.0, QColor("#50B8FF"))
            gradient.setColorAt(1.0, QColor("#2E7DFF"))
            painter.setPen(Qt.NoPen)
            painter.setBrush(gradient)
            painter.drawRoundedRect(bar_rect, 5.0, 5.0)

            subject = str(item.get("subject", ""))
            subject_label = subject if len(subject) <= 11 else f"{subject[:10]}…"
            painter.setPen(QColor("#6F7B88"))
            painter.drawText(QRectF(x_center - slot_width / 2, rect.bottom() + 6, slot_width, 32), Qt.AlignHCenter | Qt.AlignTop, subject_label)


class SummarySkeleton(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(24)
        self._timer.timeout.connect(self._advance)
        self.setMinimumHeight(260)

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def stop(self) -> None:
        self._timer.stop()

    def _advance(self) -> None:
        self._phase = (self._phase + 0.025) % 1.0
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor(166, 181, 197, 96), 1))
        painter.setBrush(QColor(255, 255, 255, 255))
        painter.drawRoundedRect(rect, 22.0, 22.0)

        content = rect.adjusted(16, 16, -16, -16)
        line_height = 14
        gap = 10
        widths = [0.90, 0.95, 0.82, 0.92, 0.66, 0.88, 0.94, 0.74, 0.86]
        for index, ratio in enumerate(widths):
            top = int(content.top() + index * (line_height + gap))
            if top + line_height > content.bottom():
                break
            bar = QRectF(content.left(), top, content.width() * ratio, line_height)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(230, 236, 243))
            painter.drawRoundedRect(bar, 8.0, 8.0)

            shimmer_width = max(46.0, bar.width() * 0.28)
            track = max(1.0, bar.width() + shimmer_width)
            x = bar.left() - shimmer_width + track * self._phase
            highlight = QRectF(x, bar.top(), shimmer_width, bar.height())
            gradient = QLinearGradient(highlight.left(), 0, highlight.right(), 0)
            gradient.setColorAt(0.0, QColor(255, 255, 255, 0))
            gradient.setColorAt(0.5, QColor(255, 255, 255, 145))
            gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setBrush(gradient)
            painter.drawRoundedRect(bar, 8.0, 8.0)


class SummaryRevealOverlay(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._progress = 0.0
        self._pixmap = QPixmap()
        self.hide()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def setPixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.update()

    def getProgress(self) -> float:
        return self._progress

    def setProgress(self, value: float) -> None:
        try:
            self._progress = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            self._progress = 1.0
        self.update()

    progress = Property(float, getProgress, setProgress)

    def paintEvent(self, event) -> None:
        del event
        if self._pixmap.isNull():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        outer = self.rect().adjusted(1, 1, -1, -1)
        if outer.width() <= 2 or outer.height() <= 2:
            return

        path = QPainterPath()
        path.addRoundedRect(QRectF(outer), 22.0, 22.0)
        painter.fillPath(path, QColor("#FFFFFF"))
        painter.setPen(QPen(QColor(166, 181, 197, 97), 1))
        painter.drawPath(path)

        content = outer.adjusted(1, 1, -1, -1)
        reveal_bottom = content.top() + (content.height() * self._progress)
        if reveal_bottom <= content.top():
            return

        source = QRectF(0, 0, self._pixmap.width(), self._pixmap.height())
        target = QRectF(content)

        painter.save()
        painter.setClipPath(path)
        painter.setClipRect(QRectF(content.left(), content.top(), content.width(), reveal_bottom - content.top()))
        painter.drawPixmap(target, self._pixmap, source)
        painter.restore()

        if reveal_bottom < content.bottom():
            feather = min(54.0, content.height() * 0.18)
            band_top = max(content.top(), reveal_bottom - feather)
            gradient = QLinearGradient(content.left(), band_top, content.left(), reveal_bottom)
            gradient.setColorAt(0.0, QColor(255, 255, 255, 0))
            gradient.setColorAt(1.0, QColor(255, 255, 255, 255))
            painter.save()
            painter.setClipPath(path)
            painter.fillRect(QRectF(content.left(), band_top, content.width(), reveal_bottom - band_top), gradient)
            painter.restore()


class StatsDialog(QDialog):
    def __init__(
        self,
        datastore: DataStore,
        ollama: OllamaService,
        session_controller,
        parent=None,
        close_icon_path: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.datastore = datastore
        self.ollama = ollama
        self.session_controller = session_controller
        self.close_icon_path = close_icon_path
        self.stats_service = StatsService()
        self.profile = self.datastore.load_profile()
        self._summary_token = 0
        self._summary_worker: StatsSummaryWorker | None = None
        self._summary_workers: set[StatsSummaryWorker] = set()
        self._summary_reveal_anim: QPropertyAnimation | None = None
        self._last_summary_markdown = "No summary available yet."
        self._drag_offset = None
        self._summary_scroll_anim: QPropertyAnimation | None = None

        self.setWindowTitle("View stats")
        self.setObjectName("StatsDialog")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._apply_initial_geometry()
        self._build_ui()
        self._animate_intro()
        self._refresh_stats()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_offset is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._summary_worker = None
        for worker in list(self._summary_workers):
            try:
                worker.requestInterruption()
            except RuntimeError:
                continue
        for worker in list(self._summary_workers):
            try:
                if worker.isRunning():
                    worker.wait(1500)
            except RuntimeError:
                continue
        if hasattr(self, "summary_skeleton"):
            self.summary_skeleton.stop()
        super().closeEvent(event)

    def _apply_initial_geometry(self) -> None:
        screen = self.screen()
        if screen is None:
            self.resize(860, 720)
            return
        available = screen.availableGeometry()
        width = min(860, max(720, available.width() - 120))
        height = min(720, max(560, available.height() - 120))
        self.resize(width, height)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(0)

        self.surface = QFrame()
        self.surface.setObjectName("Surface")
        self.surface.setProperty("statsMain", True)
        shadow = QGraphicsDropShadowEffect(self.surface)
        shadow.setBlurRadius(56)
        shadow.setOffset(0, 0)
        shadow.setColor(QColor(15, 37, 57, 78))
        self.surface.setGraphicsEffect(shadow)
        polish_surface(self.surface)
        frame = QVBoxLayout(self.surface)
        frame.setContentsMargins(18, 18, 18, 12)
        frame.setSpacing(10)

        name = str(self.profile.get("name", "")).strip() or "Student"
        age = str(self.profile.get("age", "")).strip() or "unknown age"
        hobbies = str(self.profile.get("hobbies", "")).strip() or "learning"

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)
        self.greeting = GradientGlowLabel(f"Hello, {name}")
        header_row.addWidget(self.greeting, 1)

        self.close_btn = QPushButton("")
        self.close_btn.setObjectName("StatsCloseButton")
        self.close_btn.setToolTip("Close")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setFixedSize(34, 34)
        self.close_btn.clicked.connect(self.close)
        icon = self._close_icon()
        if not icon.isNull():
            self.close_btn.setIcon(icon)
            self.close_btn.setIconSize(QSize(16, 16))
        header_row.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)
        frame.addLayout(header_row)

        profile_meta = QLabel(f"{name}, is {age}, and likes {hobbies}")
        profile_meta.setObjectName("SectionText")
        profile_meta.setWordWrap(True)
        profile_meta.setStyleSheet('font-size: 14px; color: #3E4D5D;')
        frame.addWidget(profile_meta)

        range_row = QHBoxLayout()
        range_row.setContentsMargins(0, 4, 0, 0)
        range_row.setSpacing(8)
        range_label = QLabel("Range")
        range_label.setObjectName("SectionTitle")
        self.range_combo = AnimatedComboBox()
        self.range_combo.setObjectName("StatsRangeCombo")
        self.range_combo.setStyleSheet(
            """
            QComboBox#StatsRangeCombo QAbstractItemView {
                border: none;
                outline: none;
                background-color: rgba(255, 255, 255, 0.98);
                border-radius: 14px;
                padding: 8px 6px;
                selection-background-color: #e4eef8;
                selection-color: #122131;
            }
            """
        )
        self.range_combo.addItem("Hourly", "hourly")
        self.range_combo.addItem("Daily 3 days", "daily")
        self.range_combo.addItem("Weekly", "weekly")
        self.range_combo.addItem("2 Weeks", "2weeks")
        self.range_combo.addItem("Monthly", "monthly")
        setup = self.datastore.load_setup()
        stats_setup = dict(setup.get("stats", {}))
        default_range = str(stats_setup.get("default_range", "daily")).strip().lower() or "daily"
        default_index = self.range_combo.findData(default_range)
        if default_index < 0:
            default_index = self.range_combo.findData("daily")
        if default_index < 0:
            default_index = 1
        self.range_combo.setCurrentIndex(default_index)
        self.range_combo.currentIndexChanged.connect(self._refresh_stats)
        range_row.addWidget(range_label)
        range_row.addWidget(self.range_combo, 1)
        frame.addLayout(range_row)

        title1 = QLabel("How you have performed today:")
        title1.setObjectName("SectionTitle")
        frame.addWidget(title1)
        self.line_chart = AnimatedLineChart()
        frame.addWidget(self.line_chart)

        title2 = QLabel("This is how good you performed for the given subjects")
        title2.setObjectName("SectionTitle")
        frame.addWidget(title2)
        self.bar_chart = AnimatedBarChart()
        frame.addWidget(self.bar_chart)

        summary_title = QLabel("Summary")
        summary_title.setObjectName("SectionTitle")
        frame.addWidget(summary_title)

        self.summary = QTextBrowser()
        self.summary.setObjectName("StatsSummary")
        self.summary.setMinimumHeight(260)
        self.summary.setOpenExternalLinks(False)
        self.summary.setStyleSheet(
            "QTextBrowser#StatsSummary { border: 1px solid rgba(166,181,197,0.38); border-radius: 22px; padding: 12px; background: #ffffff; }"
        )
        self.summary_container = QWidget()
        summary_layout = QVBoxLayout(self.summary_container)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(0)
        summary_layout.addWidget(self.summary)
        self.summary_skeleton = SummarySkeleton()
        self.summary_skeleton.setObjectName("SummarySkeleton")

        self.summary_stack_host = QWidget()
        self.summary_stack = QStackedLayout(self.summary_stack_host)
        self.summary_stack.setContentsMargins(0, 0, 0, 0)
        self.summary_stack.setStackingMode(QStackedLayout.StackOne)
        self.summary_stack.addWidget(self.summary_skeleton)
        self.summary_stack.addWidget(self.summary_container)
        self.summary_stack.setCurrentWidget(self.summary_container)
        self.summary_stack_host.setStyleSheet("background: transparent; border: none;")
        self.summary_container.setStyleSheet("background: transparent; border: none;")
        self.summary_skeleton.setStyleSheet("background: transparent; border: none;")
        self.summary_reveal_overlay = SummaryRevealOverlay(self.summary_stack_host)
        frame.addWidget(self.summary_stack_host)

        self.links = QTextBrowser()
        self.links.setMaximumHeight(30)
        self.links.setOpenLinks(False)
        self.links.setOpenExternalLinks(False)
        self.links.setFrameShape(QFrame.NoFrame)
        self.links.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.links.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.links.setStyleSheet(
            """
            QTextBrowser {
                background: transparent;
                border: none;
                font-size: 11px;
            }
            a {
                color: #8C96A1;
                text-decoration: none;
            }
            a:hover {
                color: #2E7DFF;
            }
            """
        )
        self.links.setHtml(
            "<a href='export'>export account</a> &nbsp;&nbsp; "
            "<a href='delete'>delete account</a> &nbsp;&nbsp; "
            "<a href='change'>change account</a> &nbsp;&nbsp; "
            "<a href='new'>New account</a>"
        )
        self.links.anchorClicked.connect(self._on_link_clicked)
        frame.addWidget(self.links)

        root.addWidget(self.surface, 1)

    def _close_icon(self) -> QIcon:
        if self.close_icon_path is not None and self.close_icon_path.exists():
            return QIcon(str(self.close_icon_path))
        parent = self.parent()
        candidate = getattr(getattr(parent, "paths", None), "icons", None)
        if isinstance(candidate, Path):
            path = candidate / "common" / "close.png"
            if path.exists():
                return QIcon(str(path))
        return QIcon()

    def _animate_intro(self) -> None:
        return

    def _refresh_stats(self) -> None:
        range_key = str(self.range_combo.currentData() or "hourly")
        snapshot = self.stats_service.summarize(
            range_key=range_key,
            attempts=self.datastore.load_attempts(),
            cards=self.datastore.list_all_cards(),
        )
        self.line_chart.set_points(snapshot.get("line_points", []))
        bars = list(snapshot.get("subject_scores", []))[:10]
        self.bar_chart.set_bars(bars)
        self._refresh_summary(snapshot)

    def _refresh_summary(self, snapshot: dict) -> None:
        previous_worker = self._summary_worker
        if previous_worker is not None:
            try:
                if previous_worker.isRunning():
                    previous_worker.requestInterruption()
            except RuntimeError:
                pass
        self._summary_worker = None
        self._summary_token += 1
        token = self._summary_token
        summary_payload = dict(snapshot.get("summary_payload", {}))
        context_length = int(snapshot.get("range", {}).get("context_length", 4000))
        self._show_summary_skeleton(force=True)

        worker = StatsSummaryWorker(
            ollama=self.ollama,
            profile=self.profile,
            summary_payload=summary_payload,
            context_length=context_length,
            model="gemma3:4b",
        )
        self._summary_worker = worker
        self._summary_workers.add(worker)

        def _release_worker() -> None:
            self._summary_workers.discard(worker)
            worker.deleteLater()

        def _done(markdown: str) -> None:
            if token != self._summary_token:
                return
            self._summary_worker = None
            self._show_summary_result(markdown or "No summary available yet.", token)

        def _failed(message: str) -> None:
            if token != self._summary_token:
                return
            self._summary_worker = None
            self._show_summary_result(f"Summary could not be generated right now.\n\n- {message}", token)

        worker.finished.connect(_done)
        worker.failed.connect(_failed)
        worker.finished.connect(_release_worker)
        worker.failed.connect(_release_worker)
        worker.start()

    def _has_summary_content(self) -> bool:
        return bool((self._last_summary_markdown or "").strip()) and self._last_summary_markdown.strip() != "No summary available yet."

    def _show_summary_skeleton(self, *, force: bool) -> None:
        if self._summary_reveal_anim is not None:
            self._summary_reveal_anim.stop()
            self._summary_reveal_anim = None
        self.summary_reveal_overlay.hide()
        self.summary.setMarkdown(self._last_summary_markdown)
        if force:
            self.summary_skeleton.start()
            self.summary_stack.setCurrentWidget(self.summary_skeleton)
            return
        self.summary_skeleton.stop()
        self.summary_stack.setCurrentWidget(self.summary_container)

    def _show_summary_result(self, markdown: str, token: int) -> None:
        if token != self._summary_token:
            return
        cleaned = (markdown or "").strip()
        if cleaned:
            self._last_summary_markdown = cleaned
        self.summary_skeleton.stop()
        self.summary.setMarkdown(self._last_summary_markdown)
        bar = self.summary.verticalScrollBar()
        if bar is not None:
            bar.setValue(bar.maximum())
        animate_reveal = self.summary_stack.currentWidget() is self.summary_skeleton
        self.summary_stack.setCurrentWidget(self.summary_container)
        if animate_reveal:
            self._start_summary_reveal()
            return
        self._animate_summary_scroll_to_top()

    def _start_summary_reveal(self) -> None:
        self.summary_reveal_overlay.setGeometry(self.summary_stack_host.rect())
        self.summary_reveal_overlay.raise_()
        self.summary_reveal_overlay.setPixmap(self.summary_container.grab())
        self.summary_reveal_overlay.setProgress(0.0)
        self.summary_reveal_overlay.show()

        animation = QPropertyAnimation(self.summary_reveal_overlay, b"progress", self)
        animation.setDuration(620)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)

        def _finish() -> None:
            self.summary_reveal_overlay.hide()
            self._summary_reveal_anim = None
            self._animate_summary_scroll_to_top()

        animation.finished.connect(_finish)
        animation.start()
        self._summary_reveal_anim = animation

    def _animate_summary_scroll_to_top(self) -> None:
        bar = self.summary.verticalScrollBar()
        if bar is None:
            return
        start = int(bar.value())
        if start <= 0:
            return
        if self._summary_scroll_anim is not None:
            self._summary_scroll_anim.stop()
        animation = QPropertyAnimation(bar, b"value", self)
        animation.setDuration(560)
        animation.setEasingCurve(QEasingCurve.InOutCubic)
        animation.setStartValue(start)
        animation.setEndValue(0)
        animation.start()
        self._summary_scroll_anim = animation

    def _on_link_clicked(self, url) -> None:
        link = url.toString().strip().lower()
        if link == "export":
            self._export_account_flow()
            return
        if link == "delete":
            self._delete_account_flow()
            return
        if link == "change":
            self._change_account_flow()
            return
        if link == "new":
            self._new_account_flow()
            return

    def _export_account_flow(self) -> bool:
        try:
            temp_zip = self.session_controller.create_temp_export()
        except Exception as exc:
            QMessageBox.warning(self, "Export account", str(exc))
            return False
        msg = QMessageBox(self)
        msg.setWindowTitle("Export account")
        msg.setText("We have made a copy of your data. Where would you like to save it?")
        choose_btn = msg.addButton("I will choose", QMessageBox.AcceptRole)
        downloads_btn = msg.addButton("Downloads folder", QMessageBox.AcceptRole)
        cancel_btn = msg.addButton("Cancel", QMessageBox.RejectRole)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked == cancel_btn:
            self._cleanup_temp_export(temp_zip)
            return False

        destination: Path | None = None
        if clicked == downloads_btn:
            destination = Path.home() / "Downloads" / temp_zip.name
        elif clicked == choose_btn:
            filename, _ = QFileDialog.getSaveFileName(self, "Save exported account", temp_zip.name, "Zip files (*.zip)")
            if not filename:
                self._cleanup_temp_export(temp_zip)
                return False
            destination = Path(filename)
        if destination is None:
            self._cleanup_temp_export(temp_zip)
            return False

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(temp_zip, destination)
        except Exception as exc:
            QMessageBox.warning(self, "Export account", f"Could not save export: {exc}")
            self._cleanup_temp_export(temp_zip)
            return False
        self._cleanup_temp_export(temp_zip)
        QMessageBox.information(self, "Export account", f"Account copy saved:\n{destination}")
        return True

    @staticmethod
    def _cleanup_temp_export(path: Path) -> None:
        parent = path.parent
        path.unlink(missing_ok=True)
        shutil.rmtree(parent, ignore_errors=True)

    def _delete_account_flow(self) -> None:
        for step in range(1, 5):
            answer = QMessageBox.question(
                self,
                "Delete account",
                f"Your local account will be delete forever. Are you sure? [{step}/4]",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if answer != QMessageBox.Yes:
                return

        final = QMessageBox(self)
        final.setWindowTitle("Delete account")
        final.setText("Got it! We will delete your data for you. Would you like to create a copy of your account before you do that?")
        copy_btn = final.addButton("Okay!", QMessageBox.AcceptRole)
        delete_btn = final.addButton("permentantly delete my data", QMessageBox.DestructiveRole)
        cancel_btn = final.addButton("Cancel", QMessageBox.RejectRole)
        final.exec()
        clicked = final.clickedButton()
        if clicked == cancel_btn:
            return
        if clicked == copy_btn:
            if not self._export_account_flow():
                return
        try:
            outcome = self.session_controller.delete_current_account()
        except Exception as exc:
            QMessageBox.warning(self, "Delete account", str(exc))
            return
        if outcome == "quit":
            self.close()
            return
        self.close()

    def _change_account_flow(self) -> None:
        for _ in range(3):
            confirm = QMessageBox(self)
            confirm.setWindowTitle("Change account")
            confirm.setText(
                "Changin the account will delete your data and overwrite it with the data given by the user. please confirm this message 3 times"
            )
            ok_btn = confirm.addButton("okay", QMessageBox.AcceptRole)
            cancel_btn = confirm.addButton("cancel", QMessageBox.RejectRole)
            confirm.exec()
            if confirm.clickedButton() != ok_btn:
                return

        ready = QMessageBox(self)
        ready.setWindowTitle("Change account")
        ready.setText(
            "Got it! After you import your data from the other account, we will delete the in-app data and overwrite it with your new account"
        )
        okay_btn = ready.addButton("Okay", QMessageBox.AcceptRole)
        cancel_btn = ready.addButton("Cancel", QMessageBox.RejectRole)
        ready.exec()
        if ready.clickedButton() != okay_btn:
            return

        archive_file, _ = QFileDialog.getOpenFileName(self, "Import account zip", "", "Zip files (*.zip)")
        if not archive_file:
            return
        try:
            self.session_controller.import_archive_into_current(Path(archive_file))
        except Exception as exc:
            QMessageBox.warning(self, "Change account", str(exc))
            return
        QMessageBox.information(self, "Change account", "Account data was imported and overwritten successfully.")
        self.close()

    def _new_account_flow(self) -> None:
        name = str(self.profile.get("name", "")).strip() or "Student"
        first = QMessageBox(self)
        first.setWindowTitle("New account")
        first.setText(
            f"Hey, {name}. It is nice to see you making another account. Creating a new account won't affect any of your existing account(s). you can change it anytime by pressing on the app icon > pressing accounts > and pressing on your prefered account"
        )
        yes_btn = first.addButton("yes, I am in!", QMessageBox.AcceptRole)
        cancel_btn = first.addButton("cancel", QMessageBox.RejectRole)
        first.exec()
        if first.clickedButton() != yes_btn:
            return

        second = QMessageBox(self)
        second.setWindowTitle("New account")
        second.setText("Nice! New account will be made. The app will open a new profile maker window for you to make a new account.")
        okay_btn = second.addButton("Okay", QMessageBox.AcceptRole)
        never_btn = second.addButton("nevermind, I changed my mind", QMessageBox.RejectRole)
        second.exec()
        if second.clickedButton() != okay_btn:
            return

        try:
            created = bool(self.session_controller.create_new_account_via_profile(self))
        except Exception as exc:
            QMessageBox.warning(self, "New account", str(exc))
            return
        if created:
            self.close()
