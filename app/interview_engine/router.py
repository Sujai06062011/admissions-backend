import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.interview_engine.schemas import (
    PromptBankCreate,
    PromptBankResponse,
    PromptBankUpdate,
    PromptCreate,
    PromptResponse,
    PromptUpdate,
)
from app.interview_engine.storage import save_recording
from app.models.core import Program
from app.models.scheduling import CampusSession
from app.models.stage1 import Application
from app.models.stage3_test_b import Prompt, PromptBank, TestBSession
from app.schemas.stage3 import PromptType, TestBSessionResponse
from workers.interview_scoring import enqueue_interview_scoring

router = APIRouter(tags=["interview_engine"])


# --- PromptBank CRUD ---


@router.post(
    "/programs/{program_id}/prompt-banks", response_model=PromptBankResponse, status_code=201
)
def create_prompt_bank(
    program_id: uuid.UUID, payload: PromptBankCreate, db: Session = Depends(get_db)
) -> PromptBank:
    if db.get(Program, program_id) is None:
        raise HTTPException(status_code=404, detail="Program not found")

    bank = PromptBank(program_id=program_id, **payload.model_dump())
    db.add(bank)
    db.commit()
    db.refresh(bank)
    return bank


@router.get("/programs/{program_id}/prompt-banks", response_model=list[PromptBankResponse])
def list_prompt_banks(program_id: uuid.UUID, db: Session = Depends(get_db)) -> list[PromptBank]:
    if db.get(Program, program_id) is None:
        raise HTTPException(status_code=404, detail="Program not found")

    return db.query(PromptBank).filter(PromptBank.program_id == program_id).all()


@router.get("/prompt-banks/{bank_id}", response_model=PromptBankResponse)
def get_prompt_bank(bank_id: uuid.UUID, db: Session = Depends(get_db)) -> PromptBank:
    bank = db.get(PromptBank, bank_id)
    if bank is None:
        raise HTTPException(status_code=404, detail="Prompt bank not found")
    return bank


@router.patch("/prompt-banks/{bank_id}", response_model=PromptBankResponse)
def update_prompt_bank(
    bank_id: uuid.UUID, payload: PromptBankUpdate, db: Session = Depends(get_db)
) -> PromptBank:
    bank = db.get(PromptBank, bank_id)
    if bank is None:
        raise HTTPException(status_code=404, detail="Prompt bank not found")

    bank.name = payload.name
    db.commit()
    db.refresh(bank)
    return bank


@router.delete("/prompt-banks/{bank_id}", status_code=204)
def delete_prompt_bank(bank_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    bank = db.get(PromptBank, bank_id)
    if bank is None:
        raise HTTPException(status_code=404, detail="Prompt bank not found")

    # prompts relationship has no cascade="delete" configured, so a plain
    # session.delete(bank) would try to null out each prompt's NOT NULL
    # bank_id instead of deleting them. Delete the children directly first.
    db.query(Prompt).filter(Prompt.bank_id == bank_id).delete(synchronize_session=False)
    db.delete(bank)
    db.commit()


# --- Prompt CRUD ---


@router.post("/prompt-banks/{bank_id}/prompts", response_model=PromptResponse, status_code=201)
def create_prompt(
    bank_id: uuid.UUID, payload: PromptCreate, db: Session = Depends(get_db)
) -> Prompt:
    if db.get(PromptBank, bank_id) is None:
        raise HTTPException(status_code=404, detail="Prompt bank not found")

    prompt = Prompt(bank_id=bank_id, **payload.model_dump())
    db.add(prompt)
    db.commit()
    db.refresh(prompt)
    return prompt


@router.get("/prompt-banks/{bank_id}/prompts", response_model=list[PromptResponse])
def list_prompts(
    bank_id: uuid.UUID,
    db: Session = Depends(get_db),
    prompt_type: PromptType | None = None,
) -> list[Prompt]:
    if db.get(PromptBank, bank_id) is None:
        raise HTTPException(status_code=404, detail="Prompt bank not found")

    query = db.query(Prompt).filter(Prompt.bank_id == bank_id)
    if prompt_type is not None:
        query = query.filter(Prompt.prompt_type == prompt_type)
    return query.order_by(Prompt.created_at).all()


@router.get("/prompts/{prompt_id}", response_model=PromptResponse)
def get_prompt(prompt_id: uuid.UUID, db: Session = Depends(get_db)) -> Prompt:
    prompt = db.get(Prompt, prompt_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return prompt


@router.patch("/prompts/{prompt_id}", response_model=PromptResponse)
def update_prompt(
    prompt_id: uuid.UUID, payload: PromptUpdate, db: Session = Depends(get_db)
) -> Prompt:
    prompt = db.get(Prompt, prompt_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail="Prompt not found")

    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(prompt, field_name, value)
    db.commit()
    db.refresh(prompt)
    return prompt


@router.delete("/prompts/{prompt_id}", status_code=204)
def delete_prompt(prompt_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    prompt = db.get(Prompt, prompt_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail="Prompt not found")

    # test_b_sessions.prompt_id is nullable with no cascade configured on the
    # relationship, so session.delete(prompt) would silently null it out on any
    # referencing TestBSession rather than raising — there's no NOT NULL or FK
    # violation to catch here, unlike the bank/schedule delete cases. Check
    # explicitly instead of relying on a DB-level error that will never come.
    referenced = db.query(TestBSession).filter(TestBSession.prompt_id == prompt_id).first()
    if referenced is not None:
        raise HTTPException(
            status_code=409,
            detail="Prompt is referenced by an existing test session and cannot be deleted",
        )

    db.delete(prompt)
    db.commit()


# --- Recording submission ---


@router.post(
    "/applications/{application_id}/test-b-recording",
    response_model=TestBSessionResponse,
    status_code=201,
)
def submit_recording(
    application_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    prompt_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> TestBSession:
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    if db.get(CampusSession, application_id) is None:
        raise HTTPException(
            status_code=404,
            detail="Application has no assigned campus session — cannot record interview response",
        )

    prompt = db.get(Prompt, prompt_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail="Prompt not found")
    if prompt.bank.program_id != application.program_id:
        raise HTTPException(
            status_code=400, detail="Prompt does not belong to the application's program"
        )

    recording_url = save_recording(application_id, file)

    session = db.get(TestBSession, application_id)
    if session is None:
        session = TestBSession(application_id=application_id)
        db.add(session)

    session.prompt = prompt
    session.recording_url = recording_url
    session.recorded_at = datetime.now(timezone.utc)
    # Clear any prior scoring immediately on re-submission so a stale
    # transcript/score from a previous recording is never visible against
    # this new one while the background job is still running.
    session.transcript = None
    session.rubric_score = None
    session.rationale = None

    db.commit()
    db.refresh(session)

    enqueue_interview_scoring(background_tasks, str(application_id))

    return session
