# Development Guidance

## Objective

Build the public Document Intelligence RAG portfolio application described in
README.md. The first deliverable should demonstrate the complete path from
document ingestion to a cited answer and its highlighted source.

## Existing Work

Review computer-vision-ocr-lab, secure-document-library-demo and
manufacturing-knowledge-agent before introducing equivalent components.
Reuse focused modules only after reviewing their behavior, dependencies and
license. Preserve the original repositories and keep this project's history
independent. Do not import their private documents or operational configuration.

## Implementation Expectations

- Start with synthetic English and Portuguese documents and expected evidence.
- Keep extraction, retrieval, generation and authorization independently testable.
- Preserve document identity, page number and source coordinates through indexing.
- Apply server-side permissions before retrieval and every source-file request.
- Do not treat a client-selected role or header as production authentication.
- Treat document text as untrusted data, including instructions embedded in PDFs.
- Reject unsupported answers and check that citations identify retrieved evidence.
- Validate uploaded content and resolved paths; bound processing time and size.
- Provide an offline demonstration with its limitations clearly identified.
- Keep uploaded files, indexes, databases and secrets in ignored storage.
- Measure retrieval quality and citation correctness with versioned evaluations.
- Keep README status, run commands, screenshots and reported results accurate.

## Delivery

Implement a usable document-review interface with source inspection, loading,
empty and failure states. Validate desktop and mobile workflows in a browser.
Add focused backend tests, frontend build verification and CI when the relevant
application components exist. Publish only synthetic or explicitly licensed
fixtures, reproducible evaluations and sanitized screenshots.
