"""`read_upload`: the bounded multipart reader for document uploads (RAG-03.02)."""

from __future__ import annotations

from typing import Any

import anyio
import pytest
from starlette.requests import Request

from neuron_agent.api.multipart import Upload, read_upload
from neuron_agent.errors.base import UploadRefusedError

_BOUNDARY = "b0undary"


def _form(*parts: tuple[str, str | None, str | None, bytes], epilogue: bytes = b"") -> bytes:
    body = b""
    for name, filename, content_type, data in parts:
        disposition = f'form-data; name="{name}"' + (
            f'; filename="{filename}"' if filename is not None else ""
        )
        body += f"--{_BOUNDARY}\r\nContent-Disposition: {disposition}\r\n".encode()
        if content_type:
            body += f"Content-Type: {content_type}\r\n".encode()
        body += b"\r\n" + data + b"\r\n"
    return body + f"--{_BOUNDARY}--\r\n".encode() + epilogue


def _read(
    body: bytes,
    content_type: str = f"multipart/form-data; boundary={_BOUNDARY}",
    *,
    max_file: int = 1_000,
    max_body: int = 10_000,
    chunk: int = 7,
) -> Upload:
    chunks = [body[i : i + chunk] for i in range(0, len(body), chunk)] or [b""]
    messages = [
        {"type": "http.request", "body": c, "more_body": i < len(chunks) - 1}
        for i, c in enumerate(chunks)
    ]

    async def receive() -> dict[str, Any]:
        return messages.pop(0)

    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"content-type", content_type.encode())],
    }

    async def go() -> Upload:
        return await read_upload(
            Request(scope, receive), max_file_bytes=max_file, max_body_bytes=max_body
        )

    return anyio.run(go)


def _refused(body: bytes, **kwargs: Any) -> tuple[str, int]:
    with pytest.raises(UploadRefusedError) as caught:
        _read(body, **kwargs)
    return caught.value.context.code, caught.value.context.http_status


def test_the_file_and_title_are_read_across_chunk_boundaries() -> None:
    data = bytes(range(256)) * 3  # binary, with CR and LF inside
    upload = _read(
        _form(
            ("title", None, None, "Rapport été".encode()),
            ("file", "C:\\x\\r.pdf", "Application/PDF", data),
        )
    )
    assert upload == Upload(
        data=data, content_type="application/pdf", filename="r.pdf", title="Rapport été"
    )


def test_a_file_over_the_cap_is_413_before_the_rest_is_read() -> None:
    assert _refused(_form(("file", "a", None, b"x" * 1_001))) == ("file_too_large", 413)
    # Bytes outside any part count against the body cap.
    body = _form(("file", "a", None, b"x"), epilogue=b"y" * 20_000)
    assert _refused(body) == ("file_too_large", 413)


@pytest.mark.parametrize(
    "body",
    [
        _form(("title", None, None, b"t")),  # no file
        _form(("file", "a", None, b"1"), ("file", "b", None, b"2")),  # two files
        _form(("file", "a", None, b"1"), ("other", None, None, b"x")),  # unknown field
        _form(("file", None, None, b"1")),  # a file part without a file name
        _form(("file", "a", None, b"1"), ("title", None, None, b"\xff")),  # title not UTF-8
        _form(("file", "a", None, b"1"), ("title", None, None, b"t" * 1_201)),  # title too long
        b"--b0undary\r\nno headers end",
        # python-multipart caps a part's headers (8, 4,224 bytes each): no header bomb.
        b"--b0undary\r\n" + b"".join(b"X-%d: y\r\n" % i for i in range(20)) + b"\r\n",
        b"--b0undary\r\nX-Big: " + b"y" * 5_000 + b"\r\n\r\n",
    ],
    ids=[
        "no-file",
        "two-files",
        "unknown-field",
        "nameless",
        "bad-title",
        "long-title",
        "garbled",
        "many-headers",
        "long-header",
    ],
)
def test_any_other_form_is_422(body: bytes) -> None:
    assert _refused(body) == ("upload_invalid", 422)


def test_a_body_that_is_not_multipart_is_415() -> None:
    assert _refused(b"%PDF-1.7", content_type="application/pdf") == ("multipart_required", 415)
    assert _refused(b"", content_type="multipart/form-data") == ("multipart_required", 415)
