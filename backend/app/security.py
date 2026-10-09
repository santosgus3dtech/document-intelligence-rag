"""Independent upload, path, and server-owned demo identity boundaries."""
from __future__ import annotations

import hmac
import asyncio
import json
import os
import re
import secrets
import time
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PureWindowsPath

import pymupdf as fitz
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PAGES = 20
MAX_IMAGE_PIXELS = 20_000_000
SESSION_COOKIE = "document_intel_session"
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}


class RequestBodyLimitMiddleware:
    """Bound bytes before Starlette can parse or spool a multipart upload.

    A bounded buffer lets us reject without passing even a partial oversized
    multipart body to the parser, including chunked requests with no length.
    """
    def __init__(self, app):
        self.app = app
        self.upload_slots = asyncio.Semaphore(4)

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or not scope.get("path", "").startswith("/api/")
                or scope.get("method") not in {"POST", "PUT", "PATCH", "DELETE"}):
            await self.app(scope, receive, send)
            return
        if scope["path"] == "/api/documents":
            async with self.upload_slots:
                await self.bounded_body(scope, receive, send)
        else:
            await self.bounded_body(scope, receive, send)

    async def bounded_body(self, scope, receive, send):
        limit = MAX_UPLOAD_BYTES + 65536 if scope["path"] == "/api/documents" else 65536
        headers = dict(scope.get("headers", []))

        async def reject(status: int, detail: str) -> None:
            response = JSONResponse({"detail": detail}, status_code=status,
                                    headers={"Cache-Control": "no-store", "Connection": "close"})
            await response(scope, receive, send)

        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                length = int(declared)
                if length < 0:
                    raise ValueError
            except ValueError:
                await reject(400, "Invalid request body length.")
                return
            if length > limit:
                await reject(413, "The request body exceeds the configured size limit.")
                return
        buffer = bytearray()
        deadline = time.monotonic() + 30
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                message = await asyncio.wait_for(receive(), timeout=remaining)
                if message["type"] == "http.disconnect":
                    await reject(400, "The client disconnected before completing the request body.")
                    return
                chunk = message.get("body", b"")
                if len(buffer) + len(chunk) > limit:
                    await reject(413, "The request body exceeds the configured size limit.")
                    return
                buffer.extend(chunk)
                if not message.get("more_body", False):
                    break
        except (TimeoutError, asyncio.TimeoutError):
            await reject(408, "The request body exceeded the 30 second time limit.")
            return
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(buffer), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)


def validated_filename(filename: str) -> str:
    if (not filename or len(filename) > 160 or filename != Path(filename).name
            or filename != PureWindowsPath(filename).name
            or re.search(r'[\x00-\x1f<>:"/\\|?*]', filename)
            or filename.startswith(".") or filename.rstrip(". ") != filename):
        raise ValueError("Use a plain PDF, PNG or JPEG filename without path characters.")
    if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("Supported file types are PDF, PNG and JPEG.")
    return filename


def contained_path(root: Path, *parts: str) -> Path:
    """Resolve containment, including existing symlinks; never use upload names as paths."""
    root = root.resolve()
    candidate = root.joinpath(*parts).resolve()
    if candidate == root or not candidate.is_relative_to(root):
        raise ValueError("Stored path escapes its configured storage directory.")
    return candidate


def validate_upload(filename: str, content: bytes) -> str:
    validated_filename(filename)
    if not content:
        raise ValueError("The uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("The upload exceeds the 10 MiB limit.")
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise ValueError("The file content does not match its PDF extension.")
        try:
            with fitz.open(stream=content, filetype="pdf") as document:
                if document.needs_pass:
                    raise ValueError("Encrypted PDFs are not supported in this demo.")
                if not 1 <= len(document) <= MAX_PAGES:
                    raise ValueError(f"PDFs must contain between 1 and {MAX_PAGES} pages.")
                if document.is_repaired:
                    raise ValueError("The PDF is damaged or required structural repair.")
                for page in document:
                    if page.rect.width <= 0 or page.rect.height <= 0 or page.rect.width * page.rect.height * 4 > MAX_IMAGE_PIXELS:
                        raise ValueError("A PDF page exceeds the rendering pixel limit.")
        except (fitz.FileDataError, RuntimeError) as error:
            raise ValueError("The PDF could not be parsed.") from error
        return "application/pdf"
    expected = "PNG" if suffix == ".png" else "JPEG"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                if image.format != expected:
                    raise ValueError("The image content does not match its filename extension.")
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ValueError("The image exceeds the 20 megapixel limit.")
                if getattr(image, "n_frames", 1) != 1:
                    raise ValueError("Animated or multi-frame images are not supported.")
                image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError("The image could not be validated.") from error
    return "image/png" if expected == "PNG" else "image/jpeg"


@dataclass(frozen=True)
class Identity:
    id: str
    can_restricted: bool
    can_upload: bool = True


class Authentication:
    """Demo identity switching is explicit. Production identities require server tokens."""
    def __init__(self, demo: bool, api_tokens: str | None = None):
        self.demo = demo
        self.sessions: dict[str, tuple[Identity, float]] = {}
        self.tokens: list[tuple[str, Identity]] = []
        if not demo:
            raw = json.loads(api_tokens or os.getenv("DOC_INTEL_API_TOKENS", "{}"))
            if not isinstance(raw, dict) or not raw:
                raise ValueError("Non-demo mode requires DOC_INTEL_API_TOKENS with server-configured identities.")
            for token, value in raw.items():
                if not isinstance(token, str) or len(token) < 32 or not isinstance(value, dict):
                    raise ValueError("Configured bearer tokens must contain at least 32 characters.")
                self.tokens.append((token, Identity(str(value["id"]), bool(value.get("can_restricted", False)), bool(value.get("can_upload", False)))))

    def set_session(self, response: Response, identity: Identity) -> None:
        now = time.monotonic()
        self.sessions = {key: value for key, value in self.sessions.items() if value[1] > now}
        if len(self.sessions) >= 1000:
            self.sessions.pop(next(iter(self.sessions)))
        token = secrets.token_urlsafe(32)
        self.sessions[token] = (identity, now + 8 * 3600)
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict", max_age=8 * 3600)

    def identify(self, request: Request, response: Response) -> Identity:
        if not self.demo:
            authorization = request.headers.get("authorization", "")
            supplied = authorization[7:] if authorization.startswith("Bearer ") else ""
            for token, identity in self.tokens:
                if hmac.compare_digest(supplied.encode("utf-8"), token.encode("utf-8")):
                    return identity
            raise HTTPException(401, "A server-configured bearer token is required.")
        token = request.cookies.get(SESSION_COOKIE, "")
        existing = self.sessions.get(token)
        if existing and existing[1] > time.monotonic():
            return existing[0]
        viewer = Identity("viewer", False)
        self.set_session(response, viewer)
        return viewer
