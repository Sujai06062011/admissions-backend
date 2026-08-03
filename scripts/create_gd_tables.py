"""Create Group Discussion tables (gd_sessions, gd_participants).

Usage:
    railway run python scripts/create_gd_tables.py
    # or locally with DATABASE_URL set:
    python scripts/create_gd_tables.py

Safe to re-run (IF NOT EXISTS). Does not alter applications or existing stages.
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
                CREATE TABLE IF NOT EXISTS gd_sessions (
                  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                  program_id UUID NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
                  label TEXT,
                  target_size INTEGER NOT NULL DEFAULT 5,
                  scheduled_at TIMESTAMPTZ,
                  duration_minutes INTEGER NOT NULL DEFAULT 60,
                  assignment_strategy TEXT NOT NULL DEFAULT 'manual',
                  status TEXT NOT NULL DEFAULT 'draft',
                  track TEXT NOT NULL DEFAULT 'online',
                  teams_meeting_id TEXT,
                  join_url TEXT,
                  topic TEXT,
                  professor_email TEXT,
                  professor_name TEXT,
                  started_at TIMESTAMPTZ,
                  ended_at TIMESTAMPTZ,
                  join_opens_minutes_before INTEGER DEFAULT 10,
                  created_by UUID REFERENCES admin_users(id),
                  created_at TIMESTAMPTZ DEFAULT now(),
                  updated_at TIMESTAMPTZ DEFAULT now()
                );

                CREATE INDEX IF NOT EXISTS idx_gd_sessions_program ON gd_sessions(program_id);
                CREATE INDEX IF NOT EXISTS idx_gd_sessions_status ON gd_sessions(status);

                CREATE TABLE IF NOT EXISTS gd_participants (
                  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                  gd_session_id UUID NOT NULL REFERENCES gd_sessions(id) ON DELETE CASCADE,
                  application_id UUID NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                  role TEXT NOT NULL DEFAULT 'candidate',
                  invite_sent_at TIMESTAMPTZ,
                  invite_status TEXT DEFAULT 'pending',
                  created_at TIMESTAMPTZ DEFAULT now(),
                  CONSTRAINT uq_gd_participant_session_app UNIQUE (gd_session_id, application_id)
                );

                CREATE INDEX IF NOT EXISTS idx_gd_participants_application
                  ON gd_participants(application_id);
                """
            )
        )
    print("gd_sessions + gd_participants tables ready.")


if __name__ == "__main__":
    main()
