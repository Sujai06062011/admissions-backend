import logging
import uuid
from pathlib import Path

from fastapi import BackgroundTasks

from app.applications.storage import download_document
from app.db.session import SessionLocal
from app.models.stage1 import UploadedDocument
from workers.claude_extraction import (
    extract_certifications_via_claude,
    extract_structured_fields_via_claude,
)
from workers.vision_ocr import PDF_CONTENT_TYPE, extract_text

logger = logging.getLogger(__name__)

_CLAUDE_EXTRACTED_DOC_TYPES = {
    "address_proof",
    "id_proof",
    "10th_marksheet",
    "12th_marksheet",
    "ug_marksheet",
    "pg_marksheet",
}

# Extension → Vision content-type. Vision's images:annotate auto-detects the
# actual codec from the bytes, so the value only needs to distinguish PDF
# (files:annotate) from "any image" — but mapping the common image extensions
# explicitly keeps logs/storage metadata accurate for JPEG/PNG/WebP uploads.
_CONTENT_TYPE_BY_SUFFIX = {
    ".pdf": PDF_CONTENT_TYPE,
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _parse_fields(raw_text: str, doc_type: str) -> dict:
    """Routes to the right field extractor for a document's doc_type.

    Marksheets, address proofs, and ID proofs all vary too much in layout
    (a CBSE 10th marksheet vs. a university degree certificate; a utility
    bill vs. an Aadhaar card) for a regex parser to handle reliably, so all
    of those go through Claude. Certifications can list an arbitrary number
    of credentials on one page, so those get their own Claude
    list-extraction. Everything else (resume, experience_certificate) has no
    structured fields to extract — only the raw OCR text is kept.
    """
    if doc_type in _CLAUDE_EXTRACTED_DOC_TYPES:
        return extract_structured_fields_via_claude(raw_text, doc_type)
    if doc_type == "certifications":
        return extract_certifications_via_claude(raw_text)
    return {}


def _guess_content_type(file_url: str) -> str:
    """Picks the Vision content-type from the stored object path's suffix.

    PDFs must go to files:annotate; every other known image type goes to
    images:annotate. Unknown suffixes default to image/jpeg so a photo
    upload without a recognized extension still gets OCR'd rather than
    rejected — Vision auto-detects the codec from the bytes either way.
    """
    suffix = Path(file_url).suffix.lower()
    return _CONTENT_TYPE_BY_SUFFIX.get(suffix, "image/jpeg")


def _mark_ocr_failed(document: UploadedDocument, reason: str) -> None:
    """Writes an explicit failure marker so the candidate ProcessingStep
    stops polling forever. A non-null ocr_result counts as "done" on the
    frontend; empty parsed fields then surface as "Enter manually" on the
    Review screen — better than an infinite spinner.
    """
    document.ocr_result = {
        "raw_text": "",
        "parsed": {},
        "confidence": 0.0,
        "error": reason,
    }
    document.ocr_confidence = 0.0


def process_document_ocr(document_id: str) -> None:
    """Runs real OCR (Google Cloud Vision) on an uploaded document and stores
    the raw extracted text plus parsed structured fields on the row.

    Opens its own DB session — this runs as a background task after the
    request that triggered it has already returned, so it can't reuse that
    request's session. Never raises: a failed OCR run has no one left to
    report to (the upload request already completed), so failures are logged
    and recorded as an explicit ocr_result error marker rather than left
    null forever (which used to hang the candidate ProcessingStep spinner).
    """
    db = SessionLocal()
    try:
        document = db.get(UploadedDocument, uuid.UUID(document_id))
        if document is None:
            logger.error("OCR job: document %s not found", document_id)
            return

        try:
            file_bytes = download_document(document.file_url)
            content_type = _guess_content_type(document.file_url)
            raw_text, confidence = extract_text(file_bytes, content_type)
        except Exception as exc:
            logger.exception("OCR job failed for document %s", document_id)
            _mark_ocr_failed(document, f"ocr_failed: {type(exc).__name__}")
            db.commit()
            return

        parsed = _parse_fields(raw_text, document.doc_type)

        document.ocr_result = {
            "raw_text": raw_text,
            "parsed": parsed,
            "confidence": confidence,
        }
        document.ocr_confidence = confidence
        db.commit()
        logger.info(
            "OCR job complete for document %s (confidence=%.2f)", document_id, confidence
        )
    finally:
        db.close()


def enqueue_ocr_job(background_tasks: BackgroundTasks, document_id: str) -> None:
    """Schedules the OCR job.

    Routed through FastAPI's BackgroundTasks for now; swap this function's body
    for a real queue (Celery/RQ) without touching callers when that's wired up.
    """
    background_tasks.add_task(process_document_ocr, document_id)
