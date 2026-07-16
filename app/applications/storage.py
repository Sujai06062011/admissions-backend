import os
import uuid
from pathlib import Path

from fastapi import UploadFile
from supabase import Client, create_client

DOCUMENTS_BUCKET = "documents"

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(
            os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        )
    return _client


def save_upload(application_id: uuid.UUID, upload: UploadFile) -> str:
    """Persists an uploaded file to the Supabase 'documents' storage bucket and returns its file_url.

    The returned value is the object's path within the bucket, not a public URL —
    the bucket is accessed with the service role key, so retrieval elsewhere should
    go through a signed URL. Swap the body of this function again if the storage
    backend changes; callers only depend on getting a file_url string back.
    """
    suffix = Path(upload.filename or "").suffix
    object_path = f"{application_id}/{uuid.uuid4()}{suffix}"

    _get_client().storage.from_(DOCUMENTS_BUCKET).upload(
        object_path,
        upload.file.read(),
        {"content-type": upload.content_type or "application/octet-stream"},
    )

    return object_path
