"""Evaluate real fixture extraction, retrieval, citations and refusals locally.

Run from the repository root: python evals/run.py
Only files listed in the versioned synthetic manifest are read. No uploaded
documents, application database, network or provider API is accessed.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import sys
import tempfile
from pathlib import Path
from statistics import mean
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.extraction import extract_document  # noqa: E402
from app.generation import answer, validate_citations  # noqa: E402
from app.retrieval import search  # noqa: E402


def normalized(text: str) -> str:
    return " ".join(text.split()).casefold()


def relevant(hit: dict, targets: list[dict]) -> bool:
    evidence = hit.get("quote", hit["text"])
    return any(hit["document_id"] == target["document_id"] and hit["page"] == target["page"]
               and normalized(target["quote"]) in normalized(evidence) for target in targets)


def run() -> dict:
    manifest_path = ROOT / "fixtures" / "manifest.json"
    dataset_path = ROOT / "evals" / "dataset.jsonl"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = [json.loads(line) for line in dataset_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    corpus = []
    extraction_timings = []
    engines = set()
    with tempfile.TemporaryDirectory(prefix="dirag-eval-") as temporary:
        for fixture in manifest["documents"]:
            started = perf_counter()
            extracted = extract_document(ROOT / "fixtures" / fixture["filename"], Path(temporary) / fixture["id"])
            extraction_timings.append((perf_counter() - started) * 1000)
            for page in extracted["pages"]:
                for block in page["blocks"]:
                    engines.add(block["engine"])
                    corpus.append({**block, "id": f'{fixture["id"]}:{block["id"]}',
                                   "document_id": fixture["id"], "document_title": fixture["title"],
                                   "page": page["number"], "access": fixture["access"]})
    modes = {}
    for mode in ("lexical", "vector", "hybrid"):
        recalls, reciprocal_ranks, latencies, citation_validity, refusal_success, support_success = [], [], [], [], [], []
        rows = []
        for case in cases:
            # Mirror the service boundary: ACL scope is resolved before ranking.
            allowed = [chunk for chunk in corpus if chunk["access"] == "public" or case["access"] == "restricted"]
            started = perf_counter()
            hits = search(allowed, case["question"], mode=mode, k=3)
            response = answer(case["question"], hits)
            latency = (perf_counter() - started) * 1000
            latencies.append(latency)
            ranks = [index for index, hit in enumerate(hits, start=1) if relevant(hit, case["expected"])]
            if case["expected"]:
                recalls.append(float(bool(ranks)))
                reciprocal_ranks.append(1 / min(ranks) if ranks else 0)
            else:
                refused_correctly = (response["unsupported"] and response["status"] == "insufficient_evidence"
                                     and not response["citations"])
                refusal_success.append(float(refused_correctly))
            correct = validate_citations(response["citations"], hits)
            for citation in response["citations"]:
                citation_validity.append(float(correct and relevant(citation, case["expected"])))
            supported_correctly = (not response["unsupported"] and response["status"] == "answered"
                                   and bool(response["citations"])
                                   and all(relevant(item, case["expected"]) for item in response["citations"]))
            outcome_correct = supported_correctly if case["expected"] else refused_correctly
            support_success.append(float(outcome_correct))
            rows.append({"id": case["id"], "category": case["category"], "retrieval_hit_at_3": bool(ranks),
                         "reciprocal_rank_at_3": round(1 / min(ranks), 4) if ranks else 0,
                         "refused": response["unsupported"], "outcome_correct": bool(outcome_correct),
                         "citations_correct": correct and all(relevant(item, case["expected"]) for item in response["citations"]),
                         "latency_ms": round(latency, 3)})
        modes[mode] = {
            "answerable_cases": len(recalls), "unsupported_cases": len(refusal_success),
            "recall_at_3": round(mean(recalls), 4), "mrr_at_3": round(mean(reciprocal_ranks), 4),
            "citation_correctness": round(mean(citation_validity), 4) if citation_validity else None,
            "issued_citations": len(citation_validity),
            "unsupported_refusal_accuracy": round(mean(refusal_success), 4),
            "answer_outcome_accuracy": round(mean(support_success), 4),
            "mean_retrieval_answer_latency_ms": round(mean(latencies), 3), "cases": rows,
        }
    return {
        "dataset_version": "1.0.0", "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "fixture_manifest_version": manifest["version"], "fixture_documents": len(manifest["documents"]),
        "vector_model": "local-feature-hashing-bilingual-v1-384",
        "source_sha256": {filename: hashlib.sha256((ROOT / filename).read_bytes()).hexdigest()
                          for filename in ("backend/app/extraction.py", "backend/app/retrieval.py", "backend/app/generation.py", "evals/run.py")},
        "extracted_chunks": len(corpus), "extraction_engines": sorted(engines),
        "fixture_sha256": {item["filename"]: hashlib.sha256((ROOT / "fixtures" / item["filename"]).read_bytes()).hexdigest() for item in manifest["documents"]},
        "python": platform.python_version(),
        "dependencies": {package: importlib.metadata.version(package) for package in ("PyMuPDF", "Pillow", "pytesseract")},
        "total_extraction_latency_ms": round(sum(extraction_timings), 3),
        "provider_requests": 0,
        "scope": "Synthetic fixture extraction and authorized-corpus retrieval; HTTP authorization is tested separately.",
        "limitations": [
            f"{len(cases)} authored cases are a regression dataset, not a representative benchmark.",
            "Vector retrieval uses 384-dimensional local feature hashing with a reviewed bilingual vocabulary, not semantic embeddings.",
            "Citation correctness requires exact expected evidence text, document identity and page, plus retrieved provenance validation.",
            "Recall@3 counts one acceptable evidence alternative per answerable case; MRR is truncated at 3.",
            "Latency is a single warm-process local run and excludes HTTP, queuing and document upload.",
            "No provider requests were performed; paid API usage and provider answer quality were not evaluated.",
        ],
        "modes": modes,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run the versioned synthetic regression evaluation.")
    parser.add_argument("--output", type=Path, default=ROOT / "evals" / "results.json")
    parser.add_argument("--check", action="store_true", help="Fail if authored regression expectations are not met.")
    arguments = parser.parse_args()
    result = run()
    output = arguments.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    for mode, summary in result["modes"].items():
        print(f'{mode}: Recall@3={summary["recall_at_3"]:.4f} MRR@3={summary["mrr_at_3"]:.4f} '
              f'citation={summary["citation_correctness"]} refusal={summary["unsupported_refusal_accuracy"]:.4f} '
              f'answer-outcome={summary["answer_outcome_accuracy"]:.4f}')
    print(f"Measured results: {output}")
    if arguments.check:
        if any(summary["recall_at_3"] < 0.9 or summary["citation_correctness"] != 1.0
               or summary["unsupported_refusal_accuracy"] != 1.0 or summary["answer_outcome_accuracy"] != 1.0
               for summary in result["modes"].values()):
            raise SystemExit("Synthetic regression expectations failed. Inspect the evaluation report.")
