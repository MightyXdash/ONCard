from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from studymate.utils.paths import AppPaths
from studymate.workers.files_to_cards_worker import (
    FilesToCardsJob,
    FilesToCardsWorker,
    _clean_question_ocr_plain_text,
    _extract_question_candidates,
    _question_items_from_result,
)


class FakeOllama:
    pass


class FilesToCardsWorkerRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.paths = AppPaths(self.root)
        self.paths.ensure()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _page(self, index: int) -> SimpleNamespace:
        image_path = self.paths.runtime / f"page_{index}.png"
        image_path.write_bytes(b"image")
        return SimpleNamespace(
            image_path=image_path,
            label=f"Page {index}",
            unit_index=index,
            total_units=2,
            family="images",
        )

    def _job(self, *, use_ocr: bool) -> FilesToCardsJob:
        return FilesToCardsJob(
            run_id="run-1",
            mode="standard",
            source_family="images",
            file_paths=[self.root / "input.png"],
            requested_questions=2,
            custom_instructions="",
            use_ocr=use_ocr,
            background_workers=2,
        )

    def test_ocr_off_uses_direct_vision_paper_route(self) -> None:
        pages = [self._page(1), self._page(2)]
        worker = FilesToCardsWorker(job=self._job(use_ocr=False), ollama=FakeOllama(), runtime_root=self.paths.runtime)

        with patch("studymate.workers.files_to_cards_worker.normalize_sources", return_value=pages), patch.object(
            worker,
            "_run_vision_paper_stage",
            return_value="vision paper",
        ) as vision_paper, patch.object(worker, "_run_gemma_stage", return_value=["Question 1"]) as gemma_stage, patch.object(
            worker,
            "_ocr_page",
            side_effect=AssertionError("OCR path should not run when OCR is off."),
        ), patch.object(
            worker,
            "_run_paper_stage",
            side_effect=AssertionError("Text paper stage should not run before direct vision paper routing."),
        ):
            worker._run_pipeline()

        vision_paper.assert_called_once_with(pages)
        gemma_stage.assert_called_once_with("vision paper")

    def test_ocr_on_uses_ocr_then_text_paper_route(self) -> None:
        pages = [self._page(1), self._page(2)]
        worker = FilesToCardsWorker(job=self._job(use_ocr=True), ollama=FakeOllama(), runtime_root=self.paths.runtime)

        with patch("studymate.workers.files_to_cards_worker.normalize_sources", return_value=pages), patch.object(
            worker,
            "_ocr_page",
            side_effect=["ocr one", "ocr two"],
        ) as ocr_page, patch.object(worker, "_run_paper_stage", return_value="paper") as paper_stage, patch.object(
            worker,
            "_run_gemma_stage",
            return_value=["Question 1"],
        ) as gemma_stage, patch.object(
            worker,
            "_run_vision_paper_stage",
            side_effect=AssertionError("Direct vision paper route should not run when OCR is on."),
        ):
            worker._run_pipeline()

        self.assertEqual(2, ocr_page.call_count)
        paper_stage.assert_called_once()
        gemma_stage.assert_called_once_with("paper")

    def test_question_result_accepts_common_structured_shapes(self) -> None:
        self.assertEqual(["One?", "Two?"], _question_items_from_result({"questions": ["One?", "Two?"]}))
        self.assertEqual(["One?", "Two?"], _question_items_from_result({"question_1": "One?", "question_2": "Two?"}))
        self.assertEqual(["One?", "Two?"], _question_items_from_result(["One?", "Two?"]))

    def test_plain_question_fallback_extracts_numbered_questions(self) -> None:
        text = "1. What is photosynthesis?\n2. Why do plants need sunlight?\nAnswer: ignore me"
        self.assertEqual(
            ["What is photosynthesis?", "Why do plants need sunlight?"],
            _extract_question_candidates(text),
        )

    def test_question_ocr_cleanup_removes_prompt_echoes(self) -> None:
        text = (
            "## Plain Text\n"
            "You are a careful OCR assistant.\n"
            "ONCard app context:\n"
            "Feature: Files To Cards OCR extraction\n"
            "\n"
            "OXIDES.pptx - Slide 1\n"
            "**Chemical properties** of metal oxides.\n"
        )
        self.assertEqual(
            "OXIDES.pptx - Slide 1\nChemical properties of metal oxides.",
            _clean_question_ocr_plain_text(text),
        )


if __name__ == "__main__":
    unittest.main()
