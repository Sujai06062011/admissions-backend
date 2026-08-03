# Admissions Backend

## Group Discussion (GD)

Additive APIs under `/admin/group-discussion/*`. They do **not** change
`Application.status` or existing Campus Interview → Final Interview flows.

### 1. Create tables (one-time)

```bash
python scripts/create_gd_tables.py
# or: railway run python scripts/create_gd_tables.py
```

### 2. Teams Graph env (meeting create)

```bash
export TEAMS_GRAPH_ENABLED=true
export TEAMS_TENANT_ID="<directory-tenant-id>"
export TEAMS_CLIENT_ID="<application-client-id>"
export TEAMS_CLIENT_SECRET="<client-secret-value>"   # Value, not Secret ID
export TEAMS_ORGANIZER_UPN="Sujaikumar@Parroworks.onmicrosoft.com"
# optional: TEAMS_ORGANIZER_OBJECT_ID=<guid>
```

### 3. Admin API flow

All routes require admin bearer token.

| Method | Path | Purpose |
|---|---|---|
| GET | `/admin/group-discussion/eligible?program_id=` | Pool: both tests done, not in active GD |
| POST | `/admin/group-discussion/sessions` | Create draft (+ optional auto-assign) |
| POST | `/admin/group-discussion/sessions/{id}/assign` | Re-assign (composite / gender_mix / random / manual) |
| POST | `/admin/group-discussion/sessions/{id}/create-meeting` | Teams meeting → store join_url |
| POST | `/admin/group-discussion/sessions/{id}/send-invites` | Email each participant |
| GET | `/admin/group-discussion/sessions?program_id=` | List |
| GET | `/admin/group-discussion/sessions/{id}` | Detail |
| POST | `/admin/group-discussion/smoke/create-meeting` | Graph-only smoke (no DB) |

Example create body:

```json
{
  "program_id": "<uuid>",
  "label": "GD-235",
  "target_size": 5,
  "scheduled_at": "2026-08-10T10:00:00+05:30",
  "duration_minutes": 60,
  "assignment_strategy": "composite",
  "auto_assign": true
}
```

### CLI Graph smoke (no DB)

```bash
python scripts/smoke_create_teams_meeting.py
```
