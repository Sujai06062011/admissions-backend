import logging
import uuid

from fastapi import BackgroundTasks

from app.applications.storage import download_document
from app.db.session import SessionLocal
from app.models.stage1 import UploadedDocument
from workers.claude_extraction import extract_structured_fields_via_claude
from workers.ocr_parsing import parse_marksheet_fields
from workers.vision_ocr import PDF_CONTENT_TYPE, extract_text

logger = logging.getLogger(__name__)

_MARKSHEET_DOC_TYPES = {"10th_marksheet", "12th_marksheet", "ug_marksheet", "pg_marksheet"}
_CLAUDE_EXTRACTED_DOC_TYPES = {"address_proof", "id_proof"}


def _parse_fields(raw_text: str, doc_type: str, confidence: float) -> dict:
    """Routes to the right field extractor for a document's doc_type.

    Marksheets have a predictable label/value layout, so a cheap regex parser
    works. Address/ID proofs vary too much in format (utility bill vs.
    Aadhaar vs. passport) for regex, so those go through Claude instead.
    Everything else (resume, certifications, experience_certificate) has no
    structured fields to extract — only the raw OCR text is kept.
    """
    if doc_type in _MARKSHEET_DOC_TYPES:
        return parse_marksheet_fields(raw_text, doc_type, confidence)
    if doc_type in _CLAUDE_EXTRACTED_DOC_TYPES:
        return extract_structured_fields_via_claude(raw_text, doc_type)
    return {}


def _guess_content_type(file_url: str) -> str:
    """Vision's images:annotate endpoint auto-detects the actual image codec
    from the bytes regardless of what's passed here — the only thing that
    actually matters is routing PDFs to the separate files:annotate endpoint,
    so this only needs to distinguish "PDF" from "everything else."
    """
    return PDF_CONTENT_TYPE if file_url.lower().endswith(".pdf") else "image/jpeg"


def process_document_ocr(document_id: str) -> None:
    """Runs real OCR (Google Cloud Vision) on an uploaded document and stores
    the raw extracted text plus parsed structured fields on the row.

    Opens its own DB session — this runs as a background task after the
    request that triggered it has already returned, so it can't reuse that
    request's session. Never raises: a failed OCR run has no one left to
    report to (the upload request already completed), so failures are logged
    instead of propagated, and the row is simply left without ocr_result
    rather than left in a partially-written state.
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
        except Exception:
            logger.exception("OCR job failed for document %s", document_id)
            return

        parsed = _parse_fields(raw_text, document.doc_type, confidence)

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
