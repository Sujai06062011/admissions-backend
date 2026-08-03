import logging
import os
from datetime import date, datetime, timedelta, timezone

import resend

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# Hardcoded for the demo — there's only one deployed candidate portal right
# now. Move to an env var once there's a real need to point at more than one
# frontend deployment (e.g. staging vs prod).
CAMPUS_LOGIN_URL = "https://admissions-frontend-phi.vercel.app/campus"


def _format_ist(dt: datetime) -> str:
    return dt.astimezone(IST).strftime("%d %b %Y %I:%M%p IST")


def _from_header() -> str:
    """Builds the "From" header as "Display Name <address>" so inboxes show a
    friendly sender name instead of the raw mailbox address. Override the name
    via RESEND_FROM_NAME if needed; defaults to "Admissions Department".
    """
    from_email = os.environ["RESEND_FROM_EMAIL"]
    from_name = os.environ.get("RESEND_FROM_NAME", "Admissions Department")
    return f"{from_name} <{from_email}>"


def send_invite_email(
    to_email: str | None,
    applicant_name: str | None,
    program_name: str,
    applied_at: datetime,
    campus_date: date,
    temp_username: str,
    temp_password: str,
    expires_at: datetime,
    application_number: str,
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
    from_email = _from_header()

    greeting_name = applicant_name or "Applicant"
    subject = "Your Application Has Moved to the Next Stage"
    html = (
        f"<p>Dear {greeting_name},</p>"
        f"<p><b>Application No:</b> {application_number}<br>"
        f"<b>Program Applied For:</b> {program_name}<br>"
        f"<b>Applied On:</b> {_format_ist(applied_at)}<br>"
        f"<b>Current Status:</b> Your application has moved to the next stage.<br>"
        f"<b>Campus Test Date:</b> {campus_date.strftime('%d %b %Y')}</p>"
        "<p>Use the credentials below to log in and take your test.</p>"
        f"<p><b>Username:</b> {temp_username}<br>"
        f"<b>Password:</b> {temp_password}</p>"
        f"<p>These credentials expire at {_format_ist(expires_at)}.</p>"
        f'<p><a href="{CAMPUS_LOGIN_URL}">{CAMPUS_LOGIN_URL}</a></p>'
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


def send_interview_invite_email(
    to_email: str | None,
    applicant_name: str | None,
    program_name: str,
    scheduled_at: datetime,
) -> tuple[bool, str]:
    """Sends the final-interview invite email through Resend, once an
    interview has actually been scheduled. Same pattern and (success, detail)
    contract as send_invite_email above — never raises, callers use the
    return value to set Notification.status.
    """
    if not to_email:
        return False, "applicant has no email address on file"

    resend.api_key = os.environ["RESEND_API_KEY"]
    from_email = _from_header()

    greeting_name = applicant_name or "Applicant"
    subject = "Your Interview Has Been Scheduled"
    html = (
        f"<p>Dear {greeting_name},</p>"
        f"<p><b>Program:</b> {program_name}<br>"
        f"<b>Interview Date &amp; Time:</b> {_format_ist(scheduled_at)}</p>"
        "<p>Please be available at the scheduled time. Further details will "
        "follow separately if needed.</p>"
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
        logger.error("Resend interview-invite email failed for %s: %s", to_email, exc)
        return False, str(exc)


def send_gd_invite_email(
    to_email: str | None,
    applicant_name: str | None,
    program_name: str,
    session_label: str,
    scheduled_at: datetime,
    duration_minutes: int,
    join_url: str,
    application_number: str | None,
) -> tuple[bool, str]:
    """Sends a Group Discussion Teams invite via Resend. Same contract as SMTP."""
    if not to_email:
        return False, "applicant has no email address on file"

    resend.api_key = os.environ["RESEND_API_KEY"]
    from_email = _from_header()

    greeting_name = applicant_name or "Applicant"
    app_line = (
        f"<b>Application No:</b> {application_number}<br>" if application_number else ""
    )
    subject = "Your Group Discussion Has Been Scheduled"
    html = (
        f"<p>Dear {greeting_name},</p>"
        f"<p>{app_line}"
        f"<b>Program:</b> {program_name}<br>"
        f"<b>Group:</b> {session_label}<br>"
        f"<b>Date &amp; Time:</b> {_format_ist(scheduled_at)}<br>"
        f"<b>Duration:</b> {duration_minutes} minutes</p>"
        "<p>Please join the Microsoft Teams meeting using the link below:</p>"
        f'<p><a href="{join_url}">{join_url}</a></p>'
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
        logger.error("Resend GD-invite email failed for %s: %s", to_email, exc)
        return False, str(exc)
