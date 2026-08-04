"""Create gd_program_settings table.

Usage:
    railway run python scripts/create_gd_settings_table.py
"""

from __future__ import annotations

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
                CREATE TABLE IF NOT EXISTS gd_program_settings (
                  program_id UUID PRIMARY KEY REFERENCES programs(id) ON DELETE CASCADE,
                  min_group_size INTEGER NOT NULL DEFAULT 5,
                  max_group_size INTEGER NOT NULL DEFAULT 7,
                  default_duration_minutes INTEGER NOT NULL DEFAULT 30,
                  updated_at TIMESTAMPTZ DEFAULT now()
                );
                """
            )
        )
    print("gd_program_settings ready")


if __name__ == "__main__":
    main()
