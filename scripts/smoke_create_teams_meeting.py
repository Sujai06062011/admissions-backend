"""CLI smoke test: create one Teams online meeting via Microsoft Graph.

Usage (from admissions-backend, with env vars set):

  export TEAMS_GRAPH_ENABLED=true
  export TEAMS_TENANT_ID=...
  export TEAMS_CLIENT_ID=...
  export TEAMS_CLIENT_SECRET=...
  export TEAMS_ORGANIZER_UPN=Sujaikumar@Parroworks.onmicrosoft.com

  python scripts/smoke_create_teams_meeting.py

Does not touch the database or application pipeline.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `python scripts/...` without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.group_discussion.teams_graph import (
    TeamsGraphApiError,
    TeamsGraphConfigError,
    create_online_meeting,
    teams_graph_enabled,
)


def main() -> int:
    if not teams_graph_enabled():
        print("TEAMS_GRAPH_ENABLED is not true — refusing to call Graph.")
        return 1
    try:
        meeting = create_online_meeting(subject="Admit GD smoke test (CLI)")
    except TeamsGraphConfigError as exc:
        print(f"Config error: {exc}")
        return 1
    except TeamsGraphApiError as exc:
        print(f"Graph error {exc.status_code}:\n{exc.body}")
        return 1

    print("Meeting created successfully.")
    print(f"  id:      {meeting.meeting_id}")
    print(f"  subject: {meeting.subject}")
    print(f"  start:   {meeting.start_date_time}")
    print(f"  end:     {meeting.end_date_time}")
    print(f"  join:    {meeting.join_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
