import os
import uuid
from pathlib import Path

from fastapi import UploadFile
from supabase import Client, create_client

RECORDINGS_BUCKET = "recordings"
PROCTORING_SNAPSHOTS_BUCKET = "proctoring-snapshots"

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(
            os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        )
    return _client


def save_recording(application_id: uuid.UUID, upload: UploadFile) -> str:
    """Persists an uploaded interview recording to the Supabase 'recordings'
    storage bucket and returns its file_url.

    Same pattern as app/applications/storage.py's save_upload: the returned
    value is the object's path within the bucket, not a public URL — the
    bucket is accessed with the service role key, so retrieval elsewhere
    should go through a signed URL.
    """
    suffix = Path(upload.filename or "").suffix
    object_path = f"{application_id}/{uuid.uuid4()}{suffix}"

    _get_client().storage.from_(RECORDINGS_BUCKET).upload(
        object_path,
        upload.file.read(),
        {"content-type": upload.content_type or "application/octet-stream"},
    )

    return object_path


def download_recording(object_path: str) -> bytes:
    """Downloads a recording's raw bytes from the Supabase 'recordings' bucket."""
    return _get_client().storage.from_(RECORDINGS_BUCKET).download(object_path)


def create_recording_signed_url(object_path: str, expires_in: int) -> str:
    """Generates a temporary signed URL for a private 'recordings' bucket
    object, valid for expires_in seconds — same pattern as
    app/applications/storage.py's create_document_signed_url.
    """
    response = _get_client().storage.from_(RECORDINGS_BUCKET).create_signed_url(
        object_path, expires_in
    )
    return response["signedURL"]


def save_snapshot(application_id: uuid.UUID, image_bytes: bytes, index: int) -> str:
    """Persists one proctoring snapshot (a JPEG frame grabbed client-side from
    the live interview camera feed) to the private 'proctoring-snapshots'
    bucket and returns its object path. `index` is just folded into the
    object name for readability in the bucket browser — it carries no
    ordering guarantee on its own, so callers that care about order should
    rely on the order snapshot_urls are stored in on TestBSession, not on
    this index.
    """
    object_path = f"{application_id}/snapshot-{index}-{uuid.uuid4()}.jpg"

    _get_client().storage.from_(PROCTORING_SNAPSHOTS_BUCKET).upload(
        object_path,
        image_bytes,
        {"content-type": "image/jpeg"},
    )

    return object_path


def download_snapshot(object_path: str) -> bytes:
    """Downloads a proctoring snapshot's raw bytes from the
    'proctoring-snapshots' bucket — used by the async Claude vision review
    step, which needs the actual image bytes rather than a signed URL.
    """
    return _get_client().storage.from_(PROCTORING_SNAPSHOTS_BUCKET).download(object_path)


def create_snapshot_signed_url(object_path: str, expires_in: int) -> str:
    """Generates a temporary signed URL for a private 'proctoring-snapshots'
    bucket object, valid for expires_in seconds — used by the admin drawer to
    render snapshot thumbnails.
    """
    response = _get_client().storage.from_(PROCTORING_SNAPSHOTS_BUCKET).create_signed_url(
        object_path, expires_in
    )
    return response["signedURL"]
