from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import re
import zipfile
from xml.etree import ElementTree as ET

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QTextOption
from PySide6.QtPdf import QPdfDocument, QPdfDocumentRenderOptions

from studymate.constants import FILES_TO_CARDS_IMAGE_SUFFIXES, FILES_TO_CARDS_SOURCE_LIMITS


@dataclass(frozen=True)
class SelectedSourceFile:
    path: Path
    family: str
    unit_count: int
    label: str


@dataclass(frozen=True)
class NormalizedPage:
    source_path: Path
    family: str
    unit_index: int
    total_units: int
    label: str
    image_path: Path


def detect_source_family(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in FILES_TO_CARDS_IMAGE_SUFFIXES:
        return "images"
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".pptx":
        return "pptx"
    return None


def describe_source_file(path: Path) -> SelectedSourceFile:
    family = detect_source_family(path)
    if family is None:
        raise ValueError(f"Unsupported file type: {path.suffix}")
    if family == "images":
        return SelectedSourceFile(path=path, family=family, unit_count=1, label="1 image")
    if family == "pdf":
        page_count = _count_pdf_pages(path)
        label = f"{page_count} page" if page_count == 1 else f"{page_count} pages"
        return SelectedSourceFile(path=path, family=family, unit_count=page_count, label=label)
    slide_count = _count_pptx_slides(path)
    label = f"{slide_count} slide" if slide_count == 1 else f"{slide_count} slides"
    return SelectedSourceFile(path=path, family=family, unit_count=slide_count, label=label)


def files_to_cards_limit(mode: str) -> int:
    limits = FILES_TO_CARDS_SOURCE_LIMITS.get(mode, FILES_TO_CARDS_SOURCE_LIMITS["standard"])
    return int(limits["max_inputs"])


def files_to_cards_question_cap(total_units: int, mode: str) -> int:
    limits = FILES_TO_CARDS_SOURCE_LIMITS.get(mode, FILES_TO_CARDS_SOURCE_LIMITS["standard"])
    if total_units <= 0:
        return 0
    if total_units <= 6:
        return int(limits["up_to_6"])
    if total_units <= 9:
        return int(limits["up_to_9"])
    return int(limits["up_to_max"])


def paper_ctx_for_units(total_units: int) -> int:
    if total_units <= 2:
        return 5_000
    if total_units <= 6:
        return 6_000
    if total_units <= 10:
        return 9_000
    if total_units <= 12:
        return 11_000
    return 16_000


def gemma_ctx_for_batch(batch_index: int) -> int:
    if batch_index <= 1:
        return 6_000
    if batch_index <= 3:
        return 10_000
    return 12_000


def normalize_sources(
    files: list[Path],
    *,
    source_family: str,
    run_dir: Path,
    on_status=None,
    max_workers: int = 2,
) -> list[NormalizedPage]:
    rendered_dir = run_dir / "rendered"
    rendered_dir.mkdir(parents=True, exist_ok=True)

    pages: list[NormalizedPage] = []
    unit_index = 0
    pool_workers = max(1, min(int(max_workers or 1), 4))

    if source_family == "images":
        jobs: list[tuple[int, Path, Path]] = []
        for file_index, path in enumerate(files, start=1):
            if on_status:
                on_status(f"Preparing {path.name} ({file_index}/{len(files)})...")
            unit_index += 1
            output = rendered_dir / f"image_{unit_index:03d}.png"
            jobs.append((unit_index, path, output))
        with ThreadPoolExecutor(max_workers=pool_workers) as executor:
            futures = [executor.submit(_normalize_image_file, path, output) for _index, path, output in jobs]
            for future in futures:
                future.result()
        pages = [
            NormalizedPage(
                source_path=path,
                family=source_family,
                unit_index=index,
                total_units=0,
                label=path.name,
                image_path=output,
            )
            for index, path, output in jobs
        ]
        total_units = len(pages)
        return [
            NormalizedPage(
                source_path=page.source_path,
                family=page.family,
                unit_index=page.unit_index,
                total_units=total_units,
                label=page.label,
                image_path=page.image_path,
            )
            for page in pages
        ]

    for file_index, path in enumerate(files, start=1):
        if on_status:
            on_status(f"Preparing {path.name} ({file_index}/{len(files)})...")
        if source_family == "pdf":
            document = QPdfDocument()
            if document.load(str(path)) != QPdfDocument.Error.None_:
                raise ValueError(f"Could not open PDF: {path.name}")
            for page_number in range(document.pageCount()):
                unit_index += 1
                output = rendered_dir / f"pdf_{unit_index:03d}.png"
                _render_pdf_page(document, page_number, output)
                pages.append(
                    NormalizedPage(
                        source_path=path,
                        family=source_family,
                        unit_index=unit_index,
                        total_units=0,
                        label=f"{path.name} - page {page_number + 1}",
                        image_path=output,
                    )
                )
            continue

        slide_texts = _extract_pptx_slide_texts(path)
        slide_jobs: list[tuple[int, int, str, Path]] = []
        for slide_number, slide_text in enumerate(slide_texts, start=1):
            unit_index += 1
            output = rendered_dir / f"pptx_{unit_index:03d}.png"
            slide_jobs.append((unit_index, slide_number, slide_text, output))
        with ThreadPoolExecutor(max_workers=pool_workers) as executor:
            futures = [
                executor.submit(_render_slide_text_image, path.name, slide_number, slide_text, output)
                for _index, slide_number, slide_text, output in slide_jobs
            ]
            for future in futures:
                future.result()
        pages.extend(
            [
                NormalizedPage(
                    source_path=path,
                    family=source_family,
                    unit_index=index,
                    total_units=0,
                    label=f"{path.name} - slide {slide_number}",
                    image_path=output,
                )
                for index, slide_number, _slide_text, output in slide_jobs
            ]
        )

    total_units = len(pages)
    return [
        NormalizedPage(
            source_path=page.source_path,
            family=page.family,
            unit_index=page.unit_index,
            total_units=total_units,
            label=page.label,
            image_path=page.image_path,
        )
        for page in pages
    ]


def create_source_preview(path: Path, *, max_width: int = 280, max_height: int = 180) -> QImage:
    family = detect_source_family(path)
    if family is None:
        raise ValueError(f"Unsupported file type: {path.suffix}")
    if family == "images":
        image = QImage(str(path))
        if image.isNull():
            raise ValueError(f"Could not open image: {path.name}")
        return _scaled_image(image, max_width=max_width, max_height=max_height)
    if family == "pdf":
        document = QPdfDocument()
        if document.load(str(path)) != QPdfDocument.Error.None_:
            raise ValueError(f"Could not open PDF: {path.name}")
        output = document.render(0, QSize(max_width * 2, max_height * 2), QPdfDocumentRenderOptions())
        if output.isNull():
            raise ValueError(f"Could not render PDF preview: {path.name}")
        return _scaled_image(output, max_width=max_width, max_height=max_height)
    slide_texts = _extract_pptx_slide_texts(path)
    if not slide_texts:
        raise ValueError(f"Could not load PPTX preview: {path.name}")
    return _render_slide_text_preview(path.name, slide_texts[0], max_width=max_width, max_height=max_height)


def _count_pdf_pages(path: Path) -> int:
    document = QPdfDocument()
    if document.load(str(path)) != QPdfDocument.Error.None_:
        raise ValueError(f"Could not open PDF: {path.name}")
    return max(document.pageCount(), 0)


def _count_pptx_slides(path: Path) -> int:
    return len(_extract_pptx_slide_texts(path))


def _normalize_image_file(source: Path, destination: Path) -> None:
    image = QImage(str(source))
    if image.isNull():
        raise ValueError(f"Could not open image: {source.name}")
    image = _scaled_image(image)
    if not image.save(str(destination), "PNG"):
        raise ValueError(f"Could not normalize image: {source.name}")


def _render_pdf_page(document: QPdfDocument, page_number: int, destination: Path) -> None:
    point_size = document.pagePointSize(page_number)
    if point_size.isEmpty():
        image_size = QSize(1400, 1800)
    else:
        ratio = point_size.width() / point_size.height() if point_size.height() else 0.77
        width = 1400
        height = max(int(width / ratio), 900) if ratio else 1800
        image_size = QSize(width, height)
    image = document.render(page_number, image_size, QPdfDocumentRenderOptions())
    if image.isNull():
        raise ValueError(f"Could not render PDF page {page_number + 1}")
    image = _scaled_image(image)
    if not image.save(str(destination), "PNG"):
        raise ValueError(f"Could not save rendered PDF page {page_number + 1}")


def _extract_pptx_slide_texts(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        slide_names = sorted(
            [name for name in archive.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", name)],
            key=_natural_slide_key,
        )
        slide_texts: list[str] = []
        for slide_name in slide_names:
            root = ET.fromstring(archive.read(slide_name))
            parts = [node.text.strip() for node in root.findall(".//{*}t") if node.text and node.text.strip()]
            slide_texts.append("\n".join(parts).strip() or "No text content was found on this slide.")
        return slide_texts


def _render_slide_text_image(file_name: str, slide_number: int, slide_text: str, destination: Path) -> None:
    image = QImage(1600, 900, QImage.Format.Format_ARGB32)
    image.fill(QColor("#ffffff"))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    title_font = QFont("Nunito Sans", 18)
    title_font.setBold(True)
    body_font = QFont("Nunito Sans", 12)

    painter.setFont(title_font)
    painter.setPen(QColor("#1a1a1a"))
    painter.drawText(QRectF(56, 44, 1488, 60), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), f"{file_name} - Slide {slide_number}")

    painter.setFont(body_font)
    painter.setPen(QColor("#444444"))
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WordWrap)
    painter.drawText(QRectF(56, 120, 1488, 724), slide_text, option)
    painter.end()

    image = _scaled_image(image)
    if not image.save(str(destination), "PNG"):
        raise ValueError(f"Could not render PPTX slide {slide_number}")


def _render_slide_text_preview(file_name: str, slide_text: str, *, max_width: int, max_height: int) -> QImage:
    image = QImage(1200, 720, QImage.Format.Format_ARGB32)
    image.fill(QColor("#ffffff"))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    title_font = QFont("Nunito Sans", 16)
    title_font.setBold(True)
    body_font = QFont("Nunito Sans", 11)

    painter.setFont(title_font)
    painter.setPen(QColor("#1a1a1a"))
    painter.drawText(QRectF(36, 28, 1128, 52), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), file_name)

    painter.setFont(body_font)
    painter.setPen(QColor("#444444"))
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WordWrap)
    painter.drawText(QRectF(36, 92, 1128, 584), slide_text, option)
    painter.end()

    return _scaled_image(image, max_width=max_width, max_height=max_height)


def _scaled_image(image: QImage, max_width: int = 1280, max_height: int = 1280) -> QImage:
    if image.width() <= max_width and image.height() <= max_height:
        return image
    return image.scaled(
        max_width,
        max_height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _natural_slide_key(name: str) -> int:
    match = re.search(r"slide(\d+)\.xml$", name)
    return int(match.group(1)) if match else 0
