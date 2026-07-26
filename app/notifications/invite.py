from sqlalchemy.orm import Session

from app.models.final import Notification
from app.models.scheduling import CampusSession
from app.models.stage1 import Application
from app.models.stage3_test_a import Credential
from app.notifications.email_dispatch import send_invite_email
from app.notifications.whatsapp_stub import send_invite_whatsapp


def send_campus_invite(
    db: Session,
    application: Application,
    credential: Credential,
    temp_password: str,
    campus_session: CampusSession,
) -> list[Notification]:
    """Sends the move-to-campus invite (temp login credentials + real assigned
    campus date) over email and WhatsApp, creates one Notification row per
    channel reflecting real delivery status, and updates
    credential.delivered_via to the channels that actually succeeded. Does not
    commit; the caller owns the transaction.
    """
    applicant = application.applicant
    notifications: list[Notification] = []
    delivered_channels: list[str] = []

    email_ok, _ = send_invite_email(
        to_email=applicant.email if applicant else None,
        applicant_name=applicant.full_name if applicant else None,
        program_name=application.program.name,
        applied_at=application.created_at,
        campus_date=campus_session.schedule.session_date,
        temp_username=credential.temp_username,
        temp_password=temp_password,
        expires_at=credential.expires_at,
    )
    notifications.append(
        Notification(
            application_id=application.id,
            channel="email",
            type="campus_invite",
            status="sent" if email_ok else "failed",
        )
    )
    if email_ok:
        delivered_channels.append("email")

    whatsapp_ok, _ = send_invite_whatsapp(
        phone=applicant.phone if applicant else None,
        temp_username=credential.temp_username,
        temp_password=temp_password,
        expires_at=credential.expires_at,
    )
    notifications.append(
        Notification(
            application_id=application.id,
            channel="whatsapp",
            type="campus_invite",
            status="sent" if whatsapp_ok else "failed",
        )
    )
    if whatsapp_ok:
        delivered_channels.append("whatsapp")

    db.add_all(notifications)
    credential.delivered_via = delivered_channels

    return notifications
