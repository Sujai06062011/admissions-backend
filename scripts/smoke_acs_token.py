"""CLI smoke: mint an ACS VoIP_JOIN token (no DB, no Teams).

Requires:
    ACS_ENABLED=true
    ACS_CONNECTION_STRING=endpoint=https://.../;accesskey=...

Usage:
    python scripts/smoke_acs_token.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, ".")


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

from app.group_discussion.acs import (  # noqa: E402
    AcsConfigError,
    acs_enabled,
    issue_voip_join_token,
)


def main() -> None:
    if not acs_enabled():
        print("Set ACS_ENABLED=true first.", file=sys.stderr)
        sys.exit(1)
    try:
        creds = issue_voip_join_token()
    except AcsConfigError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    print("ACS token minted OK")
    print(f"user_id: {creds.user_id}")
    print(f"expires_on: {creds.expires_on.isoformat()}")
    print(f"token_prefix: {creds.token[:24]}...")
    # Avoid dumping full token into logs by default.
    if os.environ.get("ACS_SMOKE_PRINT_TOKEN", "").strip().lower() in {"1", "true", "yes"}:
        print(f"token: {creds.token}")


if __name__ == "__main__":
    main()
