# Reference audit

Read-only review of the three local reference repositories before equivalent
components were implemented. Original repositories were preserved. No source
code, private documents, runtime databases, credentials or deployment settings
were imported.

| Reference | Reviewed behavior | License found | Decision |
|---|---|---|---|
| computer-vision-ocr-lab | OpenCV resize, grayscale, median/Otsu preprocessing; Tesseract text wrapper; preprocessing tests | No LICENSE/COPYING found | Independently implement OCR with word boxes, page coordinates and time limits. No copied code. |
| secure-document-library-demo | Filename validation, resolved-path containment, upload handling and document access | MIT, Gustavo Santos, 2026 | Independently implement validation/containment patterns. Replace role headers with server sessions and configured bearer identities; parse content beyond magic bytes. |
| manufacturing-knowledge-agent | BM25, deterministic ranking, citation generation and versioned evaluation | MIT, Gustavo Santos, 2026 | Independently implement accent-aware ranking and evaluation. Authorize before candidate access; preserve source rectangles and validate quoted citations. |

This repository has independent Git history. The implementation is licensed
AGPL-3.0-or-later because its PDF extraction/rendering dependency PyMuPDF is
distributed under AGPL or a commercial license. Tesseract is Apache-2.0;
Pillow uses its permissive HPND license; FastAPI, React, Vite and TypeScript use
permissive licenses. Optional Docling is MIT; its model artifacts and transitive
dependencies have their own licenses. PostgreSQL and pgvector use the PostgreSQL
license. Review dependency and model licenses before a different distribution.
