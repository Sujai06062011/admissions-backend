import os
import uuid
from pathlib import Path

from fastapi import UploadFile
from supabase import Client, create_client

RECORDINGS_BUCKET = "recordings"

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
