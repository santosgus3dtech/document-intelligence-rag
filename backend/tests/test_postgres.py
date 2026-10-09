"""Optional native pgvector integration test against an isolated local database.

Set DOC_INTEL_TEST_DATABASE_URL to run. Only this test's generated UUID documents
are removed afterward; no pre-existing rows or configuration are modified.
"""
from __future__ import annotations

import os
import time

import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient

from app.main import build_app


@pytest.mark.skipif(not os.getenv("DOC_INTEL_TEST_DATABASE_URL"), reason="Set DOC_INTEL_TEST_DATABASE_URL for native pgvector integration")
def test_native_pgvector_search_and_acl(tmp_path):
    app = build_app(tmp_path, database_url=os.environ["DOC_INTEL_TEST_DATABASE_URL"], demo=True, seed_on_start=False)
    created = []
    try:
        with TestClient(app) as client:
            client.post("/api/demo/session", json={"identity": "reviewer"})
            for access, text in [("public", "The coolant filter replacement interval is 500 operating hours."),
                                 ("restricted", "The restricted orchard access code is ORCHID-77.")]:
                with fitz.open() as pdf:
                    page = pdf.new_page()
                    page.insert_text((50, 80), text)
                    content = pdf.tobytes()
                response = client.post("/api/documents", files={"file": (f"{access}.pdf", content)}, data={"access": access})
                assert response.status_code == 202, response.text
                doc_id = response.json()["id"]
                created.append(doc_id)
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    document = client.get(f"/api/documents/{doc_id}").json()
                    if document["status"] not in {"queued", "processing"}:
                        break
                    time.sleep(0.05)
                assert document["status"] == "ready", document
            public_id, restricted_id = created
            for mode in ("vector", "hybrid"):
                for limit in (5, 20):
                    # Regression: API limit=20 must not request k=80 from the
                    # lexical component, whose independently enforced cap is20.
                    response = client.post("/api/search", json={"query": "coolant filter replacement interval", "mode": mode, "document_ids": [public_id], "limit": limit})
                    assert response.status_code == 200, response.text
                    result = response.json()
                    assert result["vector_backend"] == "pgvector"
                    assert result["results"][0]["document_id"] == public_id
                    response = client.post("/api/search", json={"query": "orchard access code", "mode": mode, "document_ids": [restricted_id], "limit": limit})
                    assert response.status_code == 200, response.text
                    assert response.json()["results"][0]["document_id"] == restricted_id
            client.post("/api/demo/session", json={"identity": "viewer"})
            for mode in ("lexical", "vector", "hybrid"):
                result = client.post("/api/search", json={"query": "orchard access code", "mode": mode, "document_ids": [restricted_id]}).json()
                assert result["results"] == []
            assert client.get(f"/api/documents/{restricted_id}/source").status_code == 404
            assert client.get(f"/api/documents/{restricted_id}/pages/1").status_code == 404
            irrelevant = client.post("/api/search", json={"query": "lunar chess champion", "mode": "vector", "document_ids": created}).json()
            assert irrelevant["results"] == []
    finally:
        for document_id in created:
            with app.state.store.connection() as connection:
                connection.execute(app.state.store.sql("DELETE FROM documents WHERE id=?"), (document_id,))
