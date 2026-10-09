"""Optional model-free Docling PDF parser with independently tested OCR/tables.

No layout, OCR or table model runs inside Docling NativePdfPipeline.
The installed package includes optional ML dependencies, but this path never
downloads weights or sends document contents to a remote service.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .extraction import (
    ExtractionError, MAX_FILE_BYTES, MAX_PAGES, _bbox,
    _new_block, _remaining,
)


def extract_with_docling_native(source: Path, pages: list[dict[str, Any]],
                                start: float) -> list[dict[str, Any]]:
    """Use Docling's actual model-free PDF parser, retaining fallback OCR/tables."""
    # Document workers are isolated subprocesses; enforce offline model-library
    # behavior without changing the API's optional remote generation provider.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        from docling.datamodel.base_models import ConversionStatus, InputFormat
        from docling.datamodel.pipeline_options import NativePdfPipelineOptions
        from docling.document_converter import DocumentConverter, NativePdfFormatOption
    except ImportError as exc:
        raise ExtractionError("Install Docling 2.135.0 optional requirements to use its native parser.") from exc
    options = NativePdfPipelineOptions(
        document_timeout=_remaining(start), enable_remote_services=False,
        allow_external_plugins=False, parser_threads=2,
    )
    try:
        converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF],
            format_options={InputFormat.PDF: NativePdfFormatOption(pipeline_options=options)},
        )
        result = converter.convert(source, max_num_pages=MAX_PAGES, max_file_size=MAX_FILE_BYTES)
    except Exception as exc:
        raise ExtractionError("Docling native PDF conversion failed.") from exc
    _remaining(start)
    if result.status != ConversionStatus.SUCCESS:
        raise ExtractionError("Docling native PDF conversion did not complete.")
    document = result.document
    extracted: dict[int, list[dict[str, Any]]] = {page["number"]: [] for page in pages}
    for item, _level in document.iterate_items():
        text = str(getattr(item, "text", "")).strip()
        if not text:
            continue
        for prov in getattr(item, "prov", []):
            number = prov.page_no
            if number not in extracted or number not in document.pages:
                raise ExtractionError("Docling returned an invalid evidence page.")
            size = document.pages[number].size
            box = prov.bbox.to_top_left_origin(size.height)
            extracted[number].append(_new_block(
                number, len(extracted[number]), text,
                _bbox([box.l, box.t, box.r, box.b], size.width, size.height),
                "text", "docling-native",
            ))
    for page in pages:
        parsed = extracted[page["number"]]
        if not parsed:
            continue
        retained = [block for block in page["blocks"] if block["kind"] in {"table", "ocr"}]
        tables = [block["bbox"] for block in retained if block["kind"] == "table"]
        parsed = [block for block in parsed if not any(
            table[0] <= block["bbox"][0] and table[1] <= block["bbox"][1]
            and table[2] >= block["bbox"][2] and table[3] >= block["bbox"][3]
            for table in tables)]
        page["blocks"] = sorted(retained + parsed, key=lambda block: (block["bbox"][1], block["bbox"][0]))
        for index, block in enumerate(page["blocks"]):
            block["id"] = f"p{page['number']}-b{index}"
    return pages
