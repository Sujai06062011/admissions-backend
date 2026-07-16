import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def send_invite_whatsapp(
    phone: str | None, temp_username: str, temp_password: str, expires_at: datetime
) -> tuple[bool, str]:
    """Stub for the WhatsApp campus-invite message.

    Not wired up to the Meta Cloud API yet — waiting on template approval. Logs
    what would be sent and reports it as delivered so the invite pipeline isn't
    blocked on it. Swap the body for a real API call later: the (bool, detail)
    return signature matches send_invite_email, so callers don't change.
    """
    if not phone:
        return False, "applicant has no phone number on file"

    logger.info(
        "[WhatsApp stub] would send to %s: username=%s password=%s expires_at=%s",
        phone,
        temp_username,
        temp_password,
        expires_at.isoformat(),
    )
    return True, "stubbed - not actually sent"
