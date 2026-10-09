import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.security import MAX_UPLOAD_BYTES, RequestBodyLimitMiddleware
from app.store import DocumentLimitError, Store


def run_request(chunks, headers=None, path="/api/documents", disconnect=False):
    received = 0
    downstream_called = False
    sent = []

    async def downstream(scope, receive, send):
        nonlocal downstream_called
        downstream_called = True
        message = await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": message["body"]})

    async def receive():
        nonlocal received
        if disconnect and received == len(chunks):
            return {"type": "http.disconnect"}
        index = received
        received += 1
        return {"type": "http.request", "body": chunks[index],
                "more_body": disconnect or index < len(chunks) - 1}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": path, "headers": headers or []}
    asyncio.run(RequestBodyLimitMiddleware(downstream)(scope, receive, send))
    return sent, downstream_called, received


@pytest.mark.parametrize("headers", [[], [(b"transfer-encoding", b"chunked")], [(b"content-length", b"1")]])
def test_actual_stream_bytes_reject_oversize_before_multipart_parser(headers):
    chunks = [b"x" * (2 * 1024 * 1024)] * 9
    sent, downstream_called, received = run_request(chunks, headers)
    assert sent[0]["status"] == 413
    assert not downstream_called
    assert received < len(chunks)  # The full malicious stream was never consumed or spooled.


def test_json_body_has_a_smaller_independent_limit():
    sent, downstream_called, _ = run_request([b"x" * 40000, b"x" * 40000], path="/api/ask")
    assert sent[0]["status"] == 413
    assert not downstream_called


def test_supported_stream_is_replayed_once_without_change():
    sent, downstream_called, received = run_request([b"first", b"second"])
    assert sent[0]["status"] == 200
    assert downstream_called and received == 2
    assert sent[1]["body"] == b"firstsecond"


def test_client_disconnect_is_handled_without_invoking_parser_or_500():
    sent, downstream_called, _ = run_request([b"partial multipart data"], disconnect=True)
    assert sent[0]["status"] == 400
    assert not downstream_called


def test_declared_oversize_rejected_without_receiving_any_body():
    sent, downstream_called, received = run_request([b"not read"], [(b"content-length", str(MAX_UPLOAD_BYTES + 65537).encode())])
    assert sent[0]["status"] == 413
    assert not downstream_called and received == 0


def test_concurrent_writes_cannot_exceed_document_quota(tmp_path):
    store = Store(None, tmp_path)

    def add(index):
        document = {"id": f"test-{index}", "title": "Synthetic", "filename": "synthetic.pdf", "access": "public",
                    "status": "queued", "created_at": "2026-01-01T00:00:00+00:00"}
        try:
            store.add_document(document)
            return True
        except DocumentLimitError:
            return False

    for index in range(99):
        assert add(index)
    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(pool.map(add, range(99, 107)))
    assert sum(accepted) == 1
    assert len(store.list_documents(True)) == 100
