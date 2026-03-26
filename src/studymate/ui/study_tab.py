from __future__ import annotations

from datetime import datetime, timezone
import random
import uuid

from PySide6.QtCore import QEasingCurve, QEvent, QEventLoop, QPropertyAnimation, QThread, QTimer, Qt, Signal, QSize
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QProgressDialog,
    QScrollArea,
    QStackedWidget,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from studymate.constants import SUBJECT_TAXONOMY
from studymate.services.data_store import DataStore
from studymate.services.embedding_service import EmbeddingService
from studymate.services.ollama_service import OllamaService
from studymate.services.recommendation_service import (
    RecommendedCard,
    build_global_recommendations,
    recommendation_candidate_cards,
)
from studymate.services.study_intelligence import (
    StudySessionState,
    SessionCardEntry,
    build_session_state,
    card_cluster_key,
    enqueue_similar_cards,
    mark_card_completed,
    next_card_for_session,
    queue_reinforcement_cards,
    register_grade_result,
)
from studymate.ui.icon_helper import IconHelper
from studymate.ui.widgets.card_tile import CardTile
from studymate.workers.embedding_worker import EmbeddingWorker
from studymate.workers.followup_worker import FollowUpWorker
from studymate.workers.grade_worker import GradeWorker
from studymate.workers.reinforcement_worker import ReinforcementWorker


class PromptTextEdit(QTextEdit):
    submitted = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
            event.accept()
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class StartStudyDialog(QDialog):
    def __init__(self, path_label: str, count: int) -> None:
        super().__init__()
        self.setWindowTitle("Start study")
        self.setFixedSize(420, 220)

        layout = QVBoxLayout(self)
        title = QLabel("Start studying from this section?")
        title.setObjectName("SectionTitle")
        text = QLabel(f"Path: {path_label}\nCards available: {count}")
        text.setObjectName("SectionText")
        text.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(text, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancel")
        start = QPushButton("Start")
        start.setObjectName("PrimaryButton")
        cancel.clicked.connect(self.reject)
        start.clicked.connect(self.accept)
        actions.addWidget(cancel)
        actions.addWidget(start)
        layout.addLayout(actions)


class MoveCardDialog(QDialog):
    def __init__(self, card: dict, datastore: DataStore) -> None:
        super().__init__()
        self.card = card
        self.datastore = datastore
        self.selected_path = {
            "subject": card.get("subject", "Mathematics"),
            "category": card.get("category", "All"),
            "subtopic": card.get("subtopic", "All"),
        }

        self.setWindowTitle("Move card")
        self.setFixedSize(520, 620)

        layout = QVBoxLayout(self)
        title = QLabel("Choose the new subject path for this card.")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Subject path"])
        self.tree.itemClicked.connect(self._select_path)
        layout.addWidget(self.tree, 1)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        cancel = QPushButton("Cancel")
        move = QPushButton("Move")
        move.setObjectName("PrimaryButton")
        cancel.clicked.connect(self.reject)
        move.clicked.connect(self._move)
        action_row.addWidget(cancel)
        action_row.addWidget(move)
        layout.addLayout(action_row)

        self._build_tree()

    def _build_tree(self) -> None:
        for subject, details in SUBJECT_TAXONOMY.items():
            subject_item = QTreeWidgetItem([subject])
            subject_item.setData(0, Qt.UserRole, {"subject": subject, "category": "All", "subtopic": "All"})
            self.tree.addTopLevelItem(subject_item)

            all_item = QTreeWidgetItem([f"{subject} / All"])
            all_item.setData(0, Qt.UserRole, {"subject": subject, "category": "All", "subtopic": "All"})
            subject_item.addChild(all_item)

            for category in details.get("core", []):
                category_item = QTreeWidgetItem([f"{subject} / {category}"])
                category_item.setData(0, Qt.UserRole, {"subject": subject, "category": category, "subtopic": "All"})
                subject_item.addChild(category_item)
                for subtopic in details.get("subtopics", []):
                    sub_item = QTreeWidgetItem([f"{subject} / {category} / {subtopic}"])
                    sub_item.setData(
                        0,
                        Qt.UserRole,
                        {"subject": subject, "category": category, "subtopic": subtopic},
                    )
                    category_item.addChild(sub_item)
        self.tree.collapseAll()

    def _select_path(self, item: QTreeWidgetItem) -> None:
        self.selected_path = item.data(0, Qt.UserRole)

    def _move(self) -> None:
        result = self.datastore.move_card(
            self.card["id"],
            self.card.get("subject", "Mathematics"),
            self.selected_path["subject"],
            self.selected_path,
        )
        if result is None:
            QMessageBox.warning(self, "Move failed", "Could not move that card.")
            return
        self.accept()


class ReinforcementProgressDialog(QDialog):
    def __init__(self, icons: IconHelper) -> None:
        super().__init__()
        self.setWindowTitle("Preparing reinforcement")
        self.setFixedSize(460, 300)
        self.rows: dict[str, tuple[QLabel, QLabel]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        title = QLabel("Preparing reinforcement cards")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        subtitle = QLabel("ONCard is building a short targeted practice block for the weak topic.")
        subtitle.setObjectName("SectionText")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.status_label = QLabel("Waiting to start...")
        self.status_label.setObjectName("SmallMeta")
        layout.addWidget(self.status_label)

        self._done_icon = icons.icon("common", "complete_green_circle", "O").pixmap(18, 18)
        self._pending_icon = icons.icon("common", "pending_red_circle", ".").pixmap(18, 18)

        for key, label_text in [
            ("creating", "Creating questions"),
            ("filling", "Filling cards"),
            ("embedding", "Embedding temporary cards"),
            ("adding", "Adding to session"),
        ]:
            row = QHBoxLayout()
            icon_label = QLabel()
            icon_label.setPixmap(self._pending_icon)
            text_label = QLabel(label_text)
            text_label.setObjectName("SectionText")
            row.addWidget(icon_label)
            row.addWidget(text_label, 1)
            layout.addLayout(row)
            self.rows[key] = (icon_label, text_label)

    def update_step(self, key: str, message: str, done: bool) -> None:
        self.status_label.setText(message)
        row = self.rows.get(key)
        if row is None:
            return
        icon_label, _text_label = row
        icon_label.setPixmap(self._done_icon if done else self._pending_icon)


class SessionPrepDialog(QDialog):
    def __init__(self, icons: IconHelper) -> None:
        super().__init__()
        self.setWindowTitle("Preparing study session")
        self.setFixedSize(460, 308)
        self.rows: dict[str, tuple[QLabel, QLabel]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        title = QLabel("Preparing your study session")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        subtitle = QLabel("ONCard is getting the next study block ready.")
        subtitle.setObjectName("SectionText")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.status_label = QLabel("Waiting to start...")
        self.status_label.setObjectName("SmallMeta")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        self._done_icon = icons.icon("common", "complete_green_circle", "O").pixmap(18, 18)
        self._pending_icon = icons.icon("common", "pending_red_circle", ".").pixmap(18, 18)

        for key, label_text in [
            ("seed", "Preparing seed cards"),
            ("topics", "Building topic links"),
            ("launch", "Starting study"),
        ]:
            row = QHBoxLayout()
            icon_label = QLabel()
            icon_label.setPixmap(self._pending_icon)
            text_label = QLabel(label_text)
            text_label.setObjectName("SectionText")
            row.addWidget(icon_label)
            row.addWidget(text_label, 1)
            layout.addLayout(row)
            self.rows[key] = (icon_label, text_label)

    def update_step(self, key: str, message: str, done: bool) -> None:
        self.status_label.setText(message)
        row = self.rows.get(key)
        if row is None:
            return
        icon_label, _text_label = row
        icon_label.setPixmap(self._done_icon if done else self._pending_icon)

    def set_progress(self, value: int) -> None:
        self.progress_bar.setValue(max(0, min(100, int(value))))


class SessionPrepWorker(QThread):
    progress = Signal(str, str, str, int, int, bool)
    finished = Signal(str, object)
    failed = Signal(str, str)

    def __init__(
        self,
        *,
        session_id: str,
        cards: list[dict],
        seed_cards: list[dict],
        embedding_service: EmbeddingService,
    ) -> None:
        super().__init__()
        self.session_id = session_id
        self.cards = list(cards)
        self.seed_cards = list(seed_cards)
        self.embedding_service = embedding_service

    def run(self) -> None:
        try:
            total_seed = max(1, len(self.seed_cards))
            if not self.seed_cards:
                self.progress.emit(self.session_id, "seed", "Seed cards already had embeddings.", 1, 1, True)
            else:
                self.progress.emit(self.session_id, "seed", "Checking seed card embeddings...", 0, total_seed, False)
                for index, card in enumerate(self.seed_cards, start=1):
                    if self.isInterruptionRequested():
                        return
                    label = str(card.get("title") or card.get("question") or "Card").strip() or "Card"
                    self.progress.emit(
                        self.session_id,
                        "seed",
                        f"Embedding seed cards... ({index}/{total_seed}) {label}",
                        index,
                        total_seed,
                        False,
                    )
                    self.embedding_service.ensure_card_embedding(card)
                    self.msleep(25)
                self.progress.emit(self.session_id, "seed", "Seed cards are ready.", total_seed, total_seed, True)

            if self.isInterruptionRequested():
                return
            self.progress.emit(self.session_id, "topics", "Building topic links from the seed set...", 0, 1, False)
            cluster_map = self.embedding_service.topic_clusters(self.cards)
            if self.isInterruptionRequested():
                return
            self.progress.emit(self.session_id, "topics", "Topic links are ready.", 1, 1, True)
            self.progress.emit(self.session_id, "launch", "Study session ready.", 1, 1, True)
            self.finished.emit(self.session_id, cluster_map)
        except Exception as exc:
            self.failed.emit(self.session_id, str(exc))


class TopicClusterWorker(QThread):
    finished = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, *, session_id: str, cards: list[dict], embedding_service: EmbeddingService) -> None:
        super().__init__()
        self.session_id = session_id
        self.cards = list(cards)
        self.embedding_service = embedding_service

    def run(self) -> None:
        try:
            cluster_map = self.embedding_service.topic_clusters(self.cards)
            if self.isInterruptionRequested():
                return
            self.finished.emit(self.session_id, cluster_map)
        except Exception as exc:
            self.failed.emit(self.session_id, str(exc))


class CardSearchWorker(QThread):
    finished = Signal(int, str, object)

    def __init__(self, *, request_id: int, query: str, cards: list[dict], embedding_service: EmbeddingService, limit: int) -> None:
        super().__init__()
        self.request_id = request_id
        self.query = query
        self.cards = list(cards)
        self.embedding_service = embedding_service
        self.limit = limit

    def run(self) -> None:
        query = self.query.strip()
        if not query:
            self.finished.emit(self.request_id, query, [])
            return
        scored: list[dict] = []
        try:
            semantic = self.embedding_service.search_cards_by_text(query, self.cards, max_results=self.limit)
            scored = [{"card": item.card, "score": float(item.score), "source": "semantic"} for item in semantic]
        except Exception:
            scored = []
        if not scored:
            fallback = StudyTab._fallback_text_search(query, self.cards)[: self.limit]
            scored = [{"card": card, "score": 0.0, "source": "fallback"} for card in fallback]
        self.finished.emit(self.request_id, query, scored)


class StudyTab(QWidget):
    def __init__(self, datastore: DataStore, ollama: OllamaService, icons: IconHelper) -> None:
        super().__init__()
        self.datastore = datastore
        self.ollama = ollama
        self.icons = icons
        self.current_subject = "All Subjects"
        self.current_category = "All"
        self.current_subtopic = "All"
        self.cards: list[dict] = []
        self.current_card: dict | None = None
        self.embedding_service = EmbeddingService(datastore, ollama)
        self.study_state: StudySessionState | None = None
        self.session_id = ""
        self.session_queue: list[dict] = []
        self.session_cards: list[dict] = []
        self.session_scores: list[float] = []
        self.session_temp_batches: dict[str, dict] = {}
        self.current_attempt_logged = False
        self.revealed_hints = 0
        self.hint_cooldown = 0
        self.sidebar_expanded = True
        self.grade_worker: GradeWorker | None = None
        self.followup_worker: FollowUpWorker | None = None
        self.embedding_worker: EmbeddingWorker | None = None
        self.reinforcement_worker: ReinforcementWorker | None = None
        self.session_prep_worker: SessionPrepWorker | None = None
        self.topic_cluster_worker: TopicClusterWorker | None = None
        self.card_search_worker: CardSearchWorker | None = None
        self.session_prep_dialog: SessionPrepDialog | None = None
        self.session_prep_remaining_cards: list[dict] = []
        self.pending_cluster_refresh = False
        self.last_grade_report: dict | None = None
        self.card_search_query = ""
        self.card_search_suggestions: list[dict] = []
        self.card_search_full_results: list[dict] = []
        self.card_search_result_limit = 20
        self.card_search_last_scores: list[float] = []
        self.card_search_has_executed = False
        self.card_search_request_id = 0
        self.card_search_no_close_match = False
        self.global_recommendations: list[RecommendedCard] = []
        self._card_search_animations: list[QPropertyAnimation] = []
        self._card_search_workers: list[CardSearchWorker] = []

        self.cooldown_timer = QTimer(self)
        self.cooldown_timer.timeout.connect(self._tick_hint_cooldown)
        self.card_search_timer = QTimer(self)
        self.card_search_timer.setSingleShot(True)
        self.card_search_timer.timeout.connect(self._request_card_suggestions)
        self.card_layout_timer = QTimer(self)
        self.card_layout_timer.setSingleShot(True)
        self.card_layout_timer.timeout.connect(self._render_cards)

        self._build_ui()
        self.reload_cards()

    def _surface(self, sidebar: bool = False) -> QFrame:
        frame = QFrame()
        frame.setObjectName("SidebarSurface" if sidebar else "Surface")
        return frame

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)

        self.sidebar = self._surface(sidebar=True)
        self.sidebar.setMinimumWidth(280)
        self.sidebar.setMaximumWidth(280)
        side_layout = QVBoxLayout(self.sidebar)
        side_layout.setContentsMargins(16, 18, 16, 18)
        side_layout.setSpacing(12)

        side_head = QHBoxLayout()
        title = QLabel("Subjects")
        title.setObjectName("SectionTitle")
        self.collapse_btn = QToolButton()
        self.collapse_btn.setObjectName("CollapseButton")
        self.collapse_btn.setText("<")
        self.collapse_btn.clicked.connect(self._toggle_sidebar)
        side_head.addWidget(title)
        side_head.addStretch(1)
        side_head.addWidget(self.collapse_btn)
        side_layout.addLayout(side_head)

        self.subject_tree = QTreeWidget()
        self.subject_tree.setHeaderHidden(True)
        self.subject_tree.setRootIsDecorated(False)
        self.subject_tree.setIndentation(0)
        self.subject_tree.setUniformRowHeights(True)
        self.subject_tree.itemClicked.connect(self._subject_clicked)
        side_layout.addWidget(self.subject_tree, 1)
        root.addWidget(self.sidebar)

        content = QVBoxLayout()
        content.setSpacing(14)

        subnav = QHBoxLayout()
        self.cards_sub_btn = QPushButton("Cards")
        self.cards_sub_btn.setObjectName("TopNavButton")
        self.cards_sub_btn.setCheckable(True)
        self.cards_sub_btn.setChecked(True)
        self.study_sub_btn = QPushButton("Study")
        self.study_sub_btn.setObjectName("TopNavButton")
        self.study_sub_btn.setCheckable(True)
        self.cards_sub_btn.clicked.connect(lambda: self._switch_mode(0))
        self.study_sub_btn.clicked.connect(lambda: self._switch_mode(1))
        subnav.addWidget(self.cards_sub_btn)
        subnav.addWidget(self.study_sub_btn)
        subnav.addStretch(1)
        content.addLayout(subnav)

        self.mode_stack = QStackedWidget()
        self.cards_view = self._build_cards_view()
        self.study_view = self._build_study_view()
        self.mode_stack.addWidget(self.cards_view)
        self.mode_stack.addWidget(self.study_view)
        content.addWidget(self.mode_stack, 1)

        root.addLayout(content, 1)

    def _build_cards_view(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        search_bar = self._surface()
        search_layout = QHBoxLayout(search_bar)
        search_layout.setContentsMargins(14, 12, 14, 12)
        search_layout.setSpacing(10)

        self.card_search_input = QLineEdit()
        self.card_search_input.setPlaceholderText("Search cards semantically...")
        self.card_search_input.textChanged.connect(self._queue_card_search)
        self.card_search_input.returnPressed.connect(self._execute_card_search)
        self.card_search_input.setTextMargins(0, 0, 36, 0)
        self.card_search_input.installEventFilter(self)
        self.card_search_btn = QToolButton(self.card_search_input)
        self.card_search_btn.setIcon(self._build_search_icon())
        self.card_search_btn.setIconSize(QSize(18, 18))
        self.card_search_btn.setCursor(Qt.PointingHandCursor)
        self.card_search_btn.setStyleSheet("QToolButton { border: none; background: transparent; padding: 0px; }")
        self.card_search_btn.setFixedSize(24, 24)
        self.card_search_btn.setToolTip("Search")
        self.card_search_btn.clicked.connect(self._execute_card_search)
        search_layout.addWidget(self.card_search_input, 1)
        self._position_card_search_button()

        self.start_cards_btn = QPushButton("Start")
        self.start_cards_btn.clicked.connect(self._open_start_dialog)
        search_layout.addWidget(self.start_cards_btn)
        self.refresh_cards_btn = QPushButton("Refresh")
        self.refresh_cards_btn.clicked.connect(self.reload_cards)
        search_layout.addWidget(self.refresh_cards_btn)
        layout.addWidget(search_bar)

        self.card_search_dropdown = self._surface()
        self.card_search_dropdown.setVisible(False)
        dropdown_layout = QVBoxLayout(self.card_search_dropdown)
        dropdown_layout.setContentsMargins(10, 10, 10, 10)
        dropdown_layout.setSpacing(6)
        self.card_search_label = QLabel("Did you mean something like:")
        self.card_search_label.setObjectName("SmallMeta")
        dropdown_layout.addWidget(self.card_search_label)
        self.card_search_list = QListWidget()
        self.card_search_list.itemClicked.connect(self._card_search_suggestion_clicked)
        self.card_search_list.itemPressed.connect(self._card_search_suggestion_clicked)
        self.card_search_list.itemActivated.connect(self._card_search_suggestion_clicked)
        dropdown_layout.addWidget(self.card_search_list)
        layout.addWidget(self.card_search_dropdown)

        self.cards_surface = self._surface()
        cards_layout = QVBoxLayout(self.cards_surface)
        cards_layout.setContentsMargins(18, 18, 18, 18)
        cards_layout.setSpacing(12)
        self.card_scroll = QScrollArea()
        self.card_scroll.setWidgetResizable(True)
        self.card_scroll.viewport().installEventFilter(self)
        self.card_host = QWidget()
        self.card_host.setObjectName("CardsCanvas")
        self.card_host_layout = QVBoxLayout(self.card_host)
        self.card_host_layout.setContentsMargins(0, 0, 0, 0)
        self.card_host_layout.setSpacing(0)
        self.recommendation_block = self._surface()
        self.recommendation_block.setObjectName("RecommendationBlock")
        recommendation_layout = QVBoxLayout(self.recommendation_block)
        recommendation_layout.setContentsMargins(18, 18, 18, 18)
        recommendation_layout.setSpacing(12)
        self.recommendation_title = QLabel("Our recommendation")
        self.recommendation_title.setObjectName("RecommendationTitle")
        recommendation_layout.addWidget(self.recommendation_title)
        self.recommendation_meta = QLabel(
            "According your past interactions, you will benefit from learning these first"
        )
        self.recommendation_meta.setObjectName("RecommendationMeta")
        self.recommendation_meta.setWordWrap(True)
        recommendation_layout.addWidget(self.recommendation_meta)
        self.recommendation_host = QWidget()
        self.recommendation_grid = QGridLayout(self.recommendation_host)
        self.recommendation_grid.setContentsMargins(0, 0, 0, 0)
        self.recommendation_grid.setHorizontalSpacing(16)
        self.recommendation_grid.setVerticalSpacing(16)
        self.recommendation_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        recommendation_layout.addWidget(self.recommendation_host)
        self.recommendation_block.hide()
        self.card_host_layout.addWidget(self.recommendation_block)
        self.card_grid_host = QWidget()
        self.card_grid_host.setObjectName("CardsCanvas")
        self.card_grid = QGridLayout(self.card_grid_host)
        self.card_grid.setContentsMargins(0, 14, 0, 0)
        self.card_grid.setHorizontalSpacing(20)
        self.card_grid.setVerticalSpacing(18)
        self.card_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.card_host_layout.addWidget(self.card_grid_host)
        self.card_scroll.setWidget(self.card_host)
        cards_layout.addWidget(self.card_scroll)
        self.card_empty_state = QWidget()
        empty_layout = QVBoxLayout(self.card_empty_state)
        empty_layout.setContentsMargins(56, 40, 56, 40)
        empty_layout.setSpacing(18)
        empty_layout.setAlignment(Qt.AlignCenter)
        self.card_empty_image = QLabel()
        self.card_empty_image.setAlignment(Qt.AlignCenter)
        self.card_empty_title = QLabel("Try another search")
        self.card_empty_title.setObjectName("PageTitle")
        self.card_empty_title.setAlignment(Qt.AlignCenter)
        self.card_empty_note = QLabel("Use a more direct topic, keyword, or idea from the card.")
        self.card_empty_note.setObjectName("SectionText")
        self.card_empty_note.setAlignment(Qt.AlignCenter)
        self.card_empty_note.setWordWrap(True)
        self.card_empty_note.setMaximumWidth(520)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.card_empty_image)
        empty_layout.addWidget(self.card_empty_title)
        empty_layout.addWidget(self.card_empty_note)
        empty_layout.addStretch(1)
        self.card_empty_state.hide()
        cards_layout.addWidget(self.card_empty_state)
        self.card_search_more_btn = QPushButton("See more")
        self.card_search_more_btn.clicked.connect(self._show_more_search_results)
        self.card_search_more_btn.hide()
        cards_layout.addWidget(self.card_search_more_btn, 0, Qt.AlignHCenter)
        layout.addWidget(self.cards_surface, 1)
        return container

    def _build_search_icon(self) -> QIcon:
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor("#111111"))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawEllipse(4, 4, 11, 11)
        painter.drawLine(14, 14, 20, 20)
        painter.end()
        return QIcon(pixmap)

    def _build_study_view(self) -> QWidget:
        container = QWidget()
        root = QHBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        left_surface = self._surface()
        left_layout = QVBoxLayout(left_surface)
        left_layout.setContentsMargins(18, 18, 18, 18)
        left_layout.setSpacing(12)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self._open_start_dialog)
        self.refresh_study_btn = QPushButton("Refresh")
        self.refresh_study_btn.clicked.connect(self.reload_cards)
        actions.addWidget(self.start_btn)
        actions.addWidget(self.refresh_study_btn)
        left_layout.addLayout(actions)

        self.session_title = QLabel("Pick a card to start")
        self.session_title.setObjectName("PageTitle")
        self.session_meta = QLabel("")
        self.session_meta.setObjectName("SmallMeta")
        self.session_question = QLabel("Use the Cards subtab or press Start for the current section.")
        self.session_question.setObjectName("SectionText")
        self.session_question.setWordWrap(True)
        self.session_question.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.answer_input = QTextEdit()
        self.answer_input.setPlaceholderText("Write your answer here...")
        self.answer_input.setMinimumHeight(180)

        hint_row = QHBoxLayout()
        self.hint_btn = QPushButton("Show hint")
        self.hint_btn.clicked.connect(self._show_hint)
        self.hint_status = QLabel("Hints stay hidden until you press Show hint.")
        self.hint_status.setObjectName("SmallMeta")
        hint_row.addWidget(self.hint_btn)
        hint_row.addWidget(self.hint_status, 1)

        self.hints_text = QTextEdit()
        self.hints_text.setReadOnly(True)
        self.hints_text.setFixedHeight(96)
        self.hints_text.setPlaceholderText("Hints will appear one by one.")

        button_row = QHBoxLayout()
        self.idk_btn = QPushButton("I don't know")
        self.idk_btn.clicked.connect(self._ask_i_dont_know)
        self.grade_btn = QPushButton("Grade")
        self.grade_btn.clicked.connect(self._grade)
        self.next_btn = QPushButton("Next")
        self.next_btn.clicked.connect(self._next_card)
        button_row.addWidget(self.idk_btn)
        button_row.addWidget(self.grade_btn)
        button_row.addWidget(self.next_btn)

        left_layout.addWidget(self.session_title)
        left_layout.addWidget(self.session_meta)
        left_layout.addWidget(self.session_question)
        left_layout.addWidget(self.answer_input, 1)
        left_layout.addLayout(hint_row)
        left_layout.addWidget(self.hints_text)
        left_layout.addLayout(button_row)

        right_surface = self._surface()
        right_surface.setMinimumWidth(360)
        right_surface.setMaximumWidth(420)
        right_layout = QVBoxLayout(right_surface)
        right_layout.setContentsMargins(18, 18, 18, 18)
        right_layout.setSpacing(12)

        self.grade_summary = QLabel("AI grader")
        self.grade_summary.setObjectName("PageTitle")
        self.grade_feedback = QTextBrowser()
        self.grade_feedback.setMinimumHeight(280)

        self.followup_title = QLabel("Follow up on this card")
        self.followup_title.setObjectName("SectionTitle")
        self.followup_title.hide()
        self.followup_input = PromptTextEdit()
        self.followup_input.setPlaceholderText("Ask about your question")
        self.followup_input.setMinimumHeight(120)
        self.followup_input.submitted.connect(self._run_followup)
        self.followup_input.hide()
        self.followup_btn = QPushButton("Ask follow up")
        self.followup_btn.clicked.connect(self._run_followup)
        self.followup_btn.hide()

        right_layout.addWidget(self.grade_summary)
        right_layout.addWidget(self.grade_feedback, 1)
        right_layout.addWidget(self.followup_title)
        right_layout.addWidget(self.followup_input)
        right_layout.addWidget(self.followup_btn)

        root.addWidget(left_surface, 2)
        root.addWidget(right_surface, 1)
        return container

    def _switch_mode(self, index: int) -> None:
        self.mode_stack.setCurrentIndex(index)
        self.cards_sub_btn.setChecked(index == 0)
        self.study_sub_btn.setChecked(index == 1)

    def _toggle_sidebar(self) -> None:
        self.sidebar_expanded = not self.sidebar_expanded
        width = 280 if self.sidebar_expanded else 88
        self.sidebar.setMinimumWidth(width)
        self.sidebar.setMaximumWidth(width)
        self.subject_tree.setVisible(self.sidebar_expanded)
        self.collapse_btn.setText("<" if self.sidebar_expanded else ">")

    def eventFilter(self, watched, event) -> bool:
        if hasattr(self, "card_scroll") and watched is self.card_scroll.viewport() and event.type() == QEvent.Resize:
            self.card_layout_timer.start(60)
        elif watched is self.card_search_input and event.type() == QEvent.Resize:
            self._position_card_search_button()
        return super().eventFilter(watched, event)

    def _position_card_search_button(self) -> None:
        if not hasattr(self, "card_search_btn") or not hasattr(self, "card_search_input"):
            return
        x_pos = self.card_search_input.width() - self.card_search_btn.width() - 10
        y_pos = max(0, int((self.card_search_input.height() - self.card_search_btn.height()) / 2))
        self.card_search_btn.move(x_pos, y_pos)

    def reload_cards(self) -> None:
        self.cards = self.datastore.list_all_cards()
        self._refresh_global_recommendations()
        self.card_search_dropdown.setVisible(False)
        self._refresh_subjects()
        self._render_cards()

    def _refresh_subjects(self) -> None:
        counts = self.datastore.card_counts_by_subject()
        self.subject_tree.clear()

        all_item = QTreeWidgetItem(["All Subjects"])
        all_item.setData(0, Qt.UserRole, {"subject": "All Subjects", "category": "All", "subtopic": "All"})
        self.subject_tree.addTopLevelItem(all_item)

        for subject, details in SUBJECT_TAXONOMY.items():
            subject_item = QTreeWidgetItem([f"{subject} ({counts.get(subject, 0)})"])
            subject_item.setData(0, Qt.UserRole, {"subject": subject, "category": "All", "subtopic": "All"})
            if counts.get(subject, 0) == 0:
                subject_item.setForeground(0, QColor("#8f8f8f"))
            self.subject_tree.addTopLevelItem(subject_item)
            for category in details.get("core", []):
                category_item = QTreeWidgetItem([category])
                category_item.setData(
                    0,
                    Qt.UserRole,
                    {"subject": subject, "category": category, "subtopic": "All"},
                )
                subject_item.addChild(category_item)
                for subtopic in details.get("subtopics", []):
                    subtopic_item = QTreeWidgetItem([subtopic])
                    subtopic_item.setData(
                        0,
                        Qt.UserRole,
                        {"subject": subject, "category": category, "subtopic": subtopic},
                    )
                    category_item.addChild(subtopic_item)
        self.subject_tree.collapseAll()
        self.subject_tree.setCurrentItem(all_item)

    def _current_path_label(self) -> str:
        parts = []
        if self.current_subject != "All Subjects":
            parts.append(self.current_subject)
        if self.current_category != "All":
            parts.append(self.current_category)
        if self.current_subtopic != "All":
            parts.append(self.current_subtopic)
        return " / ".join(parts) if parts else "All Subjects"

    def _subject_clicked(self, item: QTreeWidgetItem) -> None:
        payload = item.data(0, Qt.UserRole) or {"subject": "All Subjects", "category": "All", "subtopic": "All"}
        self.current_subject = payload["subject"]
        self.current_category = payload["category"]
        self.current_subtopic = payload.get("subtopic", "All")
        self.card_search_dropdown.setVisible(False)
        self._render_cards()

    def _clear_grid(self) -> None:
        while self.card_grid.count():
            child = self.card_grid.takeAt(0)
            widget = child.widget()
            if widget:
                widget.deleteLater()

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            child = layout.takeAt(0)
            widget = child.widget()
            if widget:
                widget.deleteLater()

    def _filtered_cards(self) -> list[dict]:
        filtered = list(self.cards)
        if self.current_subject != "All Subjects":
            filtered = [card for card in filtered if card.get("subject") == self.current_subject]
        if self.current_category != "All":
            filtered = [card for card in filtered if card.get("category") == self.current_category]
        if self.current_subtopic != "All":
            filtered = [card for card in filtered if card.get("subtopic") == self.current_subtopic]
        return filtered

    def _queue_card_search(self, text: str) -> None:
        self.card_search_query = text
        self.card_search_has_executed = False if not text.strip() else self.card_search_has_executed
        self.card_search_dropdown.setVisible(False)
        self.card_search_suggestions = []
        if not text.strip():
            self.card_search_full_results = []
            self.card_search_last_scores = []
            self.card_search_no_close_match = False
            self.card_search_more_btn.hide()
            self._render_cards()
            return
        self.card_search_timer.start(1000)

    def _request_card_suggestions(self) -> None:
        query = self.card_search_input.text().strip()
        if not query:
            return
        cards = self._filtered_cards()
        if not cards:
            self.card_search_dropdown.setVisible(False)
            return
        suggestions = self._fast_card_suggestions(query, cards, limit=5)
        self._on_card_suggestions_ready(self.card_search_request_id, query, suggestions)

    def _on_card_suggestions_ready(self, request_id: int, query: str, scored: object) -> None:
        if request_id != self.card_search_request_id:
            return
        if query != self.card_search_input.text().strip():
            return
        scored_items = scored if isinstance(scored, list) else []
        self.card_search_suggestions = [item.get("card", {}) for item in scored_items if isinstance(item, dict)]
        self.card_search_list.clear()
        for item in scored_items[:5]:
            if not isinstance(item, dict):
                continue
            card = item.get("card", {})
            title = str(card.get("title", "Untitled")).strip() or "Untitled"
            short_title = title if len(title) <= 200 else f"{title[:197]}..."
            row = QListWidgetItem(short_title)
            row.setToolTip(title)
            row.setData(Qt.UserRole, card)
            self.card_search_list.addItem(row)
        has_items = self.card_search_list.count() > 0 and bool(query)
        self.card_search_dropdown.setVisible(has_items)

    def _card_search_suggestion_clicked(self, item: QListWidgetItem) -> None:
        card = item.data(Qt.UserRole) or {}
        title = str(card.get("title", "")).strip()
        if title:
            self.card_search_input.setText(title)
        self._execute_card_search()

    def _execute_card_search(self) -> None:
        query = self.card_search_input.text().strip()
        self.card_search_dropdown.setVisible(False)
        if not query:
            self.card_search_query = ""
            self.card_search_has_executed = False
            self.card_search_full_results = []
            self.card_search_last_scores = []
            self.card_search_no_close_match = False
            self.card_search_more_btn.hide()
            self._render_cards()
            return

        cards = self._filtered_cards()
        self.card_search_query = query
        self.card_search_has_executed = True
        self.card_search_result_limit = 20
        scored_items: list[dict] = []
        try:
            semantic = self.embedding_service.search_cards_by_text(query, cards, max_results=max(20, len(cards)))
            scored_items = [{"card": item.card, "score": float(item.score), "source": "semantic"} for item in semantic]
        except Exception:
            scored_items = []
        if not scored_items:
            fallback = self._fallback_text_search(query, cards)
            scored_items = [{"card": card, "score": 0.0, "source": "fallback"} for card in fallback]

        self.card_search_full_results = [item["card"] for item in scored_items]
        self.card_search_last_scores = [float(item.get("score", 0.0)) for item in scored_items]
        best_score = self.card_search_last_scores[0] if self.card_search_last_scores else 0.0
        self.card_search_no_close_match = bool(cards) and best_score < 0.22
        self._render_cards()

    def _show_more_search_results(self) -> None:
        self.card_search_result_limit += 20
        self._render_cards()

    def _cleanup_card_search_worker(self, worker: CardSearchWorker) -> None:
        if worker in self._card_search_workers:
            self._card_search_workers.remove(worker)
        if self.card_search_worker is worker:
            self.card_search_worker = None

    @staticmethod
    def _fallback_text_search(query: str, cards: list[dict]) -> list[dict]:
        terms = [term for term in query.lower().split() if term]
        if not terms:
            return []

        def score(card: dict) -> tuple[int, int]:
            haystack = " ".join(
                [
                    str(card.get("title", "")).lower(),
                    str(card.get("question", "")).lower(),
                    str(card.get("answer", "")).lower(),
                ]
            )
            matches = sum(1 for term in terms if term in haystack)
            return matches, len(haystack)

        return sorted(cards, key=score, reverse=True)

    @staticmethod
    def _fast_card_suggestions(query: str, cards: list[dict], limit: int = 5) -> list[dict]:
        terms = [term for term in query.lower().split() if term]
        if not terms:
            return []

        scored: list[tuple[tuple[int, int, int, int], dict]] = []
        for card in cards:
            title = str(card.get("title", "")).strip()
            title_lower = title.lower()
            question_lower = str(card.get("question", "")).lower()
            answer_lower = str(card.get("answer", "")).lower()
            prefix_hits = sum(1 for term in terms if title_lower.startswith(term))
            title_hits = sum(1 for term in terms if term in title_lower)
            content_hits = sum(1 for term in terms if term in question_lower or term in answer_lower)
            if prefix_hits == 0 and title_hits == 0 and content_hits == 0:
                continue
            scored.append(((prefix_hits, title_hits, content_hits, -len(title_lower)), card))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [{"card": card, "score": 0.0, "source": "fast"} for _score, card in scored[:limit]]

    def _is_global_all_view(self) -> bool:
        return (
            self.current_subject == "All Subjects"
            and self.current_category == "All"
            and self.current_subtopic == "All"
        )

    def _refresh_global_recommendations(self) -> None:
        if len(self.cards) <= 60:
            self.global_recommendations = []
            return
        attempts = self.datastore.load_attempts()
        self.global_recommendations = build_global_recommendations(
            self.cards,
            attempts,
            self.embedding_service,
            limit=10,
        )
        candidate_cards = recommendation_candidate_cards(self.cards, attempts)
        missing = [card for card in candidate_cards if not self.embedding_service.is_card_cached(card)]
        if missing:
            self._embed_remaining_cards_in_background(missing)

    def _render_recommendations(self) -> None:
        self._clear_layout(self.recommendation_grid)
        should_show = (
            not self.card_search_has_executed
            and self._is_global_all_view()
            and len(self.cards) > 60
            and bool(self.global_recommendations)
        )
        if not should_show:
            self.recommendation_block.hide()
            return

        visible_items = self.global_recommendations[:3]
        available_width = max(self.card_scroll.viewport().width() - 52, 320)
        spacing = self.recommendation_grid.horizontalSpacing() or 16
        min_width = 300
        max_width = 380
        columns = max(1, min(3, len(visible_items), available_width // min_width))
        tile_width = int((available_width - (spacing * max(columns - 1, 0))) / columns)
        while tile_width < min_width and columns > 1:
            columns -= 1
            tile_width = int((available_width - (spacing * max(columns - 1, 0))) / columns)
        tile_width = max(min_width, min(max_width, tile_width))

        for idx, item in enumerate(visible_items):
            tile = CardTile(item.card)
            tile.set_tile_width(tile_width)
            tile.setToolTip(f"Related strong match similarity: {item.reason_similarity:.2f}")
            tile.selected.connect(self._card_selected)
            tile.move_requested.connect(self._move_card)
            tile.remove_requested.connect(self._remove_card)
            row = idx // columns
            col = idx % columns
            self.recommendation_grid.addWidget(tile, row, col)
        self.recommendation_block.show()

    def _render_cards(self) -> None:
        self._clear_grid()
        self._render_recommendations()
        self.card_scroll.show()
        self.card_empty_state.hide()
        self.card_search_more_btn.hide()
        if self.card_search_has_executed:
            cards = self.card_search_full_results[: self.card_search_result_limit]
        else:
            cards = self._filtered_cards()

        if self.card_search_has_executed and self.card_search_no_close_match:
            self._show_card_empty_state()
            return
        if not cards:
            empty_text = "No cards in this section yet." if not self.card_search_has_executed else "No matching cards found."
            empty = QLabel(empty_text)
            empty.setObjectName("SectionText")
            empty.setAlignment(Qt.AlignCenter)
            self.card_grid.addWidget(empty, 0, 0, 1, 4)
            return

        available_width = max(self.card_scroll.viewport().width() - 8, 300)
        min_width = 320
        max_width = 460
        spacing = self.card_grid.horizontalSpacing() or 18
        columns = max(1, min(4, available_width // min_width))
        tile_width = int((available_width - (spacing * max(columns - 1, 0))) / columns)
        while tile_width < min_width and columns > 1:
            columns -= 1
            tile_width = int((available_width - (spacing * max(columns - 1, 0))) / columns)
        tile_width = max(min_width, min(max_width, tile_width))

        self._card_search_animations = []
        for idx, card in enumerate(cards):
            tile = CardTile(card)
            tile.set_tile_width(tile_width)
            tile.selected.connect(self._card_selected)
            tile.move_requested.connect(self._move_card)
            tile.remove_requested.connect(self._remove_card)
            row = idx // columns
            col = idx % columns
            self.card_grid.addWidget(tile, row, col)
            if self.card_search_has_executed:
                self._animate_card_tile(tile, idx)
        if self.card_search_has_executed and len(self.card_search_full_results) > len(cards):
            self.card_search_more_btn.show()

    def _show_card_empty_state(self) -> None:
        image_path = self.datastore.paths.banners / "cards_search_empty_1x1.png"
        self.card_scroll.hide()
        self.card_empty_state.setMinimumHeight(max(self.cards_surface.height() - 44, 520))
        if image_path.exists():
            pixmap = QPixmap(str(image_path))
            self.card_empty_image.setPixmap(pixmap.scaled(420, 420, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.card_empty_image.show()
        else:
            self.card_empty_image.hide()
        self.card_empty_title.setText("Try another search")
        self.card_empty_note.setText("Use a more direct topic, keyword, or idea from the card.")
        self.card_empty_state.show()

    def _animate_card_tile(self, tile: QWidget, index: int) -> None:
        effect = QGraphicsOpacityEffect(tile)
        effect.setOpacity(0.0)
        tile.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", tile)
        animation.setDuration(760)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutQuart)
        self._card_search_animations.append(animation)
        QTimer.singleShot(index * 190, animation.start)

    def _move_card(self, card: dict) -> None:
        dialog = MoveCardDialog(card, self.datastore)
        if dialog.exec():
            self.reload_cards()

    def _remove_card(self, card: dict) -> None:
        answer = QMessageBox.question(
            self,
            "Remove card",
            "Remove this card permanently?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        deleted = self.datastore.delete_card(
            str(card.get("id", "")),
            str(card.get("subject", "Mathematics")),
        )
        if not deleted:
            QMessageBox.warning(self, "Remove failed", "Could not remove that card.")
            return
        self._remove_card_from_session(card)
        self.reload_cards()

    def _card_selected(self, card: dict) -> None:
        answer = QMessageBox.question(
            self,
            "Start from here",
            "Do you want to start from here?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._begin_session_pool(self._filtered_cards(), first_card=card)

    def _open_start_dialog(self) -> None:
        pool = self._filtered_cards()
        if not pool:
            return
        dialog = StartStudyDialog(self._current_path_label(), len(pool))
        if dialog.exec():
            self._begin_session_pool(pool)

    def _begin_session_pool(self, pool: list[dict], first_card: dict | None = None) -> None:
        if not pool:
            return
        self._cancel_session_prep()
        cards = list(pool)
        random.shuffle(cards)
        if first_card is not None:
            cards = [card for card in cards if card.get("id") != first_card.get("id")]
            cards.insert(0, first_card)
        self.session_id = str(uuid.uuid4())
        self.study_state = None
        self.session_queue = list(cards)
        self.session_cards = list(cards)
        self.session_scores = []
        self.session_temp_batches = {}
        self.session_prep_remaining_cards = []
        self._switch_mode(1)
        seed_cards: list[dict] = []
        should_prepare_async = False
        if len(cards) > 5:
            should_prepare_async = True
            self.study_state = build_session_state(cards, self._current_path_label())
            seed_cards = [self.study_state.card_lookup[card_id] for card_id in self.study_state.seed_ids if card_id in self.study_state.card_lookup]
            if first_card is not None:
                first_id = str(first_card.get("id", ""))
                self.study_state.seed_ids = [card_id for card_id in self.study_state.seed_ids if card_id != first_id]
                self.study_state.seed_ids.insert(0, first_id)
                seed_cards = [card for card in seed_cards if str(card.get("id", "")) != str(first_card.get("id", ""))]
                seed_cards.insert(0, first_card)
            remaining = [card for card in cards if not self.embedding_service.is_card_cached(card)]
            self.session_prep_remaining_cards = [
                card for card in remaining if str(card.get("id", "")) not in {str(seed.get("id", "")) for seed in seed_cards}
            ]
        self._advance_session()
        if should_prepare_async:
            self._start_session_prep(cards, seed_cards)

    def _advance_session(self) -> None:
        if self.study_state and self.study_state.nna_enabled:
            card = next_card_for_session(self.study_state, self.embedding_service)
            if card is None:
                self._finish_session()
                return
            self._start_session(card)
            return
        if not self.session_queue:
            self._finish_session()
            return
        self._start_session(self.session_queue.pop(0))

    def _start_session(self, card: dict) -> None:
        self.current_card = card
        self.revealed_hints = 0
        self.hint_cooldown = 0
        self.last_grade_report = None
        self.current_attempt_logged = False
        self.cooldown_timer.stop()
        self.answer_input.clear()
        self.hints_text.clear()
        self.grade_feedback.clear()
        self.grade_summary.setText("AI grader")
        title = card.get("title", "Untitled")
        if card.get("temporary"):
            title = f"{title} [TEMP]"
        self.session_title.setText(title)
        self.session_meta.setText(
            f"{card.get('subject', 'General')}  |  {card.get('category', 'All')}  |  Difficulty {card.get('natural_difficulty', 5)}/10"
        )
        self.session_question.setText(card.get("question", ""))
        self.hint_status.setText("Hints stay hidden until you press Show hint.")
        self.hint_btn.setEnabled(True)
        self._set_followup_visible(False)
        if self.study_state and self.study_state.nna_enabled:
            self.study_state.shown_entries.append(SessionCardEntry(card=card))

    def _cancel_session_prep(self) -> None:
        if self.session_prep_worker and self.session_prep_worker.isRunning():
            self.session_prep_worker.requestInterruption()
        self.session_prep_worker = None
        if self.topic_cluster_worker and self.topic_cluster_worker.isRunning():
            self.topic_cluster_worker.requestInterruption()
        self.topic_cluster_worker = None
        self.pending_cluster_refresh = False
        self.session_prep_remaining_cards = []
        if self.session_prep_dialog is not None:
            self.session_prep_dialog.close()
            self.session_prep_dialog.deleteLater()
            self.session_prep_dialog = None

    def _ensure_session_prep_dialog(self) -> SessionPrepDialog:
        if self.session_prep_dialog is None:
            self.session_prep_dialog = SessionPrepDialog(self.icons)
        return self.session_prep_dialog

    def _start_session_prep(self, cards: list[dict], seed_cards: list[dict]) -> None:
        dialog = self._ensure_session_prep_dialog()
        dialog.set_progress(5)
        dialog.update_step("seed", "Preparing your first cards in the background...", False)
        dialog.update_step("topics", "Waiting for seed cards...", False)
        dialog.update_step("launch", "First question is ready. Finishing the smart queue in background...", True)
        dialog.show()
        QApplication.processEvents()

        worker = SessionPrepWorker(
            session_id=self.session_id,
            cards=cards,
            seed_cards=seed_cards,
            embedding_service=self.embedding_service,
        )
        self.session_prep_worker = worker
        worker.progress.connect(self._on_session_prep_progress)
        worker.finished.connect(self._on_session_prep_finished)
        worker.failed.connect(self._on_session_prep_failed)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.start()

    def _session_prep_progress_value(self, key: str, current: int, total: int) -> int:
        safe_total = max(1, total)
        safe_current = max(0, min(current, safe_total))
        if key == "seed":
            return 5 + int((safe_current / safe_total) * 65)
        if key == "topics":
            return 70 + int((safe_current / safe_total) * 25)
        if key == "launch":
            return 95 + int((safe_current / safe_total) * 5)
        return 0

    def _on_session_prep_progress(
        self,
        session_id: str,
        key: str,
        message: str,
        current: int,
        total: int,
        done: bool,
    ) -> None:
        if session_id != self.session_id:
            return
        dialog = self._ensure_session_prep_dialog()
        dialog.update_step(key, message, done)
        dialog.set_progress(self._session_prep_progress_value(key, current, total))

    def _on_session_prep_finished(self, session_id: str, cluster_map: object) -> None:
        if session_id != self.session_id:
            return
        self.session_prep_worker = None
        if self.study_state and isinstance(cluster_map, dict):
            self.study_state.cluster_map = {str(key): str(value) for key, value in cluster_map.items()}
        dialog = self._ensure_session_prep_dialog()
        dialog.update_step("launch", "Study session ready.", True)
        dialog.set_progress(100)
        QTimer.singleShot(500, self._close_session_prep_dialog)
        if self.session_prep_remaining_cards:
            remaining = list(self.session_prep_remaining_cards)
            self.session_prep_remaining_cards = []
            self._embed_remaining_cards_in_background(remaining)

    def _on_session_prep_failed(self, session_id: str, message: str) -> None:
        if session_id != self.session_id:
            return
        self.session_prep_worker = None
        self._close_session_prep_dialog()
        QMessageBox.warning(self, "Session prep failed", message)

    def _close_session_prep_dialog(self) -> None:
        if self.session_prep_dialog is None:
            return
        self.session_prep_dialog.close()
        self.session_prep_dialog.deleteLater()
        self.session_prep_dialog = None

    def _schedule_topic_cluster_refresh(self) -> None:
        if not self.study_state or not self.study_state.nna_enabled:
            return
        if self.topic_cluster_worker and self.topic_cluster_worker.isRunning():
            self.pending_cluster_refresh = True
            return
        self.pending_cluster_refresh = False
        worker = TopicClusterWorker(
            session_id=self.session_id,
            cards=list(self.study_state.cards),
            embedding_service=self.embedding_service,
        )
        self.topic_cluster_worker = worker
        worker.finished.connect(self._on_topic_cluster_refresh_finished)
        worker.failed.connect(self._on_topic_cluster_refresh_failed)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.start()

    def _on_topic_cluster_refresh_finished(self, session_id: str, cluster_map: object) -> None:
        if session_id == self.session_id and self.study_state and isinstance(cluster_map, dict):
            self.study_state.cluster_map = {str(key): str(value) for key, value in cluster_map.items()}
        self.topic_cluster_worker = None
        if self.pending_cluster_refresh and session_id == self.session_id:
            self.pending_cluster_refresh = False
            self._schedule_topic_cluster_refresh()

    def _on_topic_cluster_refresh_failed(self, session_id: str, _message: str) -> None:
        self.topic_cluster_worker = None
        if self.pending_cluster_refresh and session_id == self.session_id:
            self.pending_cluster_refresh = False
            self._schedule_topic_cluster_refresh()

    def _ensure_seed_embeddings(self, cards: list[dict], dialog: SessionPrepDialog | None = None) -> bool:
        missing = [card for card in cards if not self.embedding_service.is_card_cached(card)]
        if not missing:
            if dialog is not None:
                dialog.update_step("seed", "Seed cards already had embeddings.", True)
                QApplication.processEvents()
            return True

        loop = QEventLoop(self)
        result = {"ok": True}
        worker = EmbeddingWorker(cards=missing, embedding_service=self.embedding_service)
        self.embedding_worker = worker

        def on_progress(label: str, index: int, total: int) -> None:
            if dialog is not None:
                dialog.update_step("seed", f"Embedding seed cards... ({index}/{total}) {label}", False)
                QApplication.processEvents()

        def on_finished(_cards: list[dict]) -> None:
            loop.quit()

        def on_failed(message: str) -> None:
            result["ok"] = False
            QMessageBox.warning(self, "Embedding unavailable", message)
            loop.quit()

        worker.progress.connect(on_progress)
        worker.finished.connect(on_finished)
        worker.failed.connect(on_failed)
        worker.start()
        loop.exec()
        self.embedding_worker = None
        return bool(result["ok"])

    def _embed_remaining_cards_in_background(self, cards: list[dict]) -> None:
        missing = [card for card in cards if not self.embedding_service.is_card_cached(card)]
        if not missing:
            self._schedule_topic_cluster_refresh()
            return
        if self.embedding_worker and self.embedding_worker.isRunning():
            return
        self.embedding_worker = EmbeddingWorker(cards=missing, embedding_service=self.embedding_service)
        self.embedding_worker.finished.connect(self._on_background_embeddings_finished)
        self.embedding_worker.failed.connect(lambda _message: self._on_background_embeddings_finished([]))
        self.embedding_worker.start()

    def _on_background_embeddings_finished(self, _cards: list[dict]) -> None:
        self.embedding_worker = None
        self._schedule_topic_cluster_refresh()
        self._refresh_global_recommendations()
        self._render_cards()
        if self.card_search_input.text().strip():
            self.card_search_timer.start(10)

    def _set_followup_visible(self, visible: bool) -> None:
        self.followup_title.setVisible(visible)
        self.followup_input.setVisible(visible)
        self.followup_btn.setVisible(visible)

    def _build_followup_context(self) -> str:
        if not self.current_card:
            return ""
        parts = [
            f"Question: {self.current_card.get('question', '')}",
            f"Expected answer: {self.current_card.get('answer', '')}",
            f"Hints: {', '.join(self.current_card.get('hints', []))}",
        ]
        if self.last_grade_report:
            parts.extend(
                [
                    f"Score: {self.last_grade_report.get('marks_out_of_10', '')}",
                    f"What went good: {self.last_grade_report.get('what_went_good', '')}",
                    f"What went bad: {self.last_grade_report.get('what_went_bad', '')}",
                    f"What to improve: {self.last_grade_report.get('what_to_improve', '')}",
                ]
            )
        return "\n".join(parts) + "\n"

    def _ask_i_dont_know(self) -> None:
        if not self.current_card:
            QMessageBox.information(self, "No card", "Start a card first.")
            return
        self._set_followup_visible(True)
        self.followup_title.setText("Follow up on this card")
        self.followup_input.setPlainText("Thoroughly explain this to me step by step")
        self.grade_summary.setText("Study help")
        self.grade_feedback.setMarkdown("### Study help\nWorking on a step-by-step explanation...")
        self._run_followup(auto_prompt="Thoroughly explain this to me step by step")

    def _show_hint(self) -> None:
        if not self.current_card:
            return
        hints = self.current_card.get("hints", [])
        if self.hint_cooldown > 0:
            return
        if self.revealed_hints >= len(hints):
            self.hint_status.setText("No more hints for this card.")
            self.hint_btn.setEnabled(False)
            return
        self.revealed_hints += 1
        visible = hints[: self.revealed_hints]
        self.hints_text.setPlainText("\n".join(f"{idx + 1}. {hint}" for idx, hint in enumerate(visible)))
        if self.revealed_hints < len(hints):
            self.hint_cooldown = 30
            self.hint_btn.setEnabled(False)
            self.hint_status.setText("Next hint in 30s.")
            self.cooldown_timer.start(1000)
        else:
            self.hint_status.setText("All hints revealed.")
            self.hint_btn.setEnabled(False)

    def _tick_hint_cooldown(self) -> None:
        if self.hint_cooldown <= 0:
            self.cooldown_timer.stop()
            self.hint_btn.setEnabled(True)
            self.hint_status.setText("You can reveal the next hint now.")
            return
        self.hint_cooldown -= 1
        self.hint_status.setText(f"Next hint in {self.hint_cooldown}s.")

    def _save_attempt(self, graded: bool, grade_payload: dict | None = None) -> None:
        if not self.current_card:
            return
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "card_id": self.current_card.get("id"),
            "subject": self.current_card.get("subject"),
            "category": self.current_card.get("category"),
            "subtopic": self.current_card.get("subtopic"),
            "question": self.current_card.get("question"),
            "answer_text": self.answer_input.toPlainText().strip(),
            "hints_used": self.revealed_hints,
            "graded": graded,
            "temporary": bool(self.current_card.get("temporary", False)),
        }
        if self.study_state:
            payload["topic_cluster_key"] = card_cluster_key(self.study_state, self.current_card)
        if grade_payload:
            payload.update(grade_payload)
        if payload.get("temporary"):
            self._record_temp_attempt(payload)
            return
        self.datastore.save_attempt(payload)

    def _record_temp_attempt(self, payload: dict) -> None:
        batch_id = str(self.current_card.get("temp_batch_id", "")).strip()
        if not batch_id:
            self.datastore.save_attempt(payload)
            return
        batch = self.session_temp_batches.setdefault(
            batch_id,
            {
                "expected_count": 4,
                "attempts": [],
                "card_ids": set(),
            },
        )
        card_id = str(payload.get("card_id", "")).strip()
        batch["card_ids"].add(card_id)
        batch["attempts"] = [item for item in batch["attempts"] if str(item.get("card_id", "")).strip() != card_id]
        batch["attempts"].append(payload)
        if len(batch["attempts"]) >= int(batch.get("expected_count", 4)):
            self._finalize_temp_batch(batch_id)

    def _finalize_temp_batch(self, batch_id: str) -> None:
        batch = self.session_temp_batches.get(batch_id)
        if not batch:
            return
        attempts = list(batch.get("attempts", []))
        weak_attempts = [item for item in attempts if item.get("marks_out_of_10") is not None and float(item.get("marks_out_of_10") or 0) <= 5.0]
        if len(weak_attempts) >= 2:
            self.datastore.save_attempts(attempts)
        elif len(weak_attempts) == 1:
            self.datastore.save_attempt(weak_attempts[0])
        del self.session_temp_batches[batch_id]

    def _grade(self) -> None:
        if not self.current_card:
            QMessageBox.information(self, "No card", "Start a card first.")
            return
        user_answer = self.answer_input.toPlainText().strip()
        if not user_answer:
            QMessageBox.warning(self, "Missing answer", "Write an answer before grading.")
            return
        if self.grade_worker and self.grade_worker.isRunning():
            return

        self.grade_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        self.grade_summary.setText("Grading...")
        self.grade_feedback.clear()
        self._set_followup_visible(False)

        self.grade_worker = GradeWorker(
            question=self.current_card.get("question", ""),
            expected_answer=self.current_card.get("answer", ""),
            user_answer=user_answer,
            difficulty=int(self.current_card.get("natural_difficulty", 5)),
            ollama=self.ollama,
            profile_context=self.datastore.load_profile(),
        )
        self.grade_worker.stream.connect(self._on_grade_stream)
        self.grade_worker.status.connect(self.grade_summary.setText)
        self.grade_worker.finished.connect(self._on_grade_done)
        self.grade_worker.failed.connect(self._on_grade_failed)
        self.grade_worker.start()

    def _on_grade_stream(self, markdown_text: str) -> None:
        self.grade_feedback.setMarkdown(markdown_text)

    def _on_grade_done(self, report: dict) -> None:
        score = float(report.get("marks_out_of_10", 0) or 0)
        self.last_grade_report = report
        state = str(report.get("state", "wrong")).title()
        self.grade_summary.setText(f"Final score: {score:.1f}/10  |  {state}")
        self._save_attempt(graded=True, grade_payload=report)
        self._refresh_global_recommendations()
        self.current_attempt_logged = True
        self.session_scores.append(score)
        if self.study_state and self.current_card:
            result = register_grade_result(self.study_state, self.current_card, report)
            if self.study_state.shown_entries:
                self.study_state.shown_entries[-1].grade_report = report
            mark_card_completed(self.study_state, self.current_card)
            if result["weak"]:
                enqueue_similar_cards(self.study_state, self.current_card, self.embedding_service)
            if result["trigger_reinforcement"]:
                self._ask_reinforcement_permission(result["cluster_key"])
        extra = [
            f"Good: {report.get('what_went_good', '')}",
            f"Bad: {report.get('what_went_bad', '')}",
        ]
        if report.get("what_to_improve"):
            extra.append(f"Improve: {report.get('what_to_improve')}")
        if float(score) >= 9:
            extra.append("Coach: Great work. You got the core meaning right, and that matters most.")
        elif float(score) <= 5:
            extra.append("Coach: Keep going. Use the follow up feature to ask more questions and work through it step by step.")
        self.grade_feedback.append("<hr>")
        self.grade_feedback.append("<br>".join(extra))
        self._set_followup_visible(True)
        self.grade_btn.setEnabled(True)
        self.next_btn.setEnabled(True)

    def _ask_reinforcement_permission(self, cluster_key: str) -> None:
        if not self.current_card or self.reinforcement_worker is not None:
            return
        answer = QMessageBox.question(
            self,
            "Reinforcement available",
            "ONCard detected repeated weakness in this topic. Generate 4 temporary reinforcement questions now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return
        self._run_reinforcement(cluster_key)

    def _run_reinforcement(self, cluster_key: str) -> None:
        if not self.current_card or not self.study_state:
            return
        related_cards = self._cluster_cards(cluster_key)
        recent_incorrect = [
            attempt
            for attempt in self.datastore.load_attempts()[-12:]
            if attempt.get("session_id") == self.session_id
            and attempt.get("topic_cluster_key") == cluster_key
            and attempt.get("how_good") is not None
            and float(attempt.get("how_good") or 0.0) < 88.8888
        ]
        ai_settings = self.datastore.load_ai_settings()
        dialog = ReinforcementProgressDialog(self.icons)
        dialog.show()
        QApplication.processEvents()

        loop = QEventLoop(self)
        result: dict[str, list[dict] | str] = {"cards": []}
        worker = ReinforcementWorker(
            ollama=self.ollama,
            weak_card=self.current_card,
            similar_cards=related_cards,
            recent_incorrect_answers=recent_incorrect,
            profile_context=self.datastore.load_profile(),
            assistant_tone=str(ai_settings.get("assistant_tone", "")),
            context_length=int(ai_settings.get("reinforcement_context_length", 8192)),
        )
        self.reinforcement_worker = worker

        def on_progress(step_key: str, message: str, done: bool) -> None:
            dialog.update_step(step_key, message, done)

        def on_finished(cards: list[dict]) -> None:
            result["cards"] = cards
            loop.quit()

        def on_failed(message: str) -> None:
            result["error"] = message
            loop.quit()

        worker.progress.connect(on_progress)
        worker.finished.connect(on_finished)
        worker.failed.connect(on_failed)
        worker.start()
        loop.exec()
        self.reinforcement_worker = None

        if result.get("error"):
            dialog.close()
            QMessageBox.warning(self, "Reinforcement failed", str(result.get("error")))
            return

        temp_cards = list(result.get("cards", []))
        dialog.update_step("embedding", "Embedding temporary cards...", False)
        if temp_cards and not self._ensure_temp_embeddings(temp_cards):
            dialog.close()
            return
        dialog.update_step("embedding", "Embedding temporary cards...", True)

        dialog.update_step("adding", "Adding to session...", False)
        batch_id = str(uuid.uuid4())
        for card in temp_cards:
            card["temp_batch_id"] = batch_id
        self.session_temp_batches[batch_id] = {"expected_count": len(temp_cards), "attempts": [], "card_ids": set()}
        self.session_cards.extend(temp_cards)
        queue_reinforcement_cards(self.study_state, temp_cards, cluster_key)
        self._schedule_topic_cluster_refresh()
        dialog.update_step("adding", "Adding to session...", True)
        dialog.close()

    def _ensure_temp_embeddings(self, cards: list[dict]) -> bool:
        missing = [card for card in cards if not self.embedding_service.is_card_cached(card)]
        if not missing:
            return True
        progress = QProgressDialog("Embedding temporary cards...", None, 0, len(missing), self)
        progress.setWindowTitle("Preparing reinforcement")
        progress.setMinimumDuration(0)
        progress.setCancelButton(None)
        progress.setValue(0)
        progress.show()

        loop = QEventLoop(self)
        result = {"ok": True}
        worker = EmbeddingWorker(cards=missing, embedding_service=self.embedding_service)

        def on_progress(label: str, index: int, total: int) -> None:
            progress.setMaximum(total)
            progress.setValue(index - 1)
            progress.setLabelText(f"Embedding temporary cards... ({index}/{total})\n{label}")

        def on_finished(_cards: list[dict]) -> None:
            progress.setValue(progress.maximum())
            loop.quit()

        def on_failed(message: str) -> None:
            result["ok"] = False
            QMessageBox.warning(self, "Embedding unavailable", message)
            loop.quit()

        worker.progress.connect(on_progress)
        worker.finished.connect(on_finished)
        worker.failed.connect(on_failed)
        worker.start()
        loop.exec()
        progress.close()
        return bool(result["ok"])

    def _cluster_cards(self, cluster_key: str) -> list[dict]:
        if not self.study_state:
            return []
        return [
            card
            for card in self.study_state.cards
            if card_cluster_key(self.study_state, card) == cluster_key and str(card.get("id", "")) != str(self.current_card.get("id", ""))
        ]

    def _on_grade_failed(self, message: str) -> None:
        self.grade_summary.setText("Grading failed.")
        self.grade_feedback.setPlainText(message)
        self.grade_btn.setEnabled(True)
        self.next_btn.setEnabled(True)

    def _run_followup(self, auto_prompt: str | None = None) -> None:
        if self.followup_worker and self.followup_worker.isRunning():
            return
        if not self.current_card:
            return
        prompt = (auto_prompt or self.followup_input.toPlainText()).strip()
        if not prompt:
            QMessageBox.information(self, "Follow up", "Write a follow-up prompt first.")
            return
        context = self._build_followup_context()
        self.followup_btn.setEnabled(False)
        if auto_prompt is None:
            self.followup_input.clear()
        self.followup_worker = FollowUpWorker(
            ollama=self.ollama,
            model="gemma3:4b",
            prompt=prompt,
            context=context,
        )
        self.followup_worker.chunk.connect(self.grade_feedback.setMarkdown)
        self.followup_worker.finished.connect(lambda: self.followup_btn.setEnabled(True))
        self.followup_worker.failed.connect(self._on_followup_failed)
        self.followup_worker.start()

    def _on_followup_failed(self, message: str) -> None:
        self.followup_btn.setEnabled(True)
        self.grade_feedback.append("<hr>")
        self.grade_feedback.append(message)

    def _next_card(self) -> None:
        if self.current_card and self.answer_input.toPlainText().strip() and not self.current_attempt_logged:
            self._save_attempt(graded=False, grade_payload={"marks_out_of_10": None, "how_good": None})
            self.current_attempt_logged = True
            if self.study_state and self.current_card:
                mark_card_completed(self.study_state, self.current_card)
        self._advance_session()

    def _finish_session(self) -> None:
        for batch_id in list(self.session_temp_batches.keys()):
            self._finalize_temp_batch(batch_id)
        avg_marks = sum(self.session_scores) / len(self.session_scores) if self.session_scores else 0.0
        avg_difficulty = (
            sum(int(card.get("natural_difficulty", 5)) for card in self.session_cards) / len(self.session_cards)
            if self.session_cards
            else 0.0
        )
        QMessageBox.information(
            self,
            "Session complete",
            f"Average marks: {avg_marks:.1f}/10\nAverage difficulty: {avg_difficulty:.1f}/10",
        )
        self._cancel_session_prep()
        self.current_card = None
        self.study_state = None
        self.session_id = ""
        self.session_queue = []
        self.session_cards = []
        self.session_scores = []
        self.session_temp_batches = {}
        self.session_title.setText("Pick a card to start")
        self.session_meta.setText("")
        self.session_question.setText("Use the Cards subtab or press Start for the current section.")
        self.answer_input.clear()
        self.hints_text.clear()
        self.grade_feedback.clear()
        self.grade_summary.setText("AI grader")
        self._set_followup_visible(False)

    def _remove_card_from_session(self, card: dict) -> None:
        card_id = str(card.get("id", ""))
        self.session_queue = [item for item in self.session_queue if str(item.get("id", "")) != card_id]
        self.session_cards = [item for item in self.session_cards if str(item.get("id", "")) != card_id]
        if self.study_state:
            self.study_state.unseen_ids = [item for item in self.study_state.unseen_ids if item != card_id]
            self.study_state.priority_ids = [item for item in self.study_state.priority_ids if item != card_id]
            self.study_state.deferred_ids = [item for item in self.study_state.deferred_ids if item != card_id]
            self.study_state.card_lookup.pop(card_id, None)
            self.study_state.cards = [item for item in self.study_state.cards if str(item.get("id", "")) != card_id]
        if self.current_card and str(self.current_card.get("id", "")) == card_id:
            self._advance_session()
