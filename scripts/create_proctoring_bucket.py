"""One-off script to create the private 'proctoring-snapshots' Supabase
storage bucket, mirroring how 'documents' and 'recordings' already exist.

Usage (via Railway, so SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY point at the
live project):
    railway run python scripts/create_proctoring_bucket.py
"""

import os
import sys

from supabase import create_client
from storage3.utils import StorageException

sys.path.insert(0, ".")

from app.interview_engine.storage import PROCTORING_SNAPSHOTS_BUCKET  # noqa: E402


def main() -> None:
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    try:
        client.storage.create_bucket(
            PROCTORING_SNAPSHOTS_BUCKET,
            options={"public": False},
        )
        print(f"Bucket '{PROCTORING_SNAPSHOTS_BUCKET}' created (private).")
    except StorageException as exc:
        message = str(exc)
        if "already exists" in message.lower() or "duplicate" in message.lower():
            print(f"Bucket '{PROCTORING_SNAPSHOTS_BUCKET}' already exists — nothing to do.")
        else:
            raise


if __name__ == "__main__":
    main()
