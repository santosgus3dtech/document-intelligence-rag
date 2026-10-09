"""An intentionally conservative offline extractive answering boundary."""

from __future__ import annotations

import re
from time import perf_counter
from typing import Any

from .retrieval import concepts

INJECTION = re.compile(
    r"ignore\s+(?:all\s+)?(?:previous|prior|system)|"
    r"(?:system|developer)\s+(?:prompt|message)|"
    r"(?:reveal|disclose|print|exfiltrate)\s+(?:the\s+)?(?:secret|password|token|api.key)|"
    r"(?:ignore|desconsidere)\s+(?:todas?\s+)?(?:as\s+)?(?:instrucoes|instruções)|"
    r"<\|(?:system|assistant|im_start)\|>|"
    r"(?:follow|execute|obey)\s+(?:these|the following)\s+instructions",
    re.IGNORECASE,
)
LIMITATIONS = (
    "Offline extractive mode quotes retrieved passages. It does not infer, "
    "calculate, summarize across documents, or verify that a source is true."
)


def validate_citations(citations: list[dict[str, Any]], hits: list[dict[str, Any]]) -> bool:
    """Reject invented provenance or quotes absent from the retrieved passage."""
    by_id = {str(hit["id"]): hit for hit in hits}
    for citation in citations:
        hit = by_id.get(str(citation.get("id", "")))
        if hit is None:
            return False
        for key in ("document_id", "page", "bbox"):
            if citation.get(key) != hit.get(key):
                return False
        quote = citation.get("quote", "")
        if not isinstance(quote, str) or not quote.strip() or quote not in hit["text"]:
            return False
    return True


def answer(question: str, hits: list[dict[str, Any]]) -> dict[str, Any]:
    """Return literal evidence only, with source-bound citations or a refusal."""
    started = perf_counter()
    question_terms = concepts(question)
    candidates: list[tuple[float, dict[str, Any]]] = []
    if question_terms and not INJECTION.search(question):
        for hit in hits:
            text = str(hit["text"])
            # A retrieved document is data, never an instruction source.
            if INJECTION.search(text):
                continue
            overlap = question_terms & concepts(text)
            coverage = len(overlap) / len(question_terms)
            # Every meaningful query term must occur (or map to a reviewed
            # bilingual equivalent). One related noun must not support an
            # absent qualifier such as "calibration" versus "replacement".
            if overlap and coverage == 1.0:
                candidates.append((coverage, hit))
    candidates.sort(key=lambda item: (-item[0], -float(item[1].get("score", 0))))
    citations = []
    if candidates:
        # Limit to one literal passage. Extracting one passage avoids unsupported
        # connective claims; the interface can still inspect all retrieved hits.
        hit = candidates[0][1]
        quote = str(hit["text"])
        citations = [{**hit, "quote": quote, "citation_id": 1}]
    if not citations or not validate_citations(citations, hits):
        return {
            "answer": "Insufficient evidence in the documents you can access. Try a more specific question or upload a relevant source.",
            "status": "insufficient_evidence",
            "unsupported": True,
            "citations": [],
            "provider": "offline-extractive",
            "mode": "offline-extractive",
            "latency_ms": round((perf_counter() - started) * 1000, 3),
            "limitations": LIMITATIONS,
        }
    return {
        "answer": f'Retrieved evidence: “{citations[0]["quote"]}” [1]',
        "status": "answered",
        "unsupported": False,
        "citations": citations,
        "provider": "offline-extractive",
        "mode": "offline-extractive",
        "latency_ms": round((perf_counter() - started) * 1000, 3),
        "limitations": LIMITATIONS,
    }
