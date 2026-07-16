import csv
import io
from dataclasses import dataclass
from typing import get_args

from app.questions.schemas import QuestionCategory

VALID_CATEGORIES = set(get_args(QuestionCategory))


@dataclass
class ParsedQuestion:
    category: str
    question_text: str
    options: list[str] | None
    correct_answer: str | None
    difficulty: str


@dataclass
class RowError:
    row: int
    reason: str


def parse_questions_csv(content: str) -> tuple[list[ParsedQuestion], list[RowError]]:
    """Parses a question-bank CSV into rows ready for Question creation.

    Required columns: category, question_text.
    Optional: correct_answer, difficulty (defaults to 'medium' if blank).
    Any column whose header starts with "option" (option_a, option_b, ...) is
    collected in header order — blank cells are skipped — to build the JSONB
    `options` list, so the number of options per question is not fixed.

    Rows with a missing/blank category or question_text, or a category outside
    QuestionCategory, are skipped and reported in the returned errors list rather
    than aborting the whole upload.
    """
    reader = csv.DictReader(io.StringIO(content))
    option_columns = [
        h for h in (reader.fieldnames or []) if h and h.strip().lower().startswith("option")
    ]

    questions: list[ParsedQuestion] = []
    errors: list[RowError] = []

    for row_number, row in enumerate(reader, start=2):  # header is row 1
        category = (row.get("category") or "").strip()
        question_text = (row.get("question_text") or "").strip()

        if not category:
            errors.append(RowError(row=row_number, reason="missing category"))
            continue
        if category not in VALID_CATEGORIES:
            errors.append(
                RowError(
                    row=row_number,
                    reason=f"invalid category '{category}', expected one of {sorted(VALID_CATEGORIES)}",
                )
            )
            continue
        if not question_text:
            errors.append(RowError(row=row_number, reason="missing question_text"))
            continue

        options = [row[col].strip() for col in option_columns if (row.get(col) or "").strip()]
        correct_answer = (row.get("correct_answer") or "").strip() or None
        difficulty = (row.get("difficulty") or "").strip() or "medium"

        questions.append(
            ParsedQuestion(
                category=category,
                question_text=question_text,
                options=options or None,
                correct_answer=correct_answer,
                difficulty=difficulty,
            )
        )

    return questions, errors
