"""Microsoft Graph client for Teams online meetings (app-only).

Requires Entra app credentials + an Application Access Policy granting the
app permission to create meetings for TEAMS_ORGANIZER_UPN.

Does not touch applications, scoring, or existing notifications.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"


class TeamsGraphConfigError(RuntimeError):
    """Missing or incomplete Teams Graph environment configuration."""


class TeamsGraphApiError(RuntimeError):
    """Graph API returned an error response."""

    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Graph API {status_code}: {body}")


@dataclass(frozen=True)
class TeamsGraphConfig:
    tenant_id: str
    client_id: str
    client_secret: str
    organizer_upn: str

    @classmethod
    def from_env(cls) -> TeamsGraphConfig:
        tenant_id = os.environ.get("TEAMS_TENANT_ID", "").strip()
        client_id = os.environ.get("TEAMS_CLIENT_ID", "").strip()
        client_secret = os.environ.get("TEAMS_CLIENT_SECRET", "").strip()
        organizer_upn = os.environ.get("TEAMS_ORGANIZER_UPN", "").strip()
        missing = [
            name
            for name, value in (
                ("TEAMS_TENANT_ID", tenant_id),
                ("TEAMS_CLIENT_ID", client_id),
                ("TEAMS_CLIENT_SECRET", client_secret),
                ("TEAMS_ORGANIZER_UPN", organizer_upn),
            )
            if not value
        ]
        if missing:
            raise TeamsGraphConfigError(
                "Teams Graph is not configured. Missing env: " + ", ".join(missing)
            )
        return cls(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
            organizer_upn=organizer_upn,
        )


@dataclass(frozen=True)
class CreatedOnlineMeeting:
    meeting_id: str
    join_url: str
    subject: str
    start_date_time: str
    end_date_time: str


def teams_graph_enabled() -> bool:
    """Feature flag — off by default so production is unchanged until opted in."""
    return os.environ.get("TEAMS_GRAPH_ENABLED", "").strip().lower() in {"1", "true", "yes"}


def _acquire_token(config: TeamsGraphConfig) -> str:
    token_url = TOKEN_URL_TEMPLATE.format(tenant_id=config.tenant_id)
    data = {
        "grant_type": "client_credentials",
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "scope": "https://graph.microsoft.com/.default",
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.post(token_url, data=data)
    if response.status_code >= 400:
        raise TeamsGraphApiError(response.status_code, response.text)
    token = response.json().get("access_token")
    if not token:
        raise TeamsGraphApiError(response.status_code, "No access_token in token response")
    return token


def _resolve_user_id(token: str, organizer_upn: str) -> str:
    """App-only onlineMeetings create requires a user object GUID, not UPN."""
    # Prefer optional override so demos can skip the lookup if needed.
    override = os.environ.get("TEAMS_ORGANIZER_OBJECT_ID", "").strip()
    if override:
        return override

    headers = {"Authorization": f"Bearer {token}"}
    upn_path = quote(organizer_upn, safe="")
    url = f"{GRAPH_BASE}/users/{upn_path}?$select=id,userPrincipalName"
    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=headers)
    if response.status_code >= 400:
        raise TeamsGraphApiError(response.status_code, response.text)
    user_id = response.json().get("id")
    if not user_id:
        raise TeamsGraphApiError(response.status_code, f"No id for user {organizer_upn}")
    return user_id


def create_online_meeting(
    *,
    subject: str,
    start: datetime | None = None,
    duration_minutes: int = 60,
    config: TeamsGraphConfig | None = None,
) -> CreatedOnlineMeeting:
    """Create a Teams online meeting as TEAMS_ORGANIZER_UPN via application permissions."""
    cfg = config or TeamsGraphConfig.from_env()
    if duration_minutes < 15 or duration_minutes > 240:
        raise ValueError("duration_minutes must be between 15 and 240")

    start_dt = start or (datetime.now(timezone.utc) + timedelta(hours=1))
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    token = _acquire_token(cfg)
    organizer_id = _resolve_user_id(token, cfg.organizer_upn)
    url = f"{GRAPH_BASE}/users/{organizer_id}/onlineMeetings"
    payload = {
        "subject": subject,
        "startDateTime": start_dt.isoformat().replace("+00:00", "Z"),
        "endDateTime": end_dt.isoformat().replace("+00:00", "Z"),
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, headers=headers, json=payload)
    if response.status_code >= 400:
        raise TeamsGraphApiError(response.status_code, response.text)

    body = response.json()
    meeting_id = body.get("id")
    join_url = body.get("joinWebUrl") or body.get("joinUrl")
    if not meeting_id or not join_url:
        raise TeamsGraphApiError(response.status_code, f"Unexpected meeting payload: {body}")

    return CreatedOnlineMeeting(
        meeting_id=meeting_id,
        join_url=join_url,
        subject=body.get("subject") or subject,
        start_date_time=body.get("startDateTime") or payload["startDateTime"],
        end_date_time=body.get("endDateTime") or payload["endDateTime"],
    )
