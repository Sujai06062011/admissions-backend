import base64
import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

IMAGES_ANNOTATE_URL = "https://vision.googleapis.com/v1/images:annotate"
FILES_ANNOTATE_URL = "https://vision.googleapis.com/v1/files:annotate"

PDF_CONTENT_TYPE = "application/pdf"

# files:annotate allows at most 5 pages per request. Requesting all 5 up
# front (rather than first detecting the page count) covers every document
# type this app handles (marksheets, ID/address proofs, certificates) in a
# single call; page numbers beyond the document's actual length just come
# back as per-page errors below, which are skipped rather than treated as
# a failure of the whole request.
MAX_PDF_PAGES = 5

# Vision can take longer on multi-page PDFs than single images; a hard 30s
# cutoff was the root cause of "stuck forever" OCR jobs when a larger
# marksheet PDF just needed a bit more time.
IMAGE_TIMEOUT_SECONDS = 30.0
PDF_TIMEOUT_SECONDS = 60.0

# Transient network / 5xx / timeout failures get a couple of retries before
# we give up — permanent 4xx responses are not retried.
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (1.5, 3.0)


def extract_text(file_bytes: bytes, content_type: str) -> tuple[str, float]:
    """Runs Google Cloud Vision OCR (DOCUMENT_TEXT_DETECTION, tuned for dense
    printed documents over sparse-text photos) on an uploaded file.

    PDFs go through the files:annotate endpoint across up to MAX_PDF_PAGES
    pages (a two-sided ID scan is a common case — the address on the back of
    an Aadhaar card is useless if only page 1 gets read); anything else is
    sent to images:annotate, which auto-detects the actual image format from
    the bytes regardless of the declared content_type.

    Returns (raw_text, confidence): raw_text is every page's text
    concatenated in order; confidence is the average per-word detection
    confidence Vision itself reports across all pages combined — not
    something invented locally — or 0.0 if no text was detected at all.
    Raises on a genuine API/network failure after retries are exhausted;
    callers decide how to handle that (this module makes no decision about
    what an OCR failure means for the caller's data).
    """
    api_key = os.environ["GOOGLE_VISION_API_KEY"]
    encoded = base64.b64encode(file_bytes).decode("ascii")
    feature = {"type": "DOCUMENT_TEXT_DETECTION"}
    is_pdf = content_type == PDF_CONTENT_TYPE

    if is_pdf:
        payload = {
            "requests": [
                {
                    "inputConfig": {"content": encoded, "mimeType": PDF_CONTENT_TYPE},
                    "features": [feature],
                    "pages": list(range(1, MAX_PDF_PAGES + 1)),
                }
            ]
        }
        url = FILES_ANNOTATE_URL
        timeout = PDF_TIMEOUT_SECONDS
    else:
        payload = {"requests": [{"image": {"content": encoded}, "features": [feature]}]}
        url = IMAGES_ANNOTATE_URL
        timeout = IMAGE_TIMEOUT_SECONDS

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = httpx.post(url, params={"key": api_key}, json=payload, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            return _parse_vision_response(data, is_pdf)
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
            # Don't retry client errors (bad request / auth) — only transient
            # network, timeout, and 5xx responses.
            if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
                if 400 <= exc.response.status_code < 500:
                    raise
            last_error = exc
            if attempt >= MAX_ATTEMPTS:
                break
            backoff = RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
            logger.warning(
                "Vision OCR attempt %s/%s failed (%s); retrying in %.1fs",
                attempt,
                MAX_ATTEMPTS,
                exc,
                backoff,
            )
            time.sleep(backoff)

    assert last_error is not None
    raise last_error


def _parse_vision_response(data: dict, is_pdf: bool) -> tuple[str, float]:
    result = data["responses"][0]

    if not is_pdf:
        if "error" in result:
            raise RuntimeError(f"Vision API error: {result['error']}")
        return _text_and_confidence([result])

    # files:annotate wraps each requested page's own response one level
    # deeper. A page number beyond the document's actual length comes back
    # as its own per-page error (not a top-level one) — those are skipped,
    # since "page 4 doesn't exist" on a 2-page PDF isn't a real failure.
    page_responses = result.get("responses", [])
    if not page_responses and "error" in result:
        raise RuntimeError(f"Vision API error: {result['error']}")

    valid_pages = [page for page in page_responses if "error" not in page]
    return _text_and_confidence(valid_pages)


def _text_and_confidence(page_results: list[dict]) -> tuple[str, float]:
    texts = []
    confidences = []

    for result in page_results:
        full_text_annotation = result.get("fullTextAnnotation")
        if not full_text_annotation:
            continue

        texts.append(full_text_annotation.get("text", ""))
        confidences.extend(
            word["confidence"]
            for page in full_text_annotation.get("pages", [])
            for block in page.get("blocks", [])
            for paragraph in block.get("paragraphs", [])
            for word in paragraph.get("words", [])
            if "confidence" in word
        )

    raw_text = "\n\n".join(texts)
    confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return raw_text, confidence
