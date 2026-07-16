import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.core import Program
from app.models.stage3_test_a import Question, QuestionBank, TestBlueprint
from app.questions.csv_import import parse_questions_csv
from app.questions.schemas import (
    BulkUploadError,
    BulkUploadResult,
    QuestionBankCreate,
    QuestionBankResponse,
    QuestionBankUpdate,
    QuestionCategory,
    QuestionCreate,
    QuestionResponse,
    QuestionUpdate,
    TestBlueprintCreate,
    TestBlueprintResponse,
    TestBlueprintUpdate,
)
from app.questions.validation import InvalidCorrectAnswer, resolve_correct_answer_text

router = APIRouter(tags=["questions"])


# --- Question Bank CRUD ---


@router.post(
    "/programs/{program_id}/question-banks", response_model=QuestionBankResponse, status_code=201
)
def create_question_bank(
    program_id: uuid.UUID, payload: QuestionBankCreate, db: Session = Depends(get_db)
) -> QuestionBank:
    if db.get(Program, program_id) is None:
        raise HTTPException(status_code=404, detail="Program not found")

    bank = QuestionBank(program_id=program_id, **payload.model_dump())
    db.add(bank)
    db.commit()
    db.refresh(bank)
    return bank


@router.get("/programs/{program_id}/question-banks", response_model=list[QuestionBankResponse])
def list_question_banks(program_id: uuid.UUID, db: Session = Depends(get_db)) -> list[QuestionBank]:
    if db.get(Program, program_id) is None:
        raise HTTPException(status_code=404, detail="Program not found")

    return db.query(QuestionBank).filter(QuestionBank.program_id == program_id).all()


@router.get("/question-banks/{bank_id}", response_model=QuestionBankResponse)
def get_question_bank(bank_id: uuid.UUID, db: Session = Depends(get_db)) -> QuestionBank:
    bank = db.get(QuestionBank, bank_id)
    if bank is None:
        raise HTTPException(status_code=404, detail="Question bank not found")
    return bank


@router.patch("/question-banks/{bank_id}", response_model=QuestionBankResponse)
def update_question_bank(
    bank_id: uuid.UUID, payload: QuestionBankUpdate, db: Session = Depends(get_db)
) -> QuestionBank:
    bank = db.get(QuestionBank, bank_id)
    if bank is None:
        raise HTTPException(status_code=404, detail="Question bank not found")

    bank.name = payload.name
    db.commit()
    db.refresh(bank)
    return bank


@router.delete("/question-banks/{bank_id}", status_code=204)
def delete_question_bank(bank_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    bank = db.get(QuestionBank, bank_id)
    if bank is None:
        raise HTTPException(status_code=404, detail="Question bank not found")

    # The questions relationship has no cascade="delete" configured, so a plain
    # session.delete(bank) would try to null out each child's NOT NULL bank_id
    # instead of deleting them. Delete the children directly first.
    db.query(Question).filter(Question.bank_id == bank_id).delete(synchronize_session=False)
    db.delete(bank)
    db.commit()


# --- Question CRUD ---


@router.post(
    "/question-banks/{bank_id}/questions", response_model=QuestionResponse, status_code=201
)
def create_question(
    bank_id: uuid.UUID, payload: QuestionCreate, db: Session = Depends(get_db)
) -> Question:
    if db.get(QuestionBank, bank_id) is None:
        raise HTTPException(status_code=404, detail="Question bank not found")

    # correct_answer is optional (a question can be created without one), but
    # if it's given, it must actually resolve — reject here rather than let a
    # bad value silently shrink Test A's selection pool later.
    if payload.correct_answer is not None:
        try:
            resolve_correct_answer_text(payload.options or [], payload.correct_answer)
        except InvalidCorrectAnswer as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    question = Question(bank_id=bank_id, **payload.model_dump())
    db.add(question)
    db.commit()
    db.refresh(question)
    return question


@router.get("/question-banks/{bank_id}/questions", response_model=list[QuestionResponse])
def list_questions(
    bank_id: uuid.UUID,
    db: Session = Depends(get_db),
    category: QuestionCategory | None = Query(None),
) -> list[Question]:
    if db.get(QuestionBank, bank_id) is None:
        raise HTTPException(status_code=404, detail="Question bank not found")

    query = db.query(Question).filter(Question.bank_id == bank_id)
    if category is not None:
        query = query.filter(Question.category == category)
    return query.order_by(Question.created_at).all()


@router.get("/questions/{question_id}", response_model=QuestionResponse)
def get_question(question_id: uuid.UUID, db: Session = Depends(get_db)) -> Question:
    question = db.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    return question


@router.patch("/questions/{question_id}", response_model=QuestionResponse)
def update_question(
    question_id: uuid.UUID, payload: QuestionUpdate, db: Session = Depends(get_db)
) -> Question:
    question = db.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(question, field_name, value)
    db.commit()
    db.refresh(question)
    return question


@router.delete("/questions/{question_id}", status_code=204)
def delete_question(question_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    question = db.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    db.delete(question)
    db.commit()


# --- Bulk CSV upload ---


@router.post(
    "/question-banks/{bank_id}/questions/bulk-upload",
    response_model=BulkUploadResult,
    status_code=201,
)
def bulk_upload_questions(
    bank_id: uuid.UUID, file: UploadFile = File(...), db: Session = Depends(get_db)
) -> BulkUploadResult:
    if db.get(QuestionBank, bank_id) is None:
        raise HTTPException(status_code=404, detail="Question bank not found")

    raw = file.file.read()
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="CSV file must be UTF-8 encoded")

    parsed, row_errors = parse_questions_csv(content)

    questions = [
        Question(
            bank_id=bank_id,
            category=p.category,
            question_text=p.question_text,
            options=p.options,
            correct_answer=p.correct_answer,
            difficulty=p.difficulty,
        )
        for p in parsed
    ]
    db.add_all(questions)
    db.commit()
    for question in questions:
        db.refresh(question)

    return BulkUploadResult(
        created_count=len(questions),
        questions=[QuestionResponse.model_validate(q) for q in questions],
        errors=[BulkUploadError(row=e.row, reason=e.reason) for e in row_errors],
    )


# --- Test Blueprint CRUD ---


@router.post(
    "/programs/{program_id}/test-blueprints", response_model=TestBlueprintResponse, status_code=201
)
def create_test_blueprint(
    program_id: uuid.UUID, payload: TestBlueprintCreate, db: Session = Depends(get_db)
) -> TestBlueprint:
    if db.get(Program, program_id) is None:
        raise HTTPException(status_code=404, detail="Program not found")

    blueprint = TestBlueprint(program_id=program_id, **payload.model_dump())
    db.add(blueprint)
    db.commit()
    db.refresh(blueprint)
    return blueprint


@router.get("/programs/{program_id}/test-blueprints", response_model=list[TestBlueprintResponse])
def list_test_blueprints(
    program_id: uuid.UUID, db: Session = Depends(get_db)
) -> list[TestBlueprint]:
    if db.get(Program, program_id) is None:
        raise HTTPException(status_code=404, detail="Program not found")

    return db.query(TestBlueprint).filter(TestBlueprint.program_id == program_id).all()


@router.get("/test-blueprints/{blueprint_id}", response_model=TestBlueprintResponse)
def get_test_blueprint(blueprint_id: uuid.UUID, db: Session = Depends(get_db)) -> TestBlueprint:
    blueprint = db.get(TestBlueprint, blueprint_id)
    if blueprint is None:
        raise HTTPException(status_code=404, detail="Test blueprint not found")
    return blueprint


@router.patch("/test-blueprints/{blueprint_id}", response_model=TestBlueprintResponse)
def update_test_blueprint(
    blueprint_id: uuid.UUID, payload: TestBlueprintUpdate, db: Session = Depends(get_db)
) -> TestBlueprint:
    blueprint = db.get(TestBlueprint, blueprint_id)
    if blueprint is None:
        raise HTTPException(status_code=404, detail="Test blueprint not found")

    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(blueprint, field_name, value)
    db.commit()
    db.refresh(blueprint)
    return blueprint


@router.delete("/test-blueprints/{blueprint_id}", status_code=204)
def delete_test_blueprint(blueprint_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    blueprint = db.get(TestBlueprint, blueprint_id)
    if blueprint is None:
        raise HTTPException(status_code=404, detail="Test blueprint not found")

    db.delete(blueprint)
    db.commit()
