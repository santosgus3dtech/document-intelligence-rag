from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .models import AskRequest, DemoSessionRequest, SearchRequest
from .security import Authentication, Identity, MAX_UPLOAD_BYTES, RequestBodyLimitMiddleware, SESSION_COOKIE, contained_path, validated_filename
from .store import DocumentLimitError, Store

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOGGER = logging.getLogger(__name__)


def build_app(storage_root: str | Path | None = None, database_url: str | None = None,
              demo: bool | None = None, seed_on_start: bool = True,
              api_tokens: str | None = None) -> FastAPI:
    root = Path(storage_root or os.getenv("DOC_INTEL_STORAGE", PROJECT_ROOT / "storage")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    is_demo = (os.getenv("DOC_INTEL_DEMO", "true").lower() == "true") if demo is None else demo
    auth = Authentication(is_demo, api_tokens)
    store = Store(database_url or os.getenv("DOC_INTEL_DATABASE_URL"), root)
    store.recover_interrupted()
    jobs: set[asyncio.Task] = set()
    processor_limit = asyncio.Semaphore(2)
    validation_limit = asyncio.Semaphore(2)
    worker_keys = {"PATH", "SystemRoot", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR",
                   "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "LANG", "LC_ALL",
                   "TESSERACT_CMD", "OCR_LANGUAGES", "LD_LIBRARY_PATH"}
    worker_environment = {key: value for key, value in os.environ.items() if key in worker_keys}
    worker_environment.update(PYTHONPATH=str(PROJECT_ROOT / "backend"), PYTHONUNBUFFERED="1", OMP_NUM_THREADS="2")
    extractor_engine = os.getenv("DOC_INTEL_EXTRACTOR", "offline")
    rate_events: dict[str, deque] = defaultdict(deque)

    def run_worker(source: Path, output: Path, validate: bool = False) -> dict:
        command = [sys.executable, "-m", "app.worker", str(source), str(output)]
        command.extend(["--validate"] if validate else ["--engine", extractor_engine])
        completed = subprocess.run(command, env=worker_environment, cwd=PROJECT_ROOT,
                                   capture_output=True, text=True, timeout=12 if validate else 65)
        if completed.returncode:
            # Deliberately do not expose parser stderr, paths or source text through the API.
            raise ValueError("The file failed content validation." if validate else "Document processing failed. Check that the document is readable and OCR is installed.")
        return json.loads(output.read_text(encoding="utf-8"))

    def process_sync(document_id: str) -> None:
        document = store.get_document(document_id, True)
        if not document:
            return
        document.update(status="processing", error=None)
        store.update_document(document)
        try:
            folder = contained_path(root, document_id)
            result = run_worker(contained_path(root, document["source_path"]), folder / "extraction.json")
            passages = []
            pages = []
            for page in result["pages"]:
                image = Path(page["image_path"]).resolve()
                if not image.is_relative_to(folder):
                    raise ValueError("Extraction produced an invalid preview path.")
                pages.append({"number": page["number"], "width": page["width"], "height": page["height"],
                              "image_path": str(image.relative_to(root))})
                for block in page["blocks"]:
                    if block["text"].strip():
                        passage = {"id": f"{document_id}:{block['id']}", "document_id": document_id,
                                   "document_title": document["title"], "page": page["number"],
                                   "text": block["text"], "bbox": block["bbox"], "kind": block["kind"],
                                   "engine": block.get("engine", result["engine"])}
                        for extra in ("rows", "confidence"):
                            if extra in block:
                                passage[extra] = block[extra]
                        passages.append(passage)
            if not passages:
                raise ValueError("No readable text was found. Try a sharper scan or a text PDF.")
            store.replace_passages(document_id, passages)
            document.update(status="ready", pages=pages, page_count=len(pages), chunk_count=len(passages),
                            engine=result["engine"], warnings=result.get("warnings", []))
        except subprocess.TimeoutExpired:
            document.update(status="failed", error="Document processing exceeded the 65 second time limit.")
        except Exception as error:
            document.update(status="failed", error=str(error) if isinstance(error, ValueError) else "Document processing failed.")
            LOGGER.warning("Document %s processing failed (%s)", document_id, type(error).__name__)
        store.update_document(document)

    async def process(document_id: str) -> None:
        async with processor_limit:
            await asyncio.to_thread(process_sync, document_id)

    def schedule(document_id: str) -> None:
        task = asyncio.create_task(process(document_id))
        jobs.add(task)
        task.add_done_callback(jobs.discard)

    def new_document(document_id: str, filename: str, title: str, access: str, source: Path, media_type: str) -> dict:
        return {"id": document_id, "filename": filename, "title": title, "access": access,
                "status": "queued", "created_at": datetime.now(timezone.utc).isoformat(),
                "page_count": 0, "chunk_count": 0, "engine": None, "error": None,
                "warnings": [], "pages": [], "source_path": str(source.relative_to(root)), "media_type": media_type}

    def seed() -> list[str]:
        manifest_path = PROJECT_ROOT / "fixtures" / "manifest.json"
        if not manifest_path.exists():
            return []
        created = []
        for fixture in json.loads(manifest_path.read_text(encoding="utf-8"))["documents"]:
            document_id = fixture["id"]
            if store.get_document(document_id, True):
                continue
            if not document_id.replace("-", "").replace("_", "").isalnum():
                raise ValueError("Fixture identifiers must be simple slugs.")
            original = contained_path(PROJECT_ROOT / "fixtures", fixture["filename"])
            filename = validated_filename(original.name)
            folder = contained_path(root, document_id)
            folder.mkdir(parents=True, exist_ok=True)
            source = folder / ("source" + original.suffix.lower())
            shutil.copyfile(original, source)
            from .security import validate_upload
            media_type = validate_upload(filename, source.read_bytes())
            document = new_document(document_id, filename, fixture["title"], fixture["access"], source, media_type)
            store.add_document(document)
            schedule(document_id)
            created.append(document_id)
        return created

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if is_demo and seed_on_start:
            seed()
        yield
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)

    app = FastAPI(title="Document Intelligence RAG", version="0.1.0", lifespan=lifespan)
    app.state.store = store
    app.state.auth = auth
    app.state.storage_root = root
    app.state.jobs = jobs
    app.state.process_sync = process_sync

    def current_identity(request: Request, response: Response) -> Identity:
        return auth.identify(request, response)

    def allowed_document(document_id: str, identity: Identity) -> dict:
        document = store.get_document(document_id, identity.can_restricted)
        if not document:
            raise HTTPException(404, "Document not found or unavailable to this identity.")
        return document

    def public_document(document: dict) -> dict:
        output = {key: value for key, value in document.items() if key not in {"source_path", "media_type", "pages"}}
        output["pages"] = [{key: value for key, value in page.items() if key != "image_path"}
                           for page in document.get("pages", [])]
        return output

    @app.middleware("http")
    async def browser_boundary(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            if request.headers.get("content-length", "0").isdigit() and int(request.headers.get("content-length", "0")) > MAX_UPLOAD_BYTES + 65536:
                return JSONResponse({"detail": "The upload exceeds the 10 MiB limit."}, status_code=413)
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                origin = request.headers.get("origin")
                if origin:
                    allowed_origins = {"http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:8100", "http://localhost:8100"}
                    allowed_origins.add(f"{request.url.scheme}://{request.url.netloc}")
                    if origin not in allowed_origins:
                        return JSONResponse({"detail": "Cross-origin mutations are not allowed."}, status_code=403)
                client_key = request.client.host if request.client else "local"
                now = time.monotonic()
                bucket = rate_events[client_key]
                while bucket and bucket[0] < now - 60:
                    bucket.popleft()
                if len(bucket) >= 60:
                    return JSONResponse({"detail": "Please wait before submitting more requests."}, status_code=429)
                bucket.append(now)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, private"
            response.headers["Vary"] = "Cookie, Authorization"
        return response

    # Added last to wrap the browser middleware and multipart parser themselves.
    app.add_middleware(RequestBodyLimitMiddleware)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "service": "document-intelligence-rag", "demo": is_demo, "storage": "postgresql-pgvector" if store.postgres else "sqlite",
                "generation": "offline-extractive", "extraction": extractor_engine}

    @app.get("/api/session")
    def session(identity: Identity = Depends(current_identity)) -> dict:
        return {"identity": identity.id, "demo": is_demo, "can_restricted": identity.can_restricted,
                "can_upload": identity.can_upload, "authentication": "local-demo-session" if is_demo else "server-bearer-token"}

    @app.post("/api/demo/session")
    def switch_session(body: DemoSessionRequest, request: Request, response: Response) -> dict:
        if not is_demo:
            raise HTTPException(404, "Demo switching is disabled.")
        auth.sessions.pop(request.cookies.get(SESSION_COOKIE, ""), None)
        identity = Identity(body.identity, body.identity == "reviewer")
        auth.set_session(response, identity)
        return session(identity)

    @app.post("/api/demo/seed")
    async def seed_documents(identity: Identity = Depends(current_identity)) -> dict:
        if not is_demo:
            raise HTTPException(404, "Synthetic demo seeding is disabled.")
        return {"created": seed()}

    @app.get("/api/documents")
    def list_documents(identity: Identity = Depends(current_identity)) -> list[dict]:
        return [public_document(document) for document in store.list_documents(identity.can_restricted)]

    @app.post("/api/documents", status_code=202)
    async def upload(file: UploadFile = File(), access: str = Form("public"), title: str | None = Form(None),
                     identity: Identity = Depends(current_identity)) -> dict:
        if not identity.can_upload or (access == "restricted" and not identity.can_restricted):
            raise HTTPException(403, "This identity cannot upload documents with the requested access.")
        if access not in {"public", "restricted"}:
            raise HTTPException(422, "Access must be public or restricted.")
        if len(store.list_documents(True)) >= 100:
            raise HTTPException(409, "The local demonstration is limited to 100 documents.")
        try:
            filename = validated_filename(file.filename or "")
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        if title is not None and not 1 <= len(title.strip()) <= 160:
            raise HTTPException(422, "Document titles must contain between 1 and 160 characters.")
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        await file.close()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "The upload exceeds the 10 MiB limit.")
        document_id = uuid.uuid4().hex
        folder = contained_path(root, document_id)
        folder.mkdir()
        source = folder / ("source" + Path(filename).suffix.lower())
        source.write_bytes(content)
        try:
            async with validation_limit:
                result = await asyncio.to_thread(run_worker, source, folder / "validation.json", True)
            document = new_document(document_id, filename, title.strip() if title else Path(filename).stem,
                                    access, source, result["media_type"])
            store.add_document(document)
        except DocumentLimitError as error:
            shutil.rmtree(folder)
            raise HTTPException(409, str(error)) from error
        except (ValueError, subprocess.TimeoutExpired) as error:
            shutil.rmtree(folder)
            raise HTTPException(422, "The file failed validation or exceeded the validation time limit.") from error
        except Exception:
            shutil.rmtree(folder)
            raise
        schedule(document_id)
        return public_document(document)

    @app.get("/api/documents/{document_id}")
    def document_detail(document_id: str, identity: Identity = Depends(current_identity)) -> dict:
        document = allowed_document(document_id, identity)
        return dict(public_document(document), passages=store.passages(identity.can_restricted, [document_id]))

    @app.get("/api/documents/{document_id}/source")
    def document_source(document_id: str, identity: Identity = Depends(current_identity)) -> FileResponse:
        document = allowed_document(document_id, identity)
        path = contained_path(root, document["source_path"])
        if not path.is_file():
            raise HTTPException(404, "The source file is missing.")
        return FileResponse(path, media_type=document["media_type"], filename=document["filename"], content_disposition_type="attachment")

    @app.get("/api/documents/{document_id}/pages/{page}")
    def document_page(document_id: str, page: int, identity: Identity = Depends(current_identity)) -> FileResponse:
        document = allowed_document(document_id, identity)
        metadata = next((item for item in document.get("pages", []) if item["number"] == page), None)
        if metadata is None:
            raise HTTPException(404, "This source page is not available.")
        path = contained_path(root, metadata["image_path"])
        if not path.is_file():
            raise HTTPException(404, "The page preview is missing.")
        return FileResponse(path, media_type="image/png")

    def retrieve(query: str, mode: str, ids: list[str] | None, limit: int, identity: Identity) -> list[dict]:
        from .retrieval import concepts, embed_text, search
        chunks = store.passages(identity.can_restricted, ids)
        if not store.postgres or mode == "lexical":
            return search(chunks, query, mode=mode, k=limit)
        candidates = store.vector_search(embed_text(query), identity.can_restricted, ids, max(100, limit * 10))
        query_terms = concepts(query)
        vector_hits = [hit for hit in candidates if query_terms & concepts(hit["text"])]
        if mode == "vector":
            return vector_hits[:limit]
        lexical_hits = search(chunks, query, mode="lexical", k=20)
        combined: dict[str, dict] = {}
        for hits in (lexical_hits, vector_hits):
            for rank, hit in enumerate(hits, 1):
                item = combined.setdefault(hit["id"], dict(hit, score=0.0))
                item["score"] += 1 / (60 + rank)
        return sorted(combined.values(), key=lambda hit: (-hit["score"], hit["id"]))[:limit]

    @app.post("/api/search")
    def search_documents(body: SearchRequest, identity: Identity = Depends(current_identity)) -> dict:
        started = time.perf_counter()
        results = retrieve(body.query, body.mode, body.document_ids, body.limit, identity)
        return {"results": results, "mode": body.mode,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "vector_backend": "pgvector" if store.postgres else "local-feature-hashing"}

    @app.post("/api/ask")
    def ask(body: AskRequest, identity: Identity = Depends(current_identity)) -> dict:
        started = time.perf_counter()
        from .generation import answer, validate_citations
        hits = retrieve(body.question, body.mode, body.document_ids, 5, identity)
        result = answer(body.question, hits)
        if (not validate_citations(result["citations"], hits)
                or (not result["unsupported"] and not result["citations"])):
            raise HTTPException(500, "Answer citations did not match retrieved evidence.")
        result["generation_latency_ms"] = result["latency_ms"]
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return result

    frontend = PROJECT_ROOT / "frontend" / "dist"
    if (frontend / "index.html").is_file():
        if (frontend / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

        @app.get("/favicon.svg", include_in_schema=False)
        def favicon() -> FileResponse:
            return FileResponse(frontend / "favicon.svg", media_type="image/svg+xml")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend_page(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(404)
            return FileResponse(frontend / "index.html")

    return app


app = build_app()
