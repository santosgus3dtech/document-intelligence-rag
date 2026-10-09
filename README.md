# Document Intelligence RAG

A document intelligence workspace for turning PDFs and scanned documents into
searchable evidence, structured data and answers with inspectable citations.

## Development Status

Project initialization. Application code, a runnable demo, benchmarks and
screenshots are planned and are not implemented yet.

## Planned Workflow

1. Upload a digital PDF, scanned PDF or image.
2. Extract text, document structure and tables while retaining page coordinates.
3. Index passages for lexical and vector retrieval.
4. Ask a question within the documents the current user is permitted to access.
5. Review an answer with citations, or an explicit insufficient-evidence response.
6. Open each cited passage highlighted in its source document.

## Planned Stack

- Python, FastAPI and Pydantic for application services and typed contracts.
- Docling for document conversion, OCR and source provenance.
- PostgreSQL and pgvector for persistence and hybrid retrieval.
- React and TypeScript for document review and source inspection.
- An optional language-model provider behind an explicit application boundary.
- Docker Compose, pytest and GitHub Actions for reproducible verification.

These are implementation choices to validate during development, not installed
dependencies or working integrations.

## Implementation Roadmap

1. Synthetic document fixtures and a versioned question-and-evidence dataset.
2. Validated uploads, document processing and page-aware extraction.
3. Lexical retrieval followed by vector and hybrid search comparisons.
4. Grounded answers, citation checks and source highlighting.
5. Server-side document permissions enforced before retrieval.
6. Evaluation reports, an offline demo path, tests, CI and container setup.
7. Desktop and mobile screenshots, architecture documentation and a demo video.

Evaluation should report retrieval Recall@K and MRR, citation correctness,
unsupported-answer handling, latency and measured provider usage where available.
Results will be published only after the corresponding evaluations run.

## Related Portfolio Projects

- [Computer Vision OCR Lab](https://github.com/santosgus3dtech/computer-vision-ocr-lab):
  preprocessing, OCR boundaries and evaluation patterns.
- [Secure Document Library Demo](https://github.com/santosgus3dtech/secure-document-library-demo):
  defensive upload handling and document-access patterns.
- [Manufacturing Knowledge Agent](https://github.com/santosgus3dtech/manufacturing-knowledge-agent):
  retrieval, citations and evaluation patterns.

Their reusable code must be reviewed before adoption. Private documents,
databases, accounts and deployment configuration are not development fixtures.

## Public Data Boundary

The public demo will use synthetic or explicitly licensed sample documents.
Uploaded documents, local indexes, credentials, runtime databases and provider
responses belong in ignored local storage. Sensitive content must not be sent
to a remote model without an explicit, visible processing policy.

## Technical References

- [Docling document model and provenance](https://docling-project.github.io/docling/reference/docling_document/)
- [pgvector](https://github.com/pgvector/pgvector)
