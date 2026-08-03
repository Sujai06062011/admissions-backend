"""Add GDPI score columns to gd_participants.

Usage:
    python scripts/add_gd_score_columns.py
    # or paste the SQL into Supabase SQL editor
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
                ALTER TABLE gd_participants
                  ADD COLUMN IF NOT EXISTS scores JSONB,
                  ADD COLUMN IF NOT EXISTS overall_score NUMERIC,
                  ADD COLUMN IF NOT EXISTS score_rationale TEXT,
                  ADD COLUMN IF NOT EXISTS speaker_labels JSONB,
                  ADD COLUMN IF NOT EXISTS scoring_status TEXT,
                  ADD COLUMN IF NOT EXISTS scored_at TIMESTAMPTZ;
                """
            )
        )
    print("gd_participants: score columns ready.")


if __name__ == "__main__":
    main()
