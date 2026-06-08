"""Thin Google Cloud Storage helpers used by the mirror and extract stages.

Authentication is ambient: the cloud-bootstrap SessionStart hook activates the
``claude-agent`` service account, so the default client picks it up with no
explicit key handling here.
"""
from __future__ import annotations

from functools import lru_cache

from google.cloud import storage

from . import config


@lru_cache(maxsize=1)
def _bucket() -> storage.Bucket:
    client = storage.Client(project=config.PROJECT)
    return client.bucket(config.BUCKET)


def exists(path: str) -> bool:
    return _bucket().blob(path).exists()


def size(path: str) -> int | None:
    blob = _bucket().get_blob(path)
    return None if blob is None else blob.size


def list_names(prefix: str) -> list[str]:
    """List object names (not gs:// URIs) under a prefix."""
    return [b.name for b in _bucket().list_blobs(prefix=prefix)]


def upload_file(local_path: str, dest_path: str) -> None:
    _bucket().blob(dest_path).upload_from_filename(local_path)


def download_file(src_path: str, local_path: str) -> None:
    _bucket().blob(src_path).download_to_filename(local_path)


def upload_stream(fileobj, dest_path: str, content_type: str | None = None) -> None:
    # chunk_size makes large, non-seekable streams (e.g. a 1.6 GB ZIP piped
    # straight from S3) upload as a resumable chunked PUT rather than being
    # buffered whole in memory.
    blob = _bucket().blob(dest_path, chunk_size=40 * 1024 * 1024)
    blob.upload_from_file(fileobj, content_type=content_type)
