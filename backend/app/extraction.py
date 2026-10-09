"""Local, coordinate-preserving document extraction.

The default pipeline uses PDF text and ruled tables when available and Tesseract
for image-only pages. Its output contains data, never executable instructions.
All rectangles use normalized top-left coordinates on the rendered page.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
import shutil
import time
from typing import Any

import pymupdf
from PIL import Image, ImageOps, UnidentifiedImageError
import pytesseract


MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PAGES = 20
MAX_IMAGE_PIXELS = 20_000_000
MAX_SECONDS = 60
MAX_OCR_SECONDS = 20
MAX_BLOCKS = 5_000
MAX_TEXT_CHARS = 500_000
PREVIEW_SCALE = 1.5
OCR_SCALE = 2.0


class ExtractionError(ValueError):
    """A document cannot be processed within the supported local limits."""


def _remaining(start: float) -> float:
    remaining = MAX_SECONDS - (time.monotonic() - start)
    if remaining <= 0:
        raise ExtractionError("Document processing exceeded the 60 second limit.")
    return remaining


def _check_pixels(width: float, height: float, scale: float = 1) -> None:
    if width <= 0 or height <= 0:
        raise ExtractionError("Document page has invalid dimensions.")
    if math.ceil(width * scale) * math.ceil(height * scale) > MAX_IMAGE_PIXELS:
        raise ExtractionError("Document page exceeds the 20 million pixel limit.")


def _bbox(rect: Any, width: float, height: float) -> list[float]:
    x0, y0, x1, y1 = map(float, rect)
    result = [x0 / width, y0 / height, x1 / width, y1 / height]
    return [round(max(0.0, min(1.0, value)), 6) for value in result]


def _pdf_bbox(page: pymupdf.Page, rect: Any) -> list[float]:
    # PDF text coordinates are unrotated; previews honor page rotation.
    transformed = pymupdf.Rect(rect) * page.rotation_matrix
    return _bbox(transformed, page.rect.width, page.rect.height)


def _new_block(number: int, index: int, text: str, bbox: list[float],
               kind: str, engine: str, **extra: Any) -> dict[str, Any]:
    return {"id": f"p{number}-b{index}", "text": text.strip(), "bbox": bbox,
            "kind": kind, "engine": engine, **extra}


def _configure_tesseract() -> None:
    configured = os.getenv("TESSERACT_CMD")
    fallback = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    if configured:
        pytesseract.pytesseract.tesseract_cmd = configured
    elif not shutil.which("tesseract") and fallback.is_file():
        pytesseract.pytesseract.tesseract_cmd = str(fallback)


def _ocr(image: Image.Image, number: int, start: float,
         warnings: list[str]) -> list[dict[str, Any]]:
    _configure_tesseract()
    _check_pixels(*image.size)
    languages = os.getenv("OCR_LANGUAGES", "eng+por")
    processed = ImageOps.autocontrast(ImageOps.grayscale(image))
    try:
        data = pytesseract.image_to_data(
            processed, lang=languages, config="--psm 3",
            output_type=pytesseract.Output.DICT,
            timeout=min(MAX_OCR_SECONDS, _remaining(start)),
        )
    except pytesseract.TesseractNotFoundError as exc:
        raise ExtractionError("OCR requires the local Tesseract executable.") from exc
    except RuntimeError as exc:
        raise ExtractionError("OCR exceeded its processing time limit.") from exc
    except pytesseract.TesseractError as exc:
        raise ExtractionError(
            "OCR failed. Verify Tesseract and the configured language data."
        ) from exc

    groups: dict[tuple[int, int], list[int]] = {}
    for index, word in enumerate(data["text"]):
        if str(word).strip() and float(data["conf"][index]) >= 0:
            key = (data["block_num"][index], data["par_num"][index])
            groups.setdefault(key, []).append(index)
    blocks = []
    for indices in groups.values():
        text = " ".join(str(data["text"][i]).strip() for i in indices)
        x0 = min(data["left"][i] for i in indices)
        y0 = min(data["top"][i] for i in indices)
        x1 = max(data["left"][i] + data["width"][i] for i in indices)
        y1 = max(data["top"][i] + data["height"][i] for i in indices)
        confidence = round(sum(float(data["conf"][i]) for i in indices) / len(indices), 1)
        blocks.append(_new_block(number, len(blocks), text,
                                 _bbox([x0, y0, x1, y1], *image.size),
                                 "ocr", "tesseract", confidence=confidence))
    warnings.append(
        f"Page {number}: OCR text and coordinates are estimates; scanned tables "
        "remain text and require manual structure verification."
    )
    return blocks


def _digital_blocks(page: pymupdf.Page, number: int,
                    warnings: list[str]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    table_rects: list[pymupdf.Rect] = []
    try:
        tables = page.find_tables().tables
        for table in tables:
            rows = [[str(cell or "").strip() for cell in row] for row in table.extract()]
            if not rows or not any(any(row) for row in rows):
                continue
            text = "\n".join(" | ".join(row) for row in rows)
            blocks.append(_new_block(number, len(blocks), text,
                                     _pdf_bbox(page, table.bbox), "table", "pymupdf",
                                     rows=rows))
            table_rects.append(pymupdf.Rect(table.bbox))
        if tables:
            warnings.append(f"Page {number}: table structure is inferred from PDF geometry.")
    except (ValueError, RuntimeError, AttributeError):
        warnings.append(f"Page {number}: structured table extraction was unavailable.")

    for block in page.get_text("blocks", sort=True):
        if block[6] != 0 or not block[4].strip():
            continue
        rect = pymupdf.Rect(block[:4])
        if any(table.contains(rect) for table in table_rects):
            continue
        blocks.append(_new_block(number, len(blocks), block[4],
                                 _pdf_bbox(page, rect), "text", "pymupdf"))
    # Stable reading order also keeps table blocks next to adjacent text.
    blocks.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    for index, block in enumerate(blocks):
        block["id"] = f"p{number}-b{index}"
    return blocks


def _render_pdf(page: pymupdf.Page, scale: float) -> Image.Image:
    _check_pixels(page.rect.width, page.rect.height, scale)
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    return Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)


def _check_output_limits(pages: list[dict[str, Any]]) -> None:
    blocks = [block for page in pages for block in page["blocks"]]
    if len(blocks) > MAX_BLOCKS or sum(len(block["text"]) for block in blocks) > MAX_TEXT_CHARS:
        raise ExtractionError("Extracted document exceeds the supported text limit.")


def extract_document(source: Path, output_dir: Path,
                     engine: str = "offline") -> dict[str, Any]:
    """Extract a validated PDF/PNG/JPEG into local previews and evidence blocks.

    The caller must additionally run this function in a killable worker process
    with a hard timeout: native PDF conversion cannot be interrupted by Python's
    monotonic deadline. `source` and `output_dir` are server-selected paths.
    """
    source, output_dir = Path(source), Path(output_dir)
    if not source.is_file() or source.stat().st_size > MAX_FILE_BYTES:
        raise ExtractionError("Document is missing or exceeds the 10 MiB file limit.")
    if engine not in {"offline", "docling-native"}:
        raise ExtractionError("Unsupported extraction engine.")
    start = time.monotonic()
    output_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    pages: list[dict[str, Any]] = []
    with source.open("rb") as handle:
        magic = handle.read(8)
    if magic.startswith(b"%PDF-"):
        try:
            document = pymupdf.open(source)
        except (pymupdf.FileDataError, RuntimeError) as exc:
            raise ExtractionError("The PDF could not be read.") from exc
        with document:
            if document.needs_pass:
                raise ExtractionError("Encrypted PDFs are not supported.")
            if not 1 <= len(document) <= MAX_PAGES:
                raise ExtractionError("PDF must contain between 1 and 20 pages.")
            for index, page in enumerate(document):
                _remaining(start)
                number = index + 1
                preview = _render_pdf(page, PREVIEW_SCALE)
                image_path = output_dir / f"page-{number}.png"
                preview.save(image_path, format="PNG")
                blocks = _digital_blocks(page, number, warnings)
                # A textless scan must use actual OCR, never a fixture transcript.
                if len(" ".join(block["text"] for block in blocks).strip()) < 15:
                    blocks = _ocr(_render_pdf(page, OCR_SCALE), number, start, warnings)
                pages.append({"number": number, "width": preview.width,
                              "height": preview.height, "image_path": str(image_path),
                              "blocks": blocks})
                _check_output_limits(pages)
    else:
        try:
            with Image.open(source) as original:
                if original.format not in {"PNG", "JPEG"}:
                    raise ExtractionError("Only PDF, PNG and JPEG documents are supported.")
                if getattr(original, "n_frames", 1) != 1:
                    raise ExtractionError("Animated or multi-frame images are not supported.")
                _check_pixels(*original.size)
                image = ImageOps.exif_transpose(original).convert("RGB")
                image.load()
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
            raise ExtractionError("The image could not be safely decoded.") from exc
        image_path = output_dir / "page-1.png"
        image.save(image_path, format="PNG")
        pages.append({"number": 1, "width": image.width, "height": image.height,
                      "image_path": str(image_path),
                      "blocks": _ocr(image, 1, start, warnings)})

    if engine == "docling-native":
        from .docling_adapter import extract_with_docling_native
        if magic.startswith(b"%PDF-"):
            pages = extract_with_docling_native(source, pages, start)
        warnings.append("Docling native PDF text parser; OCR uses Tesseract and ruled tables use PyMuPDF. No layout models run.")
    _remaining(start)
    _check_output_limits(pages)
    if not any(page["blocks"] for page in pages):
        warnings.append("No readable text was found in this document.")
    return {"pages": pages, "warnings": list(dict.fromkeys(warnings)), "engine": engine}
