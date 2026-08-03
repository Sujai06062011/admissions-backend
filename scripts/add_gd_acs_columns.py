"""Add ACS / host-start columns to gd_sessions.

Usage:
    python scripts/add_gd_acs_columns.py
    # or: railway run python scripts/add_gd_acs_columns.py
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
                  ADD COLUMN IF NOT EXISTS topic TEXT,
                  ADD COLUMN IF NOT EXISTS professor_name TEXT,
                  ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
                  ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ,
                  ADD COLUMN IF NOT EXISTS join_opens_minutes_before INTEGER DEFAULT 10,
                  ADD COLUMN IF NOT EXISTS track TEXT DEFAULT 'online';
                """
            )
        )
    print("gd_sessions: ACS / host-start columns ready.")


if __name__ == "__main__":
    main()
