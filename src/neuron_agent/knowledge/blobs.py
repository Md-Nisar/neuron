# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Private storage for original uploaded files (ADR 0014; RAG-01.03).

Keys are random and chosen here, never derived from a file name or any other user input, so a
name such as `../../etc/passwd` cannot pick where bytes land. A blob is written once under its
key and never overwritten; its SHA-256, computed while streaming, is recorded by the caller in
`knowledge.documents.sha256` and checked again on every read. There is no public URL: only
Neuron's processes read blobs, through this module.

`LocalBlobStore` (a directory, normally a volume) and `S3BlobStore` (a private S3-compatible
bucket) share one implementation over `obstore`, which provides both stores behind one API.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import re
import secrets
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import obstore
import structlog
from obstore.store import LocalStore, ObjectStore, S3Store

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import AppError, ErrorContext

logger = structlog.get_logger(__name__)

# 128 random bits as hex: unguessable, and nothing in it can be a path separator or `..`.
_KEY = re.compile(r"[0-9a-f]{32}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class BlobStoreError(AppError):
    """A blob operation failed; `code` is stable and the message never carries a path or URL."""

    context = ErrorContext(code="blob_store_error", http_status=500, user_visible=False)

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class BlobNotFoundError(BlobStoreError):
    """No blob is stored under the key."""

    def __init__(self) -> None:
        super().__init__("blob_not_found")


class BlobTooLargeError(BlobStoreError):
    """The stream is longer than the caller's limit; nothing is stored."""

    def __init__(self) -> None:
        super().__init__("blob_too_large")


class BlobIntegrityError(BlobStoreError):
    """The stored bytes do not match the SHA-256 recorded when they were written."""

    def __init__(self) -> None:
        super().__init__("blob_checksum_mismatch")


@dataclass(frozen=True)
class StoredBlob:
    key: str
    sha256: str
    size: int


class BlobStore(Protocol):
    async def put(self, chunks: AsyncIterable[bytes], *, max_bytes: int) -> StoredBlob: ...

    async def get(self, key: str, sha256: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...

    def older_than(self, cutoff: datetime) -> AsyncIterator[list[str]]: ...


def _backend_error(operation: str, exc: Exception) -> BlobStoreError:
    # obstore messages can carry the object path, an absolute local path or the endpoint URL.
    logger.warning("blob_backend_error", operation=operation, error_type=type(exc).__name__)
    return BlobStoreError("blob_backend_error")


def _check_key(key: str) -> str:
    if not _KEY.fullmatch(key):
        raise ValueError("blob key must be 32 lowercase hex characters")
    return key


class _ObjectBlobStore:
    def __init__(self, store: ObjectStore) -> None:
        self._store = store

    async def put(self, chunks: AsyncIterable[bytes], *, max_bytes: int) -> StoredBlob:
        """Stream `chunks` to a new random key and return the key, SHA-256 and size.

        More than `max_bytes` raises `BlobTooLargeError` and stores nothing.
        """
        key = secrets.token_hex(16)
        digest = hashlib.sha256()
        size = 0
        stream_error: BaseException | None = None

        async def hashed() -> AsyncIterator[bytes]:
            nonlocal size, stream_error
            try:
                async for chunk in chunks:
                    size += len(chunk)
                    if size > max_bytes:
                        raise BlobTooLargeError
                    digest.update(chunk)
                    yield chunk
            except BaseException as exc:
                stream_error = exc
                raise

        try:
            await obstore.put_async(self._store, key, hashed())
        except BaseException as exc:
            # A failed upload must not leave a partial object behind under a key nobody records.
            # The clean-up is shielded from a second cancellation, and its own failure must not
            # hide why the upload failed.
            with contextlib.suppress(Exception):
                await asyncio.shield(self.delete(key))
            if exc is stream_error or not isinstance(exc, Exception):
                raise
            raise _backend_error("put", exc) from None
        return StoredBlob(key=key, sha256=digest.hexdigest(), size=size)

    async def get(self, key: str, sha256: str) -> bytes:
        """Return the blob's bytes, or raise `BlobIntegrityError` if they changed since `put`."""
        if not _SHA256.fullmatch(sha256):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        _check_key(key)
        try:
            result = await obstore.get_async(self._store, key)
            data = bytes(await result.bytes_async())
        except FileNotFoundError:
            raise BlobNotFoundError from None
        except Exception as exc:
            raise _backend_error("get", exc) from None
        if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), sha256):
            raise BlobIntegrityError
        return data

    async def delete(self, key: str) -> None:
        """Delete the blob; deleting a missing key succeeds."""
        _check_key(key)
        try:
            await obstore.delete_async(self._store, key)
        except FileNotFoundError:
            pass
        except Exception as exc:
            raise _backend_error("delete", exc) from None

    async def exists(self, key: str) -> bool:
        _check_key(key)
        try:
            await obstore.head_async(self._store, key)
        except FileNotFoundError:
            return False
        except Exception as exc:
            raise _backend_error("exists", exc) from None
        return True

    async def older_than(self, cutoff: datetime) -> AsyncIterator[list[str]]:
        """Keys of blobs last written before `cutoff`, in batches; other objects are skipped."""
        try:
            async for batch in obstore.list(self._store, chunk_size=500):
                keys = [
                    meta["path"]
                    for meta in batch
                    if _KEY.fullmatch(meta["path"]) and meta["last_modified"] < cutoff
                ]
                if keys:
                    yield keys
        except Exception as exc:
            raise _backend_error("list", exc) from None


class LocalBlobStore(_ObjectBlobStore):
    """Blobs as files under `root`, created if missing."""

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)  # also an existing root: only the service user may read originals
        super().__init__(LocalStore(prefix=root.resolve()))


class S3BlobStore(_ObjectBlobStore):
    """Blobs as objects in a private S3-compatible bucket.

    Unset credentials fall back to the standard AWS chain (environment, web identity, instance
    metadata). The bucket must block public access and encrypt at rest; that is the operator's
    configuration (`docs/OPERATIONS.md`), not something a request here can change.
    """

    def __init__(self, settings: Settings) -> None:
        bucket = settings.knowledge_blob_bucket
        if bucket is None:  # settings validation requires it for the s3 backend
            raise ValueError("APP_KNOWLEDGE_BLOB_BUCKET is required for the s3 backend")
        config: dict[str, str] = {}
        if settings.knowledge_blob_endpoint is not None:
            config["endpoint"] = settings.knowledge_blob_endpoint
        if settings.knowledge_blob_region is not None:
            config["region"] = settings.knowledge_blob_region
        if settings.knowledge_blob_access_key_id is not None:
            config["access_key_id"] = settings.knowledge_blob_access_key_id.get_secret_value()
        if settings.knowledge_blob_secret_access_key is not None:
            config["secret_access_key"] = (
                settings.knowledge_blob_secret_access_key.get_secret_value()
            )
        allow_http = (settings.knowledge_blob_endpoint or "").startswith("http://")
        super().__init__(
            S3Store(
                bucket,
                config=config,  # type: ignore[arg-type]  # S3Config is a TypedDict of str values
                client_options={"allow_http": allow_http},
            )
        )


def build_blob_store(settings: Settings) -> BlobStore:
    if settings.knowledge_blob_backend == "s3":
        return S3BlobStore(settings)
    return LocalBlobStore(Path(settings.knowledge_blob_root))
