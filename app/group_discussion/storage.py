"""Supabase storage for GD meeting recordings (private recordings bucket)."""

from __future__ import annotations

import os
import uuid

from supabase import Client, create_client

from app.interview_engine.storage import RECORDINGS_BUCKET

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(
            os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        )
    return _client


def save_gd_recording(
    session_id: uuid.UUID,
    content: bytes,
    *,
    content_type: str = "video/mp4",
    suffix: str = ".mp4",
) -> str:
    """Upload GD meeting video; returns object path inside the recordings bucket."""
    object_path = f"gd/{session_id}/{uuid.uuid4()}{suffix}"
    _get_client().storage.from_(RECORDINGS_BUCKET).upload(
        object_path,
        content,
        {"content-type": content_type or "video/mp4"},
    )
    return object_path
