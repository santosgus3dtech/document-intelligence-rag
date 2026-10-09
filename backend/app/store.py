"""Small SQL storage adapter. ACL predicates are applied by SQL before retrieval."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class DocumentLimitError(ValueError):
    pass


class Store:
    def __init__(self, database_url: str | None, root: Path):
        if database_url and not database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("DOC_INTEL_DATABASE_URL must use the postgresql:// scheme; omit it for local SQLite.")
        self.postgres = bool(database_url and database_url.startswith(("postgresql://", "postgres://")))
        self.database_url = database_url
        self.path = root / "documents.sqlite3"
        self.lock = threading.RLock()
        root.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            if self.postgres:
                connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
            connection.execute("""CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, filename TEXT NOT NULL,
                access TEXT NOT NULL CHECK(access IN ('public','restricted')),
                status TEXT NOT NULL, created_at TEXT NOT NULL,
                metadata TEXT NOT NULL
            )""")
            vector_type = "vector(384)" if self.postgres else "TEXT"
            connection.execute(f"""CREATE TABLE IF NOT EXISTS passages (
                id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                page INTEGER NOT NULL, text TEXT NOT NULL, metadata TEXT NOT NULL,
                embedding {vector_type} NOT NULL
            )""")
            connection.execute("CREATE INDEX IF NOT EXISTS passages_document_idx ON passages(document_id)")
            if self.postgres:
                connection.execute("CREATE INDEX IF NOT EXISTS passages_vector_idx ON passages USING hnsw (embedding vector_cosine_ops)")

    @contextmanager
    def connection(self) -> Iterator:
        with self.lock:
            if self.postgres:
                import psycopg
                from psycopg.rows import dict_row
                connection = psycopg.connect(self.database_url, row_factory=dict_row)
            else:
                connection = sqlite3.connect(self.path, timeout=20)
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys=ON")
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def sql(self, statement: str) -> str:
        return statement.replace("?", "%s") if self.postgres else statement

    @staticmethod
    def document(row) -> dict:
        result = json.loads(row["metadata"])
        result.update({key: row[key] for key in ("id", "title", "filename", "access", "status", "created_at")})
        return result

    def add_document(self, document: dict) -> None:
        with self.connection() as connection:
            connection.execute("LOCK TABLE documents IN SHARE ROW EXCLUSIVE MODE" if self.postgres else "BEGIN IMMEDIATE")
            row = connection.execute("SELECT COUNT(*) AS count FROM documents").fetchone()
            if row["count"] >= 100:
                raise DocumentLimitError("The local demonstration is limited to 100 documents.")
            connection.execute(self.sql("INSERT INTO documents (id,title,filename,access,status,created_at,metadata) VALUES (?,?,?,?,?,?,?)"),
                               (*[document[key] for key in ("id", "title", "filename", "access", "status", "created_at")], json.dumps(document)))

    def update_document(self, document: dict) -> None:
        with self.connection() as connection:
            connection.execute(self.sql("UPDATE documents SET status=?,metadata=? WHERE id=?"),
                               (document["status"], json.dumps(document), document["id"]))

    def get_document(self, document_id: str, can_restricted: bool = False) -> dict | None:
        with self.connection() as connection:
            row = connection.execute(self.sql("SELECT * FROM documents WHERE id=? AND (access='public' OR ?=1)"),
                                     (document_id, int(can_restricted))).fetchone()
        return self.document(row) if row else None

    def list_documents(self, can_restricted: bool = False) -> list[dict]:
        with self.connection() as connection:
            rows = connection.execute(self.sql("SELECT * FROM documents WHERE access='public' OR ?=1 ORDER BY created_at DESC,id"),
                                      (int(can_restricted),)).fetchall()
        return [self.document(row) for row in rows]

    def replace_passages(self, document_id: str, passages: list[dict]) -> None:
        from .retrieval import embed_text
        with self.connection() as connection:
            connection.execute(self.sql("DELETE FROM passages WHERE document_id=?"), (document_id,))
            for passage in passages:
                embedding = json.dumps(embed_text(passage["text"]))
                connection.execute(self.sql("INSERT INTO passages (id,document_id,page,text,metadata,embedding) VALUES (?,?,?,?,?,?)"),
                                   (passage["id"], document_id, passage["page"], passage["text"], json.dumps(passage), embedding))

    def authorized_predicate(self, can_restricted: bool, document_ids: list[str] | None) -> tuple[str, tuple]:
        predicate = "d.status='ready' AND (d.access='public' OR ?=1)"
        parameters: tuple = (int(can_restricted),)
        if document_ids is not None:
            if not document_ids:
                return predicate + " AND 1=0", parameters
            predicate += " AND d.id IN (" + ",".join("?" for _ in document_ids) + ")"
            parameters += tuple(document_ids)
        return predicate, parameters

    def passages(self, can_restricted: bool, document_ids: list[str] | None = None) -> list[dict]:
        predicate, parameters = self.authorized_predicate(can_restricted, document_ids)
        with self.connection() as connection:
            rows = connection.execute(self.sql(f"SELECT p.metadata FROM passages p JOIN documents d ON d.id=p.document_id WHERE {predicate} ORDER BY p.id"), parameters).fetchall()
        return [json.loads(row["metadata"]) for row in rows]

    def vector_search(self, embedding: list[float], can_restricted: bool, document_ids: list[str] | None, limit: int) -> list[dict]:
        if not self.postgres:
            raise ValueError("Native pgvector retrieval requires PostgreSQL.")
        predicate, parameters = self.authorized_predicate(can_restricted, document_ids)
        vector = json.dumps(embedding)
        with self.connection() as connection:
            rows = connection.execute(self.sql(f"""SELECT p.metadata,1-(p.embedding <=> ?::vector) AS score
                FROM passages p JOIN documents d ON d.id=p.document_id
                WHERE {predicate} ORDER BY p.embedding <=> ?::vector,p.id LIMIT ?"""),
                (vector, *parameters, vector, limit)).fetchall()
        return [dict(json.loads(row["metadata"]), score=round(float(row["score"]), 6)) for row in rows if float(row["score"]) > 0]

    def recover_interrupted(self) -> None:
        for document in self.list_documents(True):
            if document["status"] in {"queued", "processing"}:
                document.update(status="failed", error="Processing was interrupted by an application restart. Upload this document again.")
                self.update_document(document)
