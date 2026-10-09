# Synthetic regression evaluation

Run `python evals/run.py` after installing `backend/requirements.txt` and local
Tesseract with English and Portuguese language data. The runner reads only the
versioned fixture manifest and documents. It uses the actual extraction pipeline,
including OCR on the raster PNG and raster-only PDF, then evaluates each retrieval
mode over the caller-authorized corpus. It never reads uploads or a runtime database.

`dataset.jsonl` version 1.0.0 contains 18 authored cases: English and Portuguese
digital evidence, page identity, raster OCR, a reviewed bilingual vocabulary query,
a natural frequency question, absent facts, a misleading near-match, prompt
injection and both permitted and forbidden access to a fictional restricted memo.
An `expected` list represents acceptable evidence alternatives, including the two
equivalent scan formats. An empty list requires an insufficient-evidence response.

The measured output is `results.json`. It includes dataset and fixture SHA-256
hashes, implementation hashes, extraction engines, Python/dependency versions, individual outcomes and
local timing. Re-running replaces that report with the actual new measurements.

| Metric | Definition |
| --- | --- |
| Recall@3 | Fraction of answerable cases with at least one expected document, page and evidence quote in the first three passages. |
| MRR@3 | Mean reciprocal rank of the first such passage, or zero if absent from the first three. |
| Citation correctness | Fraction of issued citations matching expected evidence, with identity, page, coordinates and literal quote also validated against retrieved passages. |
| Unsupported refusal accuracy | Fraction of cases with no expected evidence returning an explicit refusal and no invented answer. |
| Answer outcome accuracy | Fraction of all cases either answering with the expected cited evidence or correctly refusing. |
| Mean latency | Single-run local retrieval plus extractive answering latency, excluding extraction, HTTP and queuing. |

Coordinate validation proves that citations retain retrieved source rectangles.
It is not an independent human-annotated measurement of OCR rectangle accuracy.
The offline answer quotes one complete passage and requires all meaningful
question concepts to appear in it. It deliberately declines inference, arithmetic,
general paraphrases outside the reviewed vocabulary and multi-passage synthesis.

This small, deliberately readable regression set is not a representative quality
benchmark. Vector mode uses 384-dimensional signed feature hashing and a reviewed
English/Portuguese vocabulary, not a pretrained semantic embedding model. The
evaluation performs zero provider API requests. HTTP authorization, malicious
uploads, source access and extraction limits have separate backend tests.
