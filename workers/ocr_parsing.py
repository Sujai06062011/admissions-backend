import re
from datetime import datetime, timezone

# A labeled "percentage: 85.5" wins over a bare "85.5%" when both are present,
# since a bare percent sign could belong to an individual subject mark rather
# than the overall result.
PERCENTAGE_LABELED_RE = re.compile(r"percentage[:\s]+(\d{1,3}(?:\.\d{1,2})?)", re.IGNORECASE)
PERCENTAGE_RE = re.compile(r"(\d{1,3}(?:\.\d{1,2})?)\s*%")
CGPA_RE = re.compile(r"cgpa[:\s]+(\d{1,2}(?:\.\d{1,2})?)", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")

BOARD_KEYWORDS = ["board of", "cbse", "icse", "state board"]
UNIVERSITY_KEYWORDS = ["university"]
BOARD_DOC_TYPES = {"10th_marksheet", "12th_marksheet"}

# Below this, Vision's own text-detection confidence is low enough (typical
# of handwriting or a poor-quality scan) that trusting a regex match against
# the extracted text risks trusting garbled characters — a percentage that
# looks plausible but is actually wrong is worse than an empty field an
# admin knows to check manually.
MIN_CONFIDENCE_TO_TRUST_FIELDS = 0.5


def parse_marksheet_fields(raw_text: str, doc_type: str, ocr_confidence: float) -> dict:
    """Extracts board/university name, percentage, CGPA, and year from OCR'd
    marksheet text.

    Deliberately returns None for a field rather than a best-guess value
    whenever OCR confidence is too low, or nothing in the text clearly
    matches — this is a heuristic regex parser over noisy OCR output, not a
    real document-understanding model, so it should fail toward "unknown"
    rather than toward "plausible but wrong."
    """
    fields = {"board_or_university": None, "percentage": None, "cgpa": None, "year": None}

    if not raw_text or ocr_confidence < MIN_CONFIDENCE_TO_TRUST_FIELDS:
        return fields

    keywords = BOARD_KEYWORDS if doc_type in BOARD_DOC_TYPES else UNIVERSITY_KEYWORDS
    for line in raw_text.splitlines():
        line = line.strip()
        if line and any(keyword in line.lower() for keyword in keywords):
            fields["board_or_university"] = line
            break

    percentage_match = PERCENTAGE_LABELED_RE.search(raw_text) or PERCENTAGE_RE.search(raw_text)
    if percentage_match:
        value = float(percentage_match.group(1))
        if 0 <= value <= 100:
            fields["percentage"] = value

    cgpa_match = CGPA_RE.search(raw_text)
    if cgpa_match:
        value = float(cgpa_match.group(1))
        if 0 <= value <= 10:
            fields["cgpa"] = value

    current_year = datetime.now(timezone.utc).year
    valid_years = [
        year
        for year in (int(match) for match in YEAR_RE.findall(raw_text))
        if 1950 <= year <= current_year + 1
    ]
    if valid_years:
        fields["year"] = max(valid_years)

    return fields
