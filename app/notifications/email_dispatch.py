import os

from app.notifications import resend_email, smtp_email

# EMAIL_PROVIDER selects which backend actually sends mail. Defaults to our
# own Google Workspace SMTP relay; set EMAIL_PROVIDER=resend to fall back to
# the dormant Resend integration (e.g. if the SMTP relay ever gets rate
# limited or blocked) without touching any call sites.
_PROVIDER = os.environ.get("EMAIL_PROVIDER", "smtp").strip().lower()
_active_module = resend_email if _PROVIDER == "resend" else smtp_email

send_invite_email = _active_module.send_invite_email
send_interview_invite_email = _active_module.send_interview_invite_email
send_gd_invite_email = _active_module.send_gd_invite_email
