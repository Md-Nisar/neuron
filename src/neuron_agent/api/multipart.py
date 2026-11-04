# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""A bounded `multipart/form-data` reader for document uploads (RAG-03.02).

Reads the request stream itself, so no byte past the cap is held and nothing is spooled to disk.
The form has one `file` part and an optional `title` field; anything else is refused. The file
name is returned only to default the title: it never reaches a path, a key or a log line.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.requests import Request

from neuron_agent.errors.base import UploadRefusedError as UploadError

if TYPE_CHECKING:
    from python_multipart.multipart import MultipartCallbacks

_MAX_TITLE_BYTES = 1_200  # 300 characters of 4 bytes
_MAX_PARTS = 2


@dataclass
class _Part:
    headers: dict[bytes, bytes] = field(default_factory=dict)
    data: bytearray = field(default_factory=bytearray)
    name: bytes = b""
    filename: str | None = None


@dataclass(frozen=True)
class Upload:
    data: bytes
    content_type: str  # the client's claim, lower-cased; only a hint, the content decides
    filename: str | None
    title: str | None


class _Collector:
    """python-multipart's callbacks: the parts, each capped as it arrives."""

    def __init__(self, max_file_bytes: int) -> None:
        self.parts: list[_Part] = []
        self._max_file_bytes = max_file_bytes
        self._field = bytearray()
        self._value = bytearray()

    def callbacks(self) -> MultipartCallbacks:
        return {
            "on_part_begin": self._begin,
            "on_header_field": lambda d, s, e: self._field.extend(d[s:e]),
            "on_header_value": lambda d, s, e: self._value.extend(d[s:e]),
            "on_header_end": self._header_end,
            "on_headers_finished": self._headers_done,
            "on_part_data": self._data,
        }

    def _begin(self) -> None:
        if len(self.parts) == _MAX_PARTS:
            raise UploadError("upload_invalid", 422)
        self.parts.append(_Part())

    def _header_end(self) -> None:
        self.parts[-1].headers[bytes(self._field).lower()] = bytes(self._value)
        self._field.clear()
        self._value.clear()

    def _headers_done(self) -> None:
        part = self.parts[-1]
        disposition, params = parse_options_header(part.headers.get(b"content-disposition"))
        if disposition != b"form-data":
            raise UploadError("upload_invalid", 422)
        part.name = params.get(b"name", b"")
        if b"filename" in params:
            part.filename = params[b"filename"].decode("utf-8", "replace")

    def _data(self, chunk: bytes, start: int, end: int) -> None:
        part = self.parts[-1]
        part.data += chunk[start:end]
        if part.name == b"file" and len(part.data) > self._max_file_bytes:
            raise UploadError("file_too_large", 413)
        if part.name != b"file" and len(part.data) > _MAX_TITLE_BYTES:
            raise UploadError("upload_invalid", 422)


async def read_upload(request: Request, *, max_file_bytes: int, max_body_bytes: int) -> Upload:
    """The form's file and title, or `UploadError`: 413 past `max_file_bytes` of file or
    `max_body_bytes` of body, 415 when the body is not multipart, 422 for any other form."""
    kind, options = parse_options_header(request.headers.get("content-type"))
    boundary = options.get(b"boundary")
    if kind != b"multipart/form-data" or not boundary:
        raise UploadError("multipart_required", 415)
    collector = _Collector(max_file_bytes)
    parser = MultipartParser(boundary, collector.callbacks())
    received = 0
    try:
        async for chunk in request.stream():
            received += len(chunk)
            if received > max_body_bytes:
                raise UploadError("file_too_large", 413)
            parser.write(chunk)
        parser.finalize()
    except UploadError:
        raise
    except Exception:  # noqa: BLE001 - any malformed body is the same refusal
        raise UploadError("upload_invalid", 422) from None
    return _form(collector.parts)


def _form(parts: list[_Part]) -> Upload:
    files = [part for part in parts if part.name == b"file" and part.filename is not None]
    titles = [part for part in parts if part.name == b"title" and part.filename is None]
    if len(files) != 1 or len(files) + len(titles) != len(parts):
        raise UploadError("upload_invalid", 422)
    (file,) = files
    try:
        title = titles[0].data.decode("utf-8") if titles else None
    except UnicodeDecodeError:
        raise UploadError("upload_invalid", 422) from None
    kind, _ = parse_options_header(file.headers.get(b"content-type"))
    return Upload(
        data=bytes(file.data),
        content_type=kind.decode("latin-1").lower(),
        filename=file.filename,
        title=title,
    )
