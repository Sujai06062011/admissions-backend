import logging
import os
from datetime import date, datetime, timedelta, timezone

import resend

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


def _format_ist(dt: datetime) -> str:
    return dt.astimezone(IST).strftime("%d %b %Y %I:%M%p IST")


def send_invite_email(
    to_email: str | None,
    applicant_name: str | None,
    program_name: str,
    applied_at: datetime,
    campus_date: date,
    temp_username: str,
    temp_password: str,
    expires_at: datetime,
) -> tuple[bool, str]:
    """Sends the campus-invite email through Resend.

    Returns (success, detail): detail is the Resend message id on success, or a
    human-readable failure reason otherwise. Never raises — callers use the
    return value to set Notification.status, so a delivery failure shouldn't
    blow up the request that triggered it.

    campus_date is the real assigned CampusSchedule.session_date — shown as a
    date only, no clock time, since CampusSchedule doesn't carry a time-of-day
    and CampusSession.slot_time isn't populated by the assignment logic. Still
    deliberately leaves out a campus address: there's no such field anywhere in
    the schema, and this email goes to real applicants, so it shouldn't show a
    fabricated value.
    """
    if not to_email:
        return False, "applicant has no email address on file"

    resend.api_key = os.environ["RESEND_API_KEY"]
    from_email = os.environ["RESEND_FROM_EMAIL"]

    greeting_name = applicant_name or "Applicant"
    subject = "Your Application Has Moved to the Next Stage"
    html = (
        f"<p>Dear {greeting_name},</p>"
        f"<p><b>Program Applied For:</b> {program_name}<br>"
        f"<b>Applied On:</b> {_format_ist(applied_at)}<br>"
        f"<b>Current Status:</b> Your application has moved to the next stage.<br>"
        f"<b>Campus Test Date:</b> {campus_date.strftime('%d %b %Y')}</p>"
        "<p>Use the credentials below to log in and take your test.</p>"
        f"<p><b>Username:</b> {temp_username}<br>"
        f"<b>Password:</b> {temp_password}</p>"
        f"<p>These credentials expire at {_format_ist(expires_at)}.</p>"
        "<p>Regards,<br>Admin Team</p>"
        '<p style="color:#888;font-size:12px;">Do not reply to this auto-generated email.</p>'
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
