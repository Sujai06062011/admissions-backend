import secrets
import string
from datetime import datetime, timedelta, timezone

import bcrypt
from sqlalchemy.orm import Session

from app.models.stage1 import Application
from app.models.stage3_test_a import Credential

USERNAME_ALPHABET = string.ascii_lowercase + string.digits
# Excludes visually ambiguous characters (0/O, 1/l/I) since this gets typed by hand.
PASSWORD_ALPHABET = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")

DEFAULT_EXPIRY = timedelta(days=7)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def _generate_username() -> str:
    suffix = "".join(secrets.choice(USERNAME_ALPHABET) for _ in range(6))
    return f"cand-{suffix}"


def _generate_password() -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(10))


def generate_credentials(
    db: Session, application: Application, expiry: timedelta = DEFAULT_EXPIRY
) -> tuple[Credential, str]:
    """Creates or regenerates the application's temp login credentials.

    Returns the Credential row and the ONE-TIME plaintext password. Only
    temp_password_hash is ever persisted — the plaintext must be handed to the
    caller immediately (e.g. to put in an invite email) and never stored.
    Does not commit; the caller owns the transaction.
    """
    plaintext_password = _generate_password()

    credential = db.get(Credential, application.id)
    if credential is None:
        credential = Credential(application_id=application.id)
        db.add(credential)

    username = _generate_username()
    while (
        db.query(Credential)
        .filter(Credential.temp_username == username, Credential.application_id != application.id)
        .first()
        is not None
    ):
        username = _generate_username()

    credential.temp_username = username
    credential.temp_password_hash = hash_password(plaintext_password)
    credential.expires_at = datetime.now(timezone.utc) + expiry
    credential.login_status = "not_logged_in"

    return credential, plaintext_password
