"""Azure Communication Services identity tokens for Teams interop join.

Candidates/hosts join a Graph-created Teams meeting from a custom UI using an
ACS VoIP token + the meeting join URL. Feature-flagged; off until configured.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone


class AcsConfigError(RuntimeError):
    """Missing or incomplete ACS environment configuration."""


@dataclass(frozen=True)
class AcsConfig:
    connection_string: str

    @classmethod
    def from_env(cls) -> AcsConfig:
        connection_string = os.environ.get("ACS_CONNECTION_STRING", "").strip()
        if not connection_string:
            raise AcsConfigError(
                "ACS is not configured. Missing env: ACS_CONNECTION_STRING"
            )
        return cls(connection_string=connection_string)


@dataclass(frozen=True)
class AcsJoinCredentials:
    user_id: str
    token: str
    expires_on: datetime


def acs_enabled() -> bool:
    """Feature flag — off by default until an ACS resource is wired."""
    return os.environ.get("ACS_ENABLED", "").strip().lower() in {"1", "true", "yes"}


def issue_voip_join_token(*, config: AcsConfig | None = None) -> AcsJoinCredentials:
    """Create a fresh ACS identity + VoIP_JOIN token (join existing calls only)."""
    from azure.communication.identity import (
        CommunicationIdentityClient,
        CommunicationTokenScope,
    )

    cfg = config or AcsConfig.from_env()
    client = CommunicationIdentityClient.from_connection_string(cfg.connection_string)
    user, token_response = client.create_user_and_token(
        scopes=[CommunicationTokenScope.VOIP_JOIN]
    )
    user_id = user.properties["id"]
    expires_on = _coerce_expires_on(token_response.expires_on)
    return AcsJoinCredentials(
        user_id=user_id,
        token=token_response.token,
        expires_on=expires_on,
    )


def _coerce_expires_on(value: object) -> datetime:
    """Normalize ACS token expiry (Azure may return 7-digit fractional seconds)."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    # Trim fractional seconds to 6 digits for datetime.fromisoformat.
    match = re.match(
        r"^(?P<head>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
        r"(?:\.(?P<frac>\d+))?(?P<tz>.*)$",
        text,
    )
    if match:
        frac = (match.group("frac") or "")[:6].ljust(6, "0") if match.group("frac") else ""
        rebuilt = match.group("head")
        if frac:
            rebuilt += f".{frac}"
        rebuilt += match.group("tz") or ""
        return datetime.fromisoformat(rebuilt)
    return datetime.fromisoformat(text)
