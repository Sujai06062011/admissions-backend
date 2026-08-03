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

### 2b. Azure Communication Services (custom UI join)

Create an ACS resource in Azure → Keys → connection string.

```bash
export ACS_ENABLED=true
export ACS_CONNECTION_STRING="endpoint=https://....communication.azure.com/;accesskey=..."
export GD_JOIN_OPENS_MINUTES_BEFORE=10
export CAMPUS_PORTAL_BASE_URL="https://admissions-frontend-phi.vercel.app/campus"
```

Schema migration for topic / host-start / join window:

```bash
python scripts/add_gd_acs_columns.py
```

ACS token smoke (no meeting):

```bash
python scripts/smoke_acs_token.py
# or: POST /admin/group-discussion/smoke/acs-token
```

Join an existing GD session from curl (admin, bypasses join window):

```bash
POST /admin/group-discussion/sessions/{id}/acs-join
{"role":"host","display_name":"Prof Test","bypass_join_window":true}
```

Candidate join (enforces T−N window, no topic until host Start):

```bash
POST /campus/group-discussion/sessions/{id}/acs-join
{"application_id":"<uuid>"}
```

Host Start (reveals topic):

```bash
POST /admin/group-discussion/sessions/{id}/start
```

### 3. Admin API flow

All routes require admin bearer token (except `/campus/group-discussion/*`).

| Method | Path | Purpose |
|---|---|---|
| GET | `/admin/group-discussion/eligible?program_id=` | Pool: both tests done, not in active GD |
| POST | `/admin/group-discussion/sessions` | Create draft (+ optional auto-assign) |
| PATCH | `/admin/group-discussion/sessions/{id}` | Topic, moderator, schedule, join window |
| POST | `/admin/group-discussion/sessions/{id}/assign` | Re-assign (composite / gender_mix / random / manual) |
| POST | `/admin/group-discussion/sessions/{id}/create-meeting` | Teams meeting (auto-record + lobby bypass) |
| POST | `/admin/group-discussion/sessions/{id}/enable-recording` | PATCH older meetings to auto-record |
| POST | `/admin/group-discussion/sessions/{id}/send-invites` | Portal invite + regen temp password (no Teams URL) |
| POST | `/admin/group-discussion/sessions/{id}/start` | Host Start — topic + timer |
| POST | `/admin/group-discussion/sessions/{id}/acs-join` | ACS token + meeting URL (admin/host test) |
| POST | `/campus/group-discussion/sessions/{id}/acs-join` | Candidate ACS join (join window + topic gate) |
| POST | `/admin/group-discussion/sessions/{id}/fetch-artifacts` | After call: recording → Supabase, transcript → DB |
| POST | `/admin/group-discussion/sessions/{id}/upload-transcript` | Manual VTT/plain transcript if Graph blocked |
| POST | `/admin/group-discussion/sessions/{id}/score` | Claude GDPI scores per participant |
| GET | `/admin/group-discussion/sessions?program_id=` | List |
| GET | `/admin/group-discussion/sessions/{id}` | Detail |
| POST | `/admin/group-discussion/smoke/create-meeting` | Graph-only smoke (no DB) |
| POST | `/admin/group-discussion/smoke/acs-token` | ACS token smoke (no DB) |

Schema migration for artifact columns:

```bash
python scripts/add_gd_artifact_columns.py
```

After a meeting ends, wait a few minutes for Teams to finish processing, then call
`fetch-artifacts`. Graph webhooks can replace polling later.

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
