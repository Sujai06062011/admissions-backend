"""Add recording/transcript columns to gd_sessions.

Usage:
    python scripts/add_gd_artifact_columns.py
    # or: railway run python scripts/add_gd_artifact_columns.py
"""

import sys

from sqlalchemy import create_engine, text

sys.path.insert(0, ".")

from app.db.session import DATABASE_URL  # noqa: E402


def main() -> None:
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE gd_sessions
                  ADD COLUMN IF NOT EXISTS recording_storage_path TEXT,
                  ADD COLUMN IF NOT EXISTS recording_graph_id TEXT,
                  ADD COLUMN IF NOT EXISTS transcript_text TEXT,
                  ADD COLUMN IF NOT EXISTS transcript_vtt TEXT,
                  ADD COLUMN IF NOT EXISTS transcript_graph_id TEXT,
                  ADD COLUMN IF NOT EXISTS artifacts_status TEXT DEFAULT 'pending',
                  ADD COLUMN IF NOT EXISTS artifacts_error TEXT,
                  ADD COLUMN IF NOT EXISTS artifacts_fetched_at TIMESTAMPTZ;
                """
            )
        )
    print("gd_sessions: artifact columns ready.")


if __name__ == "__main__":
    main()
