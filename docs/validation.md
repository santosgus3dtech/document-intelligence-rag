# Validation record

Scope: first usable local portfolio release. All documents and screenshots are
synthetic. No production services or source reference repositories were changed.

## Automated checks

- Combined Windows/Python 3.11 suite with a real pgvector database: **59 passed,
  4 optional Docling skips**. One Starlette warning deprecates its httpx test
  transport; no test failures.
- Final Linux Docker suite against a dedicated validation database: **59 passed,
  4 optional skips**. Application and database health checks passed. An initial
  container run exposed a hybrid search limit=20 mismatch; it was fixed and
  included in the PostgreSQL regression test before this final passing run.
- Separate installed Docling 2.135.0 environment: **17 extraction tests passed**,
  including the four optional rotated-PDF cases. Actual worker conversions also
  passed for a digital PDF and an unrelated raster image.
- TypeScript and Vite production build: passed. npm audit at installation reported
  zero vulnerabilities for the installed frontend tree.
- Real PostgreSQL **17.11** and pgvector **0.8.7** integration: passed vector and
  hybrid retrieval, permitted/restricted uploads, unauthorized candidate/file
  requests and unrelated hashing-collision suppression.
- Versioned synthetic evaluation: 18 cases, Recall@3=1.0 for all modes; exact
  results/definitions/hashes are in `evals/`. This is a regression set.

Focused tests cover actual Tesseract OCR in both supported languages, digital
tables, coordinates at four rotations, valid/malformed/encrypted/oversized PDF
and image uploads, traversal, pixel/page limits, failure/timeout states, server
identity versus forged role headers, every source request, expected refusals,
embedded instructions and forged citation provenance. Direct ASGI tests verify
missing/spoofed Content-Length, streamed oversized bodies and disconnect handling.
Concurrent tests prove two validation workers and the atomic 100-document quota.

## Browser checks

Used Codex In-app Browser through its supported UI automation API. No Playwright
fallback was needed. Desktop: **1536x1024** (concept's native size). Mobile:
**390x844**. Browser console contained no application errors during the main
workflows. The mobile document body width and scroll width were both 390px.

| Workflow | Observed result |
|---|---|
| English question | Coolant replacement returned literal 500-hour evidence, citation, page 1 and a yellow rectangle over that exact source line. |
| Portuguese question | Supplier inspection returned the 90-day source sentence from the Portuguese PDF. |
| Real upload/OCR | Browser file chooser uploaded the synthetic PNG; queued/processing became Ready; scoped question returned scanner contact with OCR coordinates. |
| Search | Vector search for Papel A4 returned the receipt table; clicking it selected the source; extracted table displayed rows/cells. |
| No evidence | Inventor question returned Insufficient evidence without a new citation; unrelated search returned No matching passages. |
| Source | Page navigation changed 1/2 to 2/2; citation selected the correct page; 150% zoom preserved overlay alignment and scrollable source. |
| Permissions | Reviewer displayed/opened the fictional restricted memo. Viewer removed the document and source; backend tests additionally verify HTTP denials. |
| Error/loading | Invalid synthetic PDF displayed the validation error; upload and evidence retrieval showed disabled/loading states. |
| Empty filter | Nonexistent document filter displayed No matching documents and recovered when cleared. |
| Mobile | Question, citation-to-source, zoom and library filtering remained usable with no body overflow. |

Sanitized screenshots: `screenshots/desktop.jpg`, `mobile-answer.jpg`,
`mobile-source.jpg`, `upload-error.jpg`. Design comparison and intentional
functional differences are recorded in `design-notes.md`.

Remaining limits: one browser engine, no human OCR accuracy benchmark, no
representative semantic retrieval benchmark, no remote generator, and no
production browser sign-in. Scanned tables are OCR text. The local demo identity
switch is intentionally not a security boundary for public hosting.
