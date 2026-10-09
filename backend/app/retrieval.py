"""Deterministic retrieval over an already authorized collection of passages.

The caller applies authorization before calling this module. The local vector
model uses signed feature hashing, not pretrained semantic embeddings. It is
deliberately small, reproducible and usable without downloads or provider APIs.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import Counter
from typing import Any

VECTOR_DIMENSIONS = 384
STOP_WORDS = frozenset(
    "a an and are as at be by can do does for from how i in is it of on or that the "
    "this to was were what when where which who why with would should please tell me "
    "if must need needs required recommended specified per before after action value values setting "
    "about document documents according based answer evidence source sources "
    "o os a as um uma uns umas e ou de da das do dos em no na nos nas para por com "
    "que qual quais como quando onde quem porque se ser esta este esse essa isto "
    "eu me diga documento documentos segundo resposta evidencia fonte fontes deve devem "
    "necessario necessaria recomendado recomendada antes depois acao valor valores".split()
)

# This reviewed bilingual vocabulary supports a few documented demo concepts.
# It does not claim to be a general translation or language understanding model.
_CONCEPT_GROUPS = (
    ("temperature", "temperatura", "thermal", "temperatures"),
    ("inspection", "inspect", "inspected", "inspecao", "inspecionar", "check", "verificar"),
    ("interval", "intervalo", "frequency", "frequencia", "periodicity", "often"),
    ("maintenance", "manutencao", "service"),
    ("days", "day", "dias", "dia"),
    ("receipt", "receiving", "recebimento", "receber"),
    ("storage", "armazenamento", "store", "armazenar"),
    ("supplier", "fornecedor", "suppliers", "fornecedores"),
    ("damaged", "damage", "danificado", "danificados", "avaria", "avarias"),
    ("package", "packages", "packaging", "embalagem", "embalagens", "volumes"),
    ("humidity", "umidade", "humidade"),
    ("maximum", "maximo", "maxima", "limit", "limite"),
    ("minimum", "minimo", "minima"),
    ("approval", "approve", "aprovacao", "aprovar"),
    ("hours", "hour", "horas", "hora"),
    ("replace", "replaced", "replacement", "substituir", "substituicao", "trocar"),
    ("filter", "filters", "filtro", "filtros"),
    ("emergency", "emergencia"),
    ("contact", "contato", "contacto"),
)
CONCEPTS = {word: group[0] for group in _CONCEPT_GROUPS for word in group}


def tokenize(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(char for char in normalized if not unicodedata.combining(char))
    return [token for token in re.findall(r"[\w]+", plain, flags=re.UNICODE) if token not in STOP_WORDS]


def concepts(text: str) -> set[str]:
    return {CONCEPTS.get(token, token) for token in tokenize(text)}


def embed_text(text: str) -> list[float]:
    """Return a normalized 384-dimensional local feature-hashing vector."""
    tokens = [CONCEPTS.get(token, token) for token in tokenize(text)]
    counts: Counter[str] = Counter(f"w:{token}" for token in tokens)
    # Word bigrams retain some phrase order; no external model or network is used.
    counts.update(f"b:{left}:{right}" for left, right in zip(tokens, tokens[1:]))
    vector = [0.0] * VECTOR_DIMENSIONS
    for feature, count in counts.items():
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "little") % VECTOR_DIMENSIONS
        sign = 1.0 if digest[4] & 1 else -1.0
        weight = 1.0 + math.log(count)
        vector[bucket] += sign * weight * (0.5 if feature.startswith("b:") else 1.0)
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def search(
    chunks: list[dict[str, Any]], query: str, mode: str = "hybrid", k: int = 5
) -> list[dict[str, Any]]:
    """Rank only supplied passages; all original provenance fields are retained."""
    if mode not in {"lexical", "vector", "hybrid"}:
        raise ValueError("mode must be lexical, vector or hybrid")
    if not 1 <= k <= 20:
        raise ValueError("k must be between 1 and 20")
    query_tokens = set(tokenize(query))
    if not chunks or not query_tokens:
        return []
    counts = [Counter(tokenize(str(chunk["text"]))) for chunk in chunks]
    lengths = [sum(count.values()) for count in counts]
    average_length = sum(lengths) / len(lengths) or 1.0
    document_frequency: Counter[str] = Counter()
    for count in counts:
        document_frequency.update(count.keys())
    lexical: list[float] = []
    for count, length in zip(counts, lengths, strict=True):
        score = 0.0
        for token in query_tokens:
            frequency = count[token]
            if frequency:
                inverse = math.log(1.0 + (len(chunks) - document_frequency[token] + 0.5)
                                   / (document_frequency[token] + 0.5))
                score += inverse * frequency * 2.5 / (
                    frequency + 1.5 * (0.25 + 0.75 * length / average_length)
                )
        lexical.append(score)
    query_vector = embed_text(query)
    query_concepts = concepts(query)
    vector = [
        # Hash collisions must never create a result without an actual shared
        # canonical term. Similarity is reproducible, but not semantic proof.
        max(0.0, cosine(query_vector, embed_text(str(chunk["text"]))))
        if query_concepts & concepts(str(chunk["text"])) else 0.0
        for chunk in chunks
    ]

    def stable_key(index: int) -> tuple[str, int, str]:
        chunk = chunks[index]
        return str(chunk["document_id"]), int(chunk["page"]), str(chunk["id"])

    lexical_order = sorted(range(len(chunks)), key=lambda i: (-lexical[i], stable_key(i)))
    vector_order = sorted(range(len(chunks)), key=lambda i: (-vector[i], stable_key(i)))
    lexical_rank = {index: rank for rank, index in enumerate(lexical_order, start=1) if lexical[index] > 0}
    vector_rank = {index: rank for rank, index in enumerate(vector_order, start=1) if vector[index] > 0}
    max_lexical = max(lexical, default=0) or 1
    scores = []
    for index in range(len(chunks)):
        if mode == "lexical":
            score = lexical[index] / max_lexical
        elif mode == "vector":
            score = vector[index]
        else:
            # Reciprocal rank fusion avoids comparing unlike BM25/cosine scales.
            score = sum(1 / (60 + ranking[index]) for ranking in (lexical_rank, vector_rank) if index in ranking) * 30.5
        if score > 0:
            scores.append((score, index))
    scores.sort(key=lambda item: (-item[0], stable_key(item[1])))
    return [
        {
            **chunks[index],
            "score": round(score, 6),
            "lexical_score": round(lexical[index], 6),
            "vector_score": round(vector[index], 6),
        }
        for score, index in scores[:k]
    ]
