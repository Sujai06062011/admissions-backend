import base64
import os

import httpx

IMAGES_ANNOTATE_URL = "https://vision.googleapis.com/v1/images:annotate"
FILES_ANNOTATE_URL = "https://vision.googleapis.com/v1/files:annotate"

PDF_CONTENT_TYPE = "application/pdf"


def extract_text(file_bytes: bytes, content_type: str) -> tuple[str, float]:
    """Runs Google Cloud Vision OCR (DOCUMENT_TEXT_DETECTION, tuned for dense
    printed documents over sparse-text photos) on an uploaded file.

    PDFs go through the files:annotate endpoint (only the first page — most
    marksheets are single-page); anything else is sent to images:annotate,
    which auto-detects the actual image format from the bytes regardless of
    the declared content_type.

    Returns (raw_text, confidence): confidence is the average per-word
    detection confidence Vision itself reports across the whole document —
    not something invented locally — or 0.0 if no text was detected at all.
    Raises on a genuine API/network failure; callers decide how to handle
    that (this module makes no decision about what an OCR failure means for
    the caller's data).
    """
    api_key = os.environ["GOOGLE_VISION_API_KEY"]
    encoded = base64.b64encode(file_bytes).decode("ascii")
    feature = {"type": "DOCUMENT_TEXT_DETECTION"}

    if content_type == PDF_CONTENT_TYPE:
        payload = {
            "requests": [
                {
                    "inputConfig": {"content": encoded, "mimeType": PDF_CONTENT_TYPE},
                    "features": [feature],
                    "pages": [1],
                }
            ]
        }
        url = FILES_ANNOTATE_URL
    else:
        payload = {"requests": [{"image": {"content": encoded}, "features": [feature]}]}
        url = IMAGES_ANNOTATE_URL

    response = httpx.post(url, params={"key": api_key}, json=payload, timeout=30.0)
    response.raise_for_status()
    data = response.json()

    result = data["responses"][0]
    if content_type == PDF_CONTENT_TYPE:
        # files:annotate wraps each requested page's own response one level deeper.
        page_responses = result.get("responses", [])
        result = page_responses[0] if page_responses else {}

    if "error" in result:
        raise RuntimeError(f"Vision API error: {result['error']}")

    full_text_annotation = result.get("fullTextAnnotation")
    if not full_text_annotation:
        return "", 0.0

    raw_text = full_text_annotation.get("text", "")

    confidences = [
        word["confidence"]
        for page in full_text_annotation.get("pages", [])
        for block in page.get("blocks", [])
        for paragraph in block.get("paragraphs", [])
        for word in paragraph.get("words", [])
        if "confidence" in word
    ]
    confidence = sum(confidences) / len(confidences) if confidences else 0.0

    return raw_text, confidence
