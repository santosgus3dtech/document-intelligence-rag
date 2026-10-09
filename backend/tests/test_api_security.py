from __future__ import annotations

import io
import json
import subprocess
import threading
import time
from pathlib import Path

import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import build_app
from app.security import MAX_UPLOAD_BYTES, contained_path, validate_upload, validated_filename


def pdf_bytes(text: str = "The maximum storage temperature is 28 degrees Celsius.") -> bytes:
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((50, 80), text)
        return document.tobytes()


def wait_ready(client: TestClient, document_id: str) -> dict:
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        document = client.get(f"/api/documents/{document_id}").json()
        if document["status"] not in {"queued", "processing"}:
            return document
        time.sleep(0.05)
    pytest.fail("Processing did not finish within the test deadline")


@pytest.mark.parametrize("name", ["../secret.pdf", "folder/file.pdf", "folder\\file.pdf", "C:\\secret.pdf", ".pdf", "file.txt", "test.pdf ", "bad\x00.pdf"])
def test_filename_rejects_paths_and_unsupported_extensions(name):
    with pytest.raises(ValueError):
        validated_filename(name)


def test_content_validation_requires_real_supported_content():
    with pytest.raises(ValueError):
        validate_upload("fake.pdf", b"%PDF-1.7\nnot a document")
    with pytest.raises(ValueError):
        validate_upload("fake.png", pdf_bytes())
    with pytest.raises(ValueError):
        validate_upload("empty.pdf", b"")
    image = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(image, format="PNG")
    assert validate_upload("image.png", image.getvalue()) == "image/png"
    with pytest.raises(ValueError):
        validate_upload("image.jpg", image.getvalue())


def test_encrypted_and_overlong_pdfs_are_rejected():
    with fitz.open() as document:
        for _ in range(21):
            document.new_page()
        with pytest.raises(ValueError):
            validate_upload("too-many.pdf", document.tobytes())
    with fitz.open() as document:
        document.new_page()
        encrypted = document.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="reader")
        with pytest.raises(ValueError):
            validate_upload("encrypted.pdf", encrypted)


def test_containment_rejects_parent_and_symlink_escape(tmp_path):
    with pytest.raises(ValueError):
        contained_path(tmp_path, "..", "secret.pdf")
    assert contained_path(tmp_path, "abc", "source.pdf") == tmp_path / "abc" / "source.pdf"
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir(exist_ok=True)
    try:
        (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this host")
    with pytest.raises(ValueError):
        contained_path(tmp_path, "linked", "secret.pdf")


def test_upload_process_source_and_citations_work(tmp_path):
    app = build_app(tmp_path, demo=True, seed_on_start=False)
    with TestClient(app) as client:
        assert client.get("/api/session").json()["identity"] == "viewer"
        response = client.post("/api/documents", files={"file": ("manual.pdf", pdf_bytes(), "application/pdf")})
        assert response.status_code == 202, response.text
        document = wait_ready(client, response.json()["id"])
        assert document["status"] == "ready", document
        assert document["page_count"] == 1
        assert len(document["passages"]) >= 1
        assert "source_path" not in document
        page = client.get(f"/api/documents/{document['id']}/pages/1")
        assert page.status_code == 200
        assert page.headers["content-type"] == "image/png"
        assert page.headers["cache-control"] == "no-store, private"
        assert client.get(f"/api/documents/{document['id']}/source").content.startswith(b"%PDF")
        for mode in ("lexical", "vector", "hybrid"):
            results = client.post("/api/search", json={"query": "maximum storage temperature", "mode": mode}).json()["results"]
            assert results and results[0]["document_id"] == document["id"]
        answer = client.post("/api/ask", json={"question": "What is the maximum storage temperature?"}).json()
        assert not answer["unsupported"], answer
        assert answer["citations"][0]["id"] in {item["id"] for item in document["passages"]}
        assert len(answer["citations"][0]["bbox"]) == 4
        unsupported = client.post("/api/ask", json={"question": "Who won the lunar chess championship?"}).json()
        assert unsupported["unsupported"] and not unsupported["citations"]


def test_restricted_document_never_reaches_viewer_retrieval_or_source(tmp_path, monkeypatch):
    app = build_app(tmp_path, demo=True, seed_on_start=False)
    with TestClient(app) as client:
        client.post("/api/demo/session", json={"identity": "reviewer"})
        reviewer_cookie = client.cookies.get("document_intel_session")
        response = client.post("/api/documents", files={"file": ("restricted.pdf", pdf_bytes("Restricted access code is ORCHID-77."), "application/pdf")}, data={"access": "restricted"})
        assert response.status_code == 202
        doc_id = response.json()["id"]
        assert wait_ready(client, doc_id)["status"] == "ready"
        assert client.get(f"/api/documents/{doc_id}/source").status_code == 200
        client.post("/api/demo/session", json={"identity": "viewer"})
        assert reviewer_cookie not in app.state.auth.sessions
        assert all(item["id"] != doc_id for item in client.get("/api/documents").json())
        for endpoint in (f"/api/documents/{doc_id}", f"/api/documents/{doc_id}/source", f"/api/documents/{doc_id}/pages/1"):
            assert client.get(endpoint, headers={"X-Demo-Role": "reviewer", "X-Role": "admin"}).status_code == 404
        for mode in ("lexical", "vector", "hybrid"):
            assert client.post("/api/search", json={"query": "ORCHID-77", "mode": mode, "document_ids": [doc_id]}).json()["results"] == []
        assert client.post("/api/ask", json={"question": "What is the restricted access code?", "document_ids": [doc_id]}).json()["unsupported"]
        assert app.state.store.passages(False, [doc_id]) == []


def test_invalid_uploads_and_cross_origin_mutations_are_rejected(tmp_path):
    with TestClient(build_app(tmp_path, demo=True, seed_on_start=False)) as client:
        assert client.post("/api/documents", files={"file": ("../file.pdf", pdf_bytes())}).status_code == 422
        assert client.post("/api/documents", files={"file": ("fake.pdf", b"%PDF-fake")}).status_code == 422
        assert client.post("/api/documents", files={"file": ("large.pdf", b"x" * (MAX_UPLOAD_BYTES + 1))}).status_code == 413
        assert client.post("/api/documents", files={"file": ("file.pdf", pdf_bytes())}, data={"access": "restricted"}).status_code == 403
        assert client.post("/api/demo/session", json={"identity": "reviewer"}, headers={"Origin": "https://hostile.example"}).status_code == 403
        assert client.get("/api/documents/unknown/pages/0").status_code == 404
        assert client.post("/api/search", json={"query": "test", "mode": "invalid"}).status_code == 422


def test_non_demo_auth_requires_server_configured_token_and_disables_switch(tmp_path):
    token = "sample-test-token-" + "x" * 32
    configuration = json.dumps({token: {"id": "controlled-reader", "can_upload": False, "can_restricted": False}})
    with TestClient(build_app(tmp_path, demo=False, seed_on_start=False, api_tokens=configuration)) as client:
        assert client.get("/api/documents", headers={"X-Demo-Role": "reviewer"}).status_code == 401
        assert client.post("/api/demo/session", json={"identity": "reviewer"}).status_code == 404
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/session", headers=headers).json()["identity"] == "controlled-reader"
        assert client.post("/api/documents", headers=headers, files={"file": ("file.pdf", pdf_bytes())}).status_code == 403


def test_processing_failure_remains_visible_and_is_not_searchable(tmp_path):
    with fitz.open() as document:
        document.new_page()
        blank_pdf = document.tobytes()
    with TestClient(build_app(tmp_path, demo=True, seed_on_start=False)) as client:
        uploaded = client.post("/api/documents", files={"file": ("blank.pdf", blank_pdf)}).json()
        document = wait_ready(client, uploaded["id"])
        assert document["status"] == "failed"
        assert document["error"]
        assert document["passages"] == []
        assert client.get(f"/api/documents/{document['id']}/pages/1").status_code == 404


def test_api_rechecks_citation_provenance_independently(tmp_path, monkeypatch):
    from app import generation
    with TestClient(build_app(tmp_path, demo=True, seed_on_start=False)) as client:
        uploaded = client.post("/api/documents", files={"file": ("manual.pdf", pdf_bytes())}).json()
        document = wait_ready(client, uploaded["id"])
        forged = dict(document["passages"][0], page=999, quote=document["passages"][0]["text"])
        monkeypatch.setattr(generation, "answer", lambda question, hits: {"answer": "forged", "unsupported": False, "citations": [forged]})
        response = client.post("/api/ask", json={"question": "maximum storage temperature"})
        assert response.status_code == 500


def test_structured_table_rows_survive_processing_storage_and_retrieval(tmp_path):
    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "recebimento-materiais.pdf"
    with TestClient(build_app(tmp_path, demo=True, seed_on_start=False)) as client:
        uploaded = client.post("/api/documents", files={"file": (fixture.name, fixture.read_bytes())}).json()
        document = wait_ready(client, uploaded["id"])
        assert document["status"] == "ready", document
        tables = [passage for passage in document["passages"] if passage["kind"] == "table"]
        assert tables and len(tables[0]["rows"]) > 1
        assert all(isinstance(cell, str) for row in tables[0]["rows"] for cell in row)
        assert len(tables[0]["bbox"]) == 4
        results = client.post("/api/search", json={"query": tables[0]["rows"][1][0], "document_ids": [document["id"]], "limit": 20}).json()["results"]
        assert any(hit.get("rows") == tables[0]["rows"] for hit in results)


def test_parser_timeout_produces_a_bounded_failure_state(tmp_path, monkeypatch):
    real_run = subprocess.run
    monkeypatch.setenv("DOC_INTEL_API_TOKENS", "synthetic-private-server-configuration")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-private-provider-configuration")

    def timed_out(command, **kwargs):
        assert "DOC_INTEL_API_TOKENS" not in kwargs["env"]
        assert "OPENAI_API_KEY" not in kwargs["env"]
        if "--validate" in command:
            assert kwargs["timeout"] == 12
            return real_run(command, **kwargs)
        assert kwargs["timeout"] == 65
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", timed_out)
    with TestClient(build_app(tmp_path, demo=True, seed_on_start=False)) as client:
        uploaded = client.post("/api/documents", files={"file": ("manual.pdf", pdf_bytes())}).json()
        document = wait_ready(client, uploaded["id"])
        assert document["status"] == "failed"
        assert "65 second" in document["error"]
        assert document["passages"] == []


def test_concurrent_uploads_never_spawn_more_than_two_validators(tmp_path, monkeypatch):
    import asyncio
    import httpx

    active = 0
    peak = 0
    lock = threading.Lock()

    def instrumented_worker(command, **kwargs):
        nonlocal active, peak
        if "--validate" not in command:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.08)
            Path(command[4]).write_text(json.dumps({"media_type": "application/pdf"}), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(subprocess, "run", instrumented_worker)
    app = build_app(tmp_path, demo=True, seed_on_start=False)

    async def requests():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            responses = await asyncio.gather(*(client.post("/api/documents", files={"file": (f"file-{index}.pdf", pdf_bytes())}) for index in range(8)))
            assert all(response.status_code == 202 for response in responses)
        await asyncio.gather(*list(app.state.jobs))

    asyncio.run(requests())
    assert peak == 2
