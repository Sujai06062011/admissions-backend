"""One-off script to add the video-proctoring columns to test_b_sessions.

Usage (via Railway, so DATABASE_URL points at the live production DB):
    railway run python scripts/add_proctoring_columns.py

Not Alembic-managed — this repo does direct ALTER TABLE scripts for schema
changes (see scripts/seed_admin.py for the same DATABASE_URL pattern). Uses
IF NOT EXISTS so it's safe to re-run.
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
                ALTER TABLE test_b_sessions
                  ADD COLUMN IF NOT EXISTS snapshot_urls JSONB,
                  ADD COLUMN IF NOT EXISTS tab_switch_events JSONB,
                  ADD COLUMN IF NOT EXISTS proctoring_review JSONB
                """
            )
        )
    print("test_b_sessions: snapshot_urls, tab_switch_events, proctoring_review columns ready.")


if __name__ == "__main__":
    main()
