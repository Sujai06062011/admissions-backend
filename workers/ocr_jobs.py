import logging

from fastapi import BackgroundTasks

logger = logging.getLogger(__name__)


def process_document_ocr(document_id: str) -> None:
    """Placeholder OCR job.

    Eventually: load the UploadedDocument, run it through an OCR provider,
    and write ocr_result/ocr_confidence back to the row. Not implemented yet.
    """
    logger.info("OCR job stub invoked for uploaded_document_id=%s", document_id)


def enqueue_ocr_job(background_tasks: BackgroundTasks, document_id: str) -> None:
    """Schedules the OCR job.

    Routed through FastAPI's BackgroundTasks for now; swap this function's body
    for a real queue (Celery/RQ) without touching callers when that's wired up.
    """
    background_tasks.add_task(process_document_ocr, document_id)
