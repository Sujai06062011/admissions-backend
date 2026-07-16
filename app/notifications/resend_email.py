import logging
import os
from datetime import datetime

import resend

logger = logging.getLogger(__name__)


def send_invite_email(
    to_email: str | None, temp_username: str, temp_password: str, expires_at: datetime
) -> tuple[bool, str]:
    """Sends the campus-invite email through Resend.

    Returns (success, detail): detail is the Resend message id on success, or a
    human-readable failure reason otherwise. Never raises — callers use the
    return value to set Notification.status, so a delivery failure shouldn't
    blow up the request that triggered it.
    """
    if not to_email:
        return False, "applicant has no email address on file"

    resend.api_key = os.environ["RESEND_API_KEY"]
    from_email = os.environ["RESEND_FROM_EMAIL"]

    subject = "Your admissions test login details"
    html = (
        "<p>Your application has moved to the next stage. Use the credentials "
        "below to log in and take your test.</p>"
        f"<p><b>Username:</b> {temp_username}<br>"
        f"<b>Password:</b> {temp_password}</p>"
        f"<p>These credentials expire at {expires_at.isoformat()}.</p>"
    )

    try:
        response = resend.Emails.send(
            {"from": from_email, "to": to_email, "subject": subject, "html": html}
        )
        message_id = response.get("id", "") if isinstance(response, dict) else getattr(response, "id", "")
        return True, message_id
    except resend.exceptions.ResendError as exc:
        logger.error("Resend email send failed for %s: %s", to_email, exc)
        return False, str(exc)
