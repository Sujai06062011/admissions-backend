import re

_LETTERS_RE = re.compile(r"[^a-zA-Z]")
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def build_application_number(full_name: str | None, dob: str | None, sequence_number: int) -> str:
    """Builds a human-readable reference like SUJA-170399-0013.

    Deliberately padded/placeholder ("X"s) rather than raising when name or
    dob is missing or unparseable, since the number is a display convenience
    and must never block application creation.
    """
    letters = _LETTERS_RE.sub("", full_name or "").upper()
    name_part = letters[:4].ljust(4, "X")

    dob_part = "XXXXXX"
    match = _ISO_DATE_RE.match(dob or "")
    if match:
        year, month, day = match.groups()
        dob_part = f"{day}{month}{year[2:]}"

    sequence_part = str(sequence_number).zfill(4)
    return f"{name_part}-{dob_part}-{sequence_part}"
