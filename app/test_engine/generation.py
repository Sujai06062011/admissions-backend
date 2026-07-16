import random
import uuid

from sqlalchemy.orm import Session

from app.models.stage3_test_a import Question, QuestionBank, TestBlueprint


class NoTestBlueprintConfigured(Exception):
    """No TestBlueprint rows exist for the application's program."""


class InsufficientQuestions(Exception):
    """A blueprint category doesn't have enough gradeable questions available."""


def _resolve_correct_text(question: Question) -> str | None:
    """Resolves a question's correct_answer into the actual option text.

    There's no enforced contract on what correct_answer holds — the
    single-question-create endpoint accepts any freeform string, and the CSV
    bulk-upload path has been used with single-letter labels (A/B/C/D as a
    1-indexed position). Both are handled: an exact match against the option
    text wins first, falling back to treating a single letter as a position.
    Returns None if neither resolves — such a question is unresolvable and
    must not be served to a candidate (see _gradeable_pool below).
    """
    options = question.options or []
    correct_answer = (question.correct_answer or "").strip()
    if not correct_answer:
        return None
    if correct_answer in options:
        return correct_answer
    if len(correct_answer) == 1 and correct_answer.isalpha():
        index = ord(correct_answer.upper()) - ord("A")
        if 0 <= index < len(options):
            return options[index]
    return None


def _gradeable_pool(db: Session, program_id: uuid.UUID, category: str) -> list[Question]:
    """All questions in a category whose correct_answer actually resolves to
    one of their options. Ungradeable questions (malformed correct_answer,
    missing options) are excluded from selection entirely rather than served
    to a candidate and silently scored wrong no matter what they pick.
    """
    pool = (
        db.query(Question)
        .join(QuestionBank, Question.bank_id == QuestionBank.id)
        .filter(QuestionBank.program_id == program_id, Question.category == category)
        .all()
    )
    return [q for q in pool if _resolve_correct_text(q) is not None]


def build_generated_questions(
    db: Session, program_id: uuid.UUID
) -> tuple[list[dict], int]:
    """Builds a shuffled question snapshot for a Test A session.

    A program's Test A can span multiple TestBlueprint rows (one per
    category, e.g. quant + verbal as separate sections) — this combines all
    of them into a single session: total duration is the sum of every
    blueprint's duration_minutes, and the combined question set draws
    question_count gradeable questions from each blueprint's category, then
    shuffles the overall question order across categories.

    Returns (generated_questions, total_duration_minutes). Each entry in
    generated_questions is {question_id, question_text, options,
    correct_index} — options are shuffled per-question, and correct_index is
    computed fresh AFTER that shuffle (never reused from the question's
    original stored order/label), since the whole point of the snapshot is
    that grading later never has to trust anything that could have changed
    since generation.

    Raises NoTestBlueprintConfigured / InsufficientQuestions; callers turn
    these into HTTP errors.
    """
    blueprints = db.query(TestBlueprint).filter(TestBlueprint.program_id == program_id).all()
    if not blueprints:
        raise NoTestBlueprintConfigured(f"No test blueprint configured for program {program_id}")

    generated_questions: list[dict] = []
    total_duration_minutes = 0

    for blueprint in blueprints:
        total_duration_minutes += blueprint.duration_minutes

        pool = _gradeable_pool(db, program_id, blueprint.category)
        if len(pool) < blueprint.question_count:
            raise InsufficientQuestions(
                f"Category '{blueprint.category}' needs {blueprint.question_count} "
                f"gradeable questions but only {len(pool)} are available"
            )
        selected = random.sample(pool, blueprint.question_count)

        for question in selected:
            correct_text = _resolve_correct_text(question)
            shuffled_options = list(question.options or [])
            random.shuffle(shuffled_options)
            correct_index = shuffled_options.index(correct_text)

            generated_questions.append(
                {
                    "question_id": str(question.id),
                    "question_text": question.question_text,
                    "options": shuffled_options,
                    "correct_index": correct_index,
                }
            )

    random.shuffle(generated_questions)
    return generated_questions, total_duration_minutes
