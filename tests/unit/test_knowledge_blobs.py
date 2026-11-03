# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""BlobStore for original files (ADR 0014; RAG-01.03)."""

from __future__ import annotations

import hashlib
import stat
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import obstore
import pytest
from obstore.store import MemoryStore
from pydantic import ValidationError
from tests.conftest import jwt_settings

from neuron_agent.config.settings import Settings
from neuron_agent.knowledge.blobs import (
    BlobIntegrityError,
    BlobNotFoundError,
    BlobStoreError,
    BlobTooLargeError,
    LocalBlobStore,
    S3BlobStore,
    _ObjectBlobStore,
    build_blob_store,
)

pytestmark = pytest.mark.anyio

_KEY_CHARS = set("0123456789abcdef")
_LIMIT = 1024


async def _chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


def _production(**overrides: object) -> Settings:
    return jwt_settings(
        env="production",
        checkpointer="postgres",
        postgres_dsn="postgresql://app@db.example.test/n?sslmode=verify-full",
        nvidia_api_key="nv-test",
        openai_api_key="sk-test",
        **overrides,
    )


@pytest.fixture(params=["local", "memory"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> _ObjectBlobStore:
    # `memory` stands in for S3: the same obstore calls against a non-filesystem store.
    if request.param == "local":
        return LocalBlobStore(tmp_path / "blobs")
    return _ObjectBlobStore(MemoryStore())


async def test_put_streams_and_returns_a_random_key_sha256_and_size(
    store: _ObjectBlobStore,
) -> None:
    blob = await store.put(_chunks(b"hello ", b"world"), max_bytes=_LIMIT)
    assert blob.sha256 == hashlib.sha256(b"hello world").hexdigest()
    assert blob.size == 11
    assert len(blob.key) == 32
    assert set(blob.key) <= _KEY_CHARS
    assert await store.get(blob.key, blob.sha256) == b"hello world"
    other = await store.put(_chunks(b"hello world"), max_bytes=_LIMIT)
    assert other.key != blob.key


# AC1: a user file name never reaches the key, and nothing is written outside the root.


async def test_keys_carry_no_user_path_and_stay_under_the_root(tmp_path: Path) -> None:
    root = tmp_path / "store" / "blobs"
    store = LocalBlobStore(root)
    # `put` has no name parameter at all; the upload's `../` name stays in the documents row.
    blob = await store.put(_chunks(b"secret"), max_bytes=_LIMIT)
    assert ".." not in blob.key and "/" not in blob.key
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert written == [root / blob.key]


@pytest.mark.parametrize("key", ["../../etc/passwd", "/etc/passwd", "a" * 31, "A" * 32, ""])
async def test_keys_that_are_not_store_keys_are_refused(store: _ObjectBlobStore, key: str) -> None:
    with pytest.raises(ValueError, match="32 lowercase hex"):
        await store.get(key, "0" * 64)
    with pytest.raises(ValueError, match="32 lowercase hex"):
        await store.delete(key)
    with pytest.raises(ValueError, match="32 lowercase hex"):
        await store.exists(key)


# AC2: bytes that changed since `put` raise a typed error.


async def test_get_refuses_bytes_whose_checksum_changed(tmp_path: Path) -> None:
    root = tmp_path / "blobs"
    store = LocalBlobStore(root)
    blob = await store.put(_chunks(b"original"), max_bytes=_LIMIT)
    (root / blob.key).write_bytes(b"tampered")
    with pytest.raises(BlobIntegrityError) as raised:
        await store.get(blob.key, blob.sha256)
    assert raised.value.code == "blob_checksum_mismatch"


async def test_get_refuses_a_wrong_recorded_checksum(store: _ObjectBlobStore) -> None:
    blob = await store.put(_chunks(b"original"), max_bytes=_LIMIT)
    with pytest.raises(BlobIntegrityError):
        await store.get(blob.key, hashlib.sha256(b"other").hexdigest())


async def test_get_of_a_missing_key_raises_not_found(store: _ObjectBlobStore) -> None:
    with pytest.raises(BlobNotFoundError):
        await store.get("0" * 32, "0" * 64)


# AC3: deleting twice succeeds.


async def test_delete_is_idempotent(store: _ObjectBlobStore) -> None:
    blob = await store.put(_chunks(b"bytes"), max_bytes=_LIMIT)
    assert await store.exists(blob.key)
    await store.delete(blob.key)
    assert not await store.exists(blob.key)
    await store.delete(blob.key)
    with pytest.raises(BlobNotFoundError):
        await store.get(blob.key, blob.sha256)


async def test_a_failed_upload_leaves_no_blob(tmp_path: Path) -> None:
    root = tmp_path / "blobs"
    store = LocalBlobStore(root)

    async def broken() -> AsyncIterator[bytes]:
        yield b"partial"
        raise OSError("client went away")

    with pytest.raises(OSError, match="client went away"):
        await store.put(broken(), max_bytes=_LIMIT)
    assert [p for p in root.rglob("*") if p.is_file()] == []


async def test_a_stream_over_the_limit_is_refused_and_leaves_no_blob(tmp_path: Path) -> None:
    root = tmp_path / "blobs"
    store = LocalBlobStore(root)
    with pytest.raises(BlobTooLargeError):
        await store.put(_chunks(b"x" * 600, b"x" * 600), max_bytes=1000)
    assert [p for p in root.rglob("*") if p.is_file()] == []
    exact = await store.put(_chunks(b"x" * 1000), max_bytes=1000)
    assert exact.size == 1000


async def test_backend_errors_are_typed_and_carry_no_path(
    store: _ObjectBlobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def denied(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("/srv/secret/root/0123 denied")

    for name in ("get_async", "delete_async", "head_async", "put_async"):
        monkeypatch.setattr(obstore, name, denied)
    calls = [
        store.get("0" * 32, "0" * 64),
        store.delete("0" * 32),
        store.exists("0" * 32),
        store.put(_chunks(b"x"), max_bytes=_LIMIT),
    ]
    for call in calls:
        with pytest.raises(BlobStoreError) as raised:
            await call
        assert raised.value.code == "blob_backend_error"
        assert "/srv/secret" not in str(raised.value)
        assert raised.value.__cause__ is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_an_existing_local_root_is_made_private(tmp_path: Path) -> None:
    root = tmp_path / "blobs"
    root.mkdir(mode=0o755)
    LocalBlobStore(root)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700


def test_whitespace_blob_settings_count_as_unset() -> None:
    with pytest.raises(ValidationError, match="BLOB_BUCKET is required"):
        Settings(env="test", knowledge_blob_backend="s3", knowledge_blob_bucket="   ")
    with pytest.raises(ValidationError, match="must be set together"):
        Settings(
            env="test",
            knowledge_blob_backend="s3",
            knowledge_blob_bucket="neuron-kb",
            knowledge_blob_access_key_id="AKIDEXAMPLE",
            knowledge_blob_secret_access_key="  ",  # noqa: S106
        )


# AC4: `local` in staging/production needs an explicit opt-in.


def test_local_store_is_refused_in_production_without_opt_in() -> None:
    with pytest.raises(ValidationError, match="BLOB_LOCAL_ALLOWED"):
        _production(knowledge_enabled=True)


def test_local_store_is_accepted_in_production_with_opt_in(tmp_path: Path) -> None:
    settings = _production(
        knowledge_enabled=True,
        knowledge_blob_local_allowed=True,
        knowledge_blob_root=str(tmp_path / "kb"),
    )
    assert settings.knowledge_blob_backend == "local"


def test_local_default_leaves_a_production_profile_without_knowledge_valid() -> None:
    assert _production().knowledge_blob_backend == "local"


def test_s3_store_is_accepted_in_production() -> None:
    settings = _production(
        knowledge_enabled=True, knowledge_blob_backend="s3", knowledge_blob_bucket="neuron-kb"
    )
    assert isinstance(build_blob_store(settings), S3BlobStore)


def test_s3_needs_a_bucket() -> None:
    with pytest.raises(ValidationError, match="BLOB_BUCKET is required"):
        Settings(env="test", knowledge_blob_backend="s3")


def test_s3_credentials_are_set_together() -> None:
    with pytest.raises(ValidationError, match="must be set together"):
        Settings(
            env="test",
            knowledge_blob_backend="s3",
            knowledge_blob_bucket="neuron-kb",
            knowledge_blob_access_key_id="AKIDEXAMPLE",
        )


@pytest.mark.parametrize(
    "endpoint",
    ["ftp://minio:9000", "https://user:pw@minio:9000", "https://minio:9000/?x=1", "minio:9000"],
)
def test_s3_endpoint_must_be_a_plain_http_url(endpoint: str) -> None:
    with pytest.raises(ValidationError, match="BLOB_ENDPOINT must be an http"):
        Settings(
            env="test",
            knowledge_blob_backend="s3",
            knowledge_blob_bucket="neuron-kb",
            knowledge_blob_endpoint=endpoint,
        )


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://169.254.169.254",
        "https://169.254.170.2:443",
        "http://[fd00:ec2::254]",
        "http://[fe80::1]:9000",
        "http://metadata.google.internal",
    ],
)
def test_s3_endpoint_refuses_metadata_addresses(endpoint: str) -> None:
    with pytest.raises(ValidationError, match="cloud metadata"):
        Settings(
            env="test",
            knowledge_blob_backend="s3",
            knowledge_blob_bucket="neuron-kb",
            knowledge_blob_endpoint=endpoint,
        )


@pytest.mark.parametrize("endpoint", ["http://minio:9000", "http://10.0.0.5:9000"])
def test_s3_endpoint_allows_private_self_hosted_servers(endpoint: str) -> None:
    settings = Settings(
        env="test",
        knowledge_blob_backend="s3",
        knowledge_blob_bucket="neuron-kb",
        knowledge_blob_endpoint=endpoint,
    )
    assert settings.knowledge_blob_endpoint == endpoint


@pytest.mark.parametrize("bucket", ["Neuron", "a/b", "ab", "-bucket", "bucket."])
def test_s3_bucket_must_be_a_valid_bucket_name(bucket: str) -> None:
    with pytest.raises(ValidationError, match="knowledge_blob_bucket"):
        Settings(env="test", knowledge_blob_backend="s3", knowledge_blob_bucket=bucket)


def test_local_root_must_be_absolute_in_production(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="ROOT must be an absolute path"):
        _production(knowledge_enabled=True, knowledge_blob_local_allowed=True)
    settings = _production(
        knowledge_enabled=True,
        knowledge_blob_local_allowed=True,
        knowledge_blob_root=str(tmp_path / "kb"),
    )
    assert Path(settings.knowledge_blob_root).is_absolute()


def test_s3_endpoint_must_use_https_in_production() -> None:
    with pytest.raises(ValidationError, match="must use https"):
        _production(
            knowledge_blob_backend="s3",
            knowledge_blob_bucket="neuron-kb",
            knowledge_blob_endpoint="http://minio:9000",
        )


def test_s3_secrets_are_not_shown() -> None:
    settings = Settings(
        env="test",
        knowledge_blob_backend="s3",
        knowledge_blob_bucket="neuron-kb",
        knowledge_blob_access_key_id="AKIDEXAMPLE",
        knowledge_blob_secret_access_key="not-a-real-secret",  # noqa: S106
    )
    assert "not-a-real-secret" not in repr(settings)
    assert "AKIDEXAMPLE" not in repr(settings)


def test_build_blob_store_defaults_to_a_local_directory(tmp_path: Path) -> None:
    settings = Settings(env="test", knowledge_blob_root=str(tmp_path / "kb"))
    assert isinstance(build_blob_store(settings), LocalBlobStore)
    assert (tmp_path / "kb").is_dir()
