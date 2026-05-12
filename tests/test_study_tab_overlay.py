from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication, QWidget

from studymate.services.data_store import DataStore
from studymate.ui.icon_helper import IconHelper
from studymate.ui.study_tab import AiResponseOverlay, StudyTab
from studymate.utils.paths import AppPaths


class FakeOllama:
    def embed_text(self, model_tag: str, text: str) -> list[float]:
        del model_tag, text
        return [0.0, 0.0, 0.0]


class _ImmediateFinishedSignal:
    def __init__(self) -> None:
        self._callbacks: list = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self) -> None:
        for callback in list(self._callbacks):
            callback()


class ImmediatePropertyAnimation:
    def __init__(self, target, property_name, parent=None) -> None:
        del parent
        self._target = target
        if isinstance(property_name, bytes):
            self._property_name = property_name.decode("utf-8")
        else:
            self._property_name = str(property_name)
        self._end_value = None
        self.finished = _ImmediateFinishedSignal()

    def setDuration(self, _duration: int) -> None:
        return

    def setStartValue(self, _value) -> None:
        return

    def setEndValue(self, value) -> None:
        self._end_value = value

    def setEasingCurve(self, _curve) -> None:
        return

    def start(self) -> None:
        if self._end_value is not None:
            if self._property_name == "geometry":
                self._target.setGeometry(self._end_value)
            elif self._property_name == "pos":
                self._target.move(self._end_value)
            elif self._property_name == "windowOpacity":
                self._target.setWindowOpacity(float(self._end_value))
        self.finished.emit()

    def stop(self) -> None:
        return


class StudyTabHarness(StudyTab):
    def __init__(self, datastore: DataStore, icons: IconHelper) -> None:
        self.stop_calls = 0
        super().__init__(datastore, FakeOllama(), icons, preflight=MagicMock())

    def reload_cards(self, force: bool = False) -> None:
        del force
        self.cards_loaded_once = True
        self.cards_dirty = False
        self.cards = []

    def _stop_active_ai_workers(self) -> None:
        self.stop_calls += 1


class StudyTabOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = AppPaths(self.root)
        self.paths.ensure()
        self.datastore = DataStore(self.paths)
        self.icons = IconHelper(self.root)

    def tearDown(self) -> None:
        self.datastore.close()
        self.tempdir.cleanup()

    def _create_parent(self) -> QWidget:
        parent = QWidget()
        parent.resize(1600, 900)
        parent.show()
        self.addCleanup(parent.close)
        self._app.processEvents()
        return parent

    def _create_overlay(self) -> AiResponseOverlay:
        overlay = AiResponseOverlay(self.icons, self._create_parent())
        self._app.processEvents()
        return overlay

    def test_second_wiki_search_returns_overlay_to_loading_state(self) -> None:
        overlay = self._create_overlay()
        queries: list[str] = []
        overlay.wikiSearchRequested.connect(queries.append)

        overlay.begin_stream()
        overlay.enable_wikipedia_tabs()
        overlay.set_wikipedia_markdown("# Topic One")
        self._app.processEvents()

        overlay.show_wikipedia_search_entry()
        self._app.processEvents()
        self.assertTrue(overlay._wiki_entry_active)
        self.assertTrue(overlay.wiki_entry_shell.isVisible())
        self.assertFalse(overlay.response_host.isVisible())

        start_global = QRect(overlay.wiki_entry_shell.mapToGlobal(QPoint(0, 0)), overlay.wiki_entry_shell.size())
        with patch("studymate.ui.study_tab.QPropertyAnimation", ImmediatePropertyAnimation):
            overlay._animate_wiki_entry_to_result_menu(start_global, "topic two")
        self._app.processEvents()

        self.assertEqual(["topic two"], queries)
        self.assertTrue(overlay.isVisible())
        self.assertFalse(overlay._wiki_entry_active)
        self.assertFalse(overlay.wiki_entry_shell.isVisible())
        self.assertTrue(overlay.response_host.isVisible())
        self.assertIs(overlay.response_stack.currentWidget(), overlay.skeleton)
        self.assertTrue(overlay.close_btn.isVisible())
        self.assertFalse(overlay.copy_btn.isVisible())

    def test_reopened_wiki_entry_cancel_restores_previous_results(self) -> None:
        overlay = self._create_overlay()

        overlay.begin_stream()
        overlay.enable_wikipedia_tabs()
        overlay.set_wikipedia_markdown("# Topic One\n\nBody text.")
        self._app.processEvents()
        self.assertTrue(overlay.response_host.isVisible())
        self.assertIs(overlay.response_stack.currentWidget(), overlay.body_container)

        overlay.show_wikipedia_search_entry()
        self._app.processEvents()
        self.assertTrue(overlay._wiki_entry_active)
        self.assertTrue(overlay.wiki_entry_shell.isVisible())
        self.assertFalse(overlay.response_host.isVisible())

        overlay.close_wikipedia_search_entry()
        self._app.processEvents()

        self.assertTrue(overlay.isVisible())
        self.assertFalse(overlay._wiki_entry_active)
        self.assertEqual("wiki", overlay._tab_mode)
        self.assertTrue(overlay.header_frame.isVisible())
        self.assertTrue(overlay.response_host.isVisible())
        self.assertIs(overlay.response_stack.currentWidget(), overlay.body_container)
        self.assertFalse(overlay.wiki_entry_shell.isVisible())
        self.assertIn("Topic One", overlay.body.toPlainText())

    def test_study_tab_reopen_preserves_active_wiki_result_session_state(self) -> None:
        tab = StudyTabHarness(self.datastore, self.icons)
        tab.resize(1600, 900)
        tab.show()
        self.addCleanup(tab.close)
        self._app.processEvents()

        assert tab.ai_response_overlay is not None
        tab.ai_query_request_id = 7
        tab.ai_response_overlay.begin_stream()
        tab.ai_response_overlay.enable_wikipedia_tabs()
        tab.ai_response_overlay.set_wikipedia_markdown("# Topic One")
        self._app.processEvents()

        tab.open_wikipedia_search_entry()
        self._app.processEvents()

        self.assertEqual(0, tab.stop_calls)
        self.assertEqual(7, tab.ai_query_request_id)
        self.assertTrue(tab.ai_response_overlay._wiki_entry_active)
        self.assertTrue(tab.ai_response_overlay.wiki_entry_shell.isVisible())


if __name__ == "__main__":
    unittest.main()
