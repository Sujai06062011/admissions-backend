import random
import uuid

from sqlalchemy.orm import Session

from app.models.stage3_test_a import Question, QuestionBank, TestBlueprint
from app.questions.validation import InvalidCorrectAnswer, resolve_correct_answer_text


class NoTestBlueprintConfigured(Exception):
    """No TestBlueprint rows exist for the application's program."""


class InsufficientQuestions(Exception):
    """A blueprint category doesn't have enough questions available."""


class MalformedQuestion(Exception):
    """A question's correct_answer doesn't resolve against its options."""


def _resolved_category_pool(
    db: Session, program_id: uuid.UUID, category: str
) -> list[tuple[Question, str]]:
    """Every question in a category that has a correct_answer set, each
    paired with its resolved correct answer text.

    A question with no correct_answer at all (still a valid, optional state —
    e.g. a draft not yet finished) is silently excluded here, same as before:
    it's just not eligible for selection, not an error. A question WITH a
    correct_answer that doesn't actually resolve against its options is a
    different case — that's malformed data, not an intentional gap, so it's
    validated up front across the WHOLE pool rather than only the questions
    that happen to get randomly selected (checking only sampled questions
    would make test-start success depend on random luck, which is a
    confusing thing for an admin to debug — "it worked yesterday").  Raises
    MalformedQuestion identifying the exact question (id + bank) on the
    first one that doesn't resolve, so it gets fixed instead of quietly
    shrinking the pool.
    """
    pool = (
        db.query(Question)
        .join(QuestionBank, Question.bank_id == QuestionBank.id)
        .filter(QuestionBank.program_id == program_id, Question.category == category)
        .all()
    )

    resolved = []
    for question in pool:
        if not (question.correct_answer or "").strip():
            continue

        try:
            correct_text = resolve_correct_answer_text(
                question.options or [], question.correct_answer
            )
        except InvalidCorrectAnswer as exc:
            raise MalformedQuestion(
                f"Question {question.id} in bank {question.bank_id} has an "
                f"invalid correct_answer: {exc}"
            ) from exc
        resolved.append((question, correct_text))

    return resolved


def build_generated_questions(
    db: Session, program_id: uuid.UUID
) -> tuple[list[dict], int]:
    """Builds a shuffled question snapshot for a Test A session.

    A program's Test A can span multiple TestBlueprint rows (one per
    category, e.g. quant + verbal as separate sections) — this combines all
    of them into a single session: total duration is the sum of every
    blueprint's duration_minutes, and the combined question set draws
    question_count questions from each blueprint's category, then shuffles
    the overall question order across categories.

    Returns (generated_questions, total_duration_minutes). Each entry in
    generated_questions is {question_id, question_text, options,
    correct_index} — options are shuffled per-question, and correct_index is
    computed fresh AFTER that shuffle (never reused from the question's
    original stored order/label), since the whole point of the snapshot is
    that grading later never has to trust anything that could have changed
    since generation.

    Raises NoTestBlueprintConfigured / InsufficientQuestions / MalformedQuestion;
    callers turn these into HTTP errors.
    """
    blueprints = db.query(TestBlueprint).filter(TestBlueprint.program_id == program_id).all()
    if not blueprints:
        raise NoTestBlueprintConfigured(f"No test blueprint configured for program {program_id}")

    generated_questions: list[dict] = []
    total_duration_minutes = 0

    for blueprint in blueprints:
        total_duration_minutes += blueprint.duration_minutes

        resolved_pool = _resolved_category_pool(db, program_id, blueprint.category)
        if len(resolved_pool) < blueprint.question_count:
            raise InsufficientQuestions(
                f"Category '{blueprint.category}' needs {blueprint.question_count} "
                f"questions but only {len(resolved_pool)} are available"
            )
        selected = random.sample(resolved_pool, blueprint.question_count)

        for question, correct_text in selected:
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
