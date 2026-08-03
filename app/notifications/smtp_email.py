import logging
import os
import smtplib
from datetime import date, datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# Hardcoded for the demo — there's only one deployed candidate portal right
# now. Move to an env var once there's a real need to point at more than one
# frontend deployment (e.g. staging vs prod).
CAMPUS_LOGIN_URL = "https://admissions-frontend-phi.vercel.app/campus"


def _format_ist(dt: datetime) -> str:
    return dt.astimezone(IST).strftime("%d %b %Y %I:%M%p IST")


def _send_smtp_email(to_email: str, subject: str, html: str) -> tuple[bool, str]:
    """Sends one HTML email over SMTPS (implicit TLS) using Google Workspace /
    Gmail's smtp.gmail.com relay. SMTP_USER is both the login and the envelope
    "from" address — Gmail rejects sends where the From header doesn't match
    the authenticated account. Never raises: callers persist the return value
    straight into Notification.status, so a delivery failure shouldn't blow up
    the request that triggered it.
    """
    host = os.environ["SMTP_HOST"]
    port = int(os.environ["SMTP_PORT"])
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASS"]
    from_name = os.environ.get("SMTP_FROM_NAME", "Admissions Team")

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = formataddr((from_name, user))
    message["To"] = to_email
    message.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL(host, port, timeout=15) as server:
            server.login(user, password)
            server.sendmail(user, [to_email], message.as_string())
        return True, "sent via smtp"
    except (smtplib.SMTPException, OSError) as exc:
        logger.error("SMTP email send failed for %s: %s", to_email, exc)
        return False, str(exc)


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
    """Sends the campus-invite email through Google Workspace SMTP.

    Returns (success, detail): detail is "sent via smtp" on success, or a
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

    return _send_smtp_email(to_email, subject, html)


def send_interview_invite_email(
    to_email: str | None,
    applicant_name: str | None,
    program_name: str,
    scheduled_at: datetime,
) -> tuple[bool, str]:
    """Sends the final-interview invite email through Google Workspace SMTP,
    once an interview has actually been scheduled. Same pattern and
    (success, detail) contract as send_invite_email above — never raises,
    callers use the return value to set Notification.status.
    """
    if not to_email:
        return False, "applicant has no email address on file"

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

    return _send_smtp_email(to_email, subject, html)


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
    """Sends a Group Discussion Teams invite. Same (success, detail) contract."""
    if not to_email:
        return False, "applicant has no email address on file"

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
    return _send_smtp_email(to_email, subject, html)


def send_gd_moderator_invite_email(
    to_email: str | None,
    moderator_name: str | None,
    program_name: str,
    session_label: str,
    scheduled_at: datetime,
    duration_minutes: int,
    join_url: str,
) -> tuple[bool, str]:
    """Sends the GD Teams join link to the college moderator / professor."""
    if not to_email:
        return False, "moderator has no email address"

    greeting_name = moderator_name or "Moderator"
    subject = "Group Discussion — Moderator Join Link"
    html = (
        f"<p>Dear {greeting_name},</p>"
        f"<p>You are listed as the moderator for this Group Discussion.</p>"
        f"<p><b>Program:</b> {program_name}<br>"
        f"<b>Group:</b> {session_label}<br>"
        f"<b>Date &amp; Time:</b> {_format_ist(scheduled_at)}<br>"
        f"<b>Duration:</b> {duration_minutes} minutes</p>"
        "<p>Join as host / moderator using the Microsoft Teams link below "
        "(prefer signing in with the Parroworks organizer account so you can admit lobby guests):</p>"
        f'<p><a href="{join_url}">{join_url}</a></p>'
        "<p>Please enable <b>Record</b> and <b>Transcribe</b> during the session.</p>"
        "<p>Regards,<br>Admin Team</p>"
        '<p style="color:#888;font-size:12px;">Do not reply to this auto-generated email.</p>'
    )
    return _send_smtp_email(to_email, subject, html)
