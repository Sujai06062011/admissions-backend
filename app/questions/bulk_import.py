import csv
import io
from dataclasses import dataclass
from typing import get_args

import openpyxl

from app.questions.schemas import QuestionCategory
from app.questions.validation import InvalidCorrectAnswer, resolve_correct_answer_text

VALID_CATEGORIES = set(get_args(QuestionCategory))

# Lets admin-authored spreadsheets use natural column names ("Question",
# "Correct Answer") instead of forcing them to match the DB field names
# exactly. Applied after header normalization (lowercased, spaces -> "_").
_HEADER_ALIASES = {
    "question": "question_text",
    "answer": "correct_answer",
}


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


def _normalize_header(header: str) -> str:
    normalized = header.strip().lower().replace(" ", "_")
    return _HEADER_ALIASES.get(normalized, normalized)


def _cell_str(value: object) -> str:
    """Stringifies an Excel cell value. Whole-number floats (openpyxl hands
    back e.g. 5.0 for an integer-looking cell) are rendered without the
    trailing ".0" so numeric option/answer cells read naturally."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _parse_row(
    values: dict[str, str],
    option_columns: list[str],
    row_number: int,
    default_category: str | None,
) -> ParsedQuestion | RowError:
    """Validates and builds one question row. Shared by the CSV and XLSX
    readers below so both formats — and any header-naming convention either
    of them accepts — are held to exactly the same rules.

    `default_category` is the category selected by the admin in the upload
    UI, used for any row that has no `category` cell of its own (e.g. a
    single-category spreadsheet, like the question-writer's per-category
    template, that never included that column). A row's own category value,
    when present, always wins over the default.
    """
    category = (values.get("category") or "").strip() or (default_category or "").strip()
    question_text = (values.get("question_text") or "").strip()

    if not category:
        return RowError(
            row=row_number,
            reason="missing category, and no default category was selected for this upload",
        )
    if category not in VALID_CATEGORIES:
        return RowError(
            row=row_number,
            reason=f"invalid category '{category}', expected one of {sorted(VALID_CATEGORIES)}",
        )
    if not question_text:
        return RowError(row=row_number, reason="missing question text")

    options = [values[col].strip() for col in option_columns if (values.get(col) or "").strip()]
    correct_answer = (values.get("correct_answer") or "").strip() or None
    difficulty = (values.get("difficulty") or "").strip() or "medium"

    if correct_answer is not None:
        # Test A's grading engine only supports a single correct option per
        # question (app/test_engine/grading.py compares one submitted index
        # against one correct_index) — a row whose correct_answer doesn't
        # resolve to exactly one option (e.g. a "Multiple Correct Answers"
        # row with "A, C") would otherwise sit in the bank until it's
        # randomly selected for a live test session and blows up test-start
        # for every candidate in that category. Reject it here instead,
        # at import time, where it's just a skipped row with a clear reason.
        try:
            resolve_correct_answer_text(options, correct_answer)
        except InvalidCorrectAnswer as exc:
            return RowError(row=row_number, reason=f"correct_answer problem: {exc}")

    return ParsedQuestion(
        category=category,
        question_text=question_text,
        options=options or None,
        correct_answer=correct_answer,
        difficulty=difficulty,
    )


def parse_questions_csv(
    content: str, default_category: str | None = None
) -> tuple[list[ParsedQuestion], list[RowError]]:
    """Parses a question-bank CSV into rows ready for Question creation.

    Recognized columns (case/spacing-insensitive, e.g. "Question" or
    "Correct Answer" both work): category, question_text, correct_answer,
    difficulty (defaults to 'medium' if blank). Any column whose header
    starts with "option" (Option A, option_b, ...) is collected in header
    order — blank cells are skipped — to build the JSONB `options` list, so
    the number of options per question is not fixed. Unrecognized columns
    (e.g. a "Question No" or "Question Type" index column) are ignored.

    `category` may be omitted from the file entirely if `default_category`
    is supplied (used for every row that has no category cell of its own).

    Rows with a missing/blank category, question text, or a correct_answer
    that can't be resolved to exactly one option, are skipped and reported
    in the returned errors list rather than aborting the whole upload.
    """
    reader = csv.DictReader(io.StringIO(content))
    headers = [_normalize_header(h) for h in (reader.fieldnames or []) if h]
    option_columns = [h for h in headers if h.startswith("option")]

    questions: list[ParsedQuestion] = []
    errors: list[RowError] = []

    for row_number, row in enumerate(reader, start=2):  # header is row 1
        values = {_normalize_header(k): (v or "") for k, v in row.items() if k}
        result = _parse_row(values, option_columns, row_number, default_category)
        if isinstance(result, RowError):
            errors.append(result)
        else:
            questions.append(result)

    return questions, errors


def parse_questions_xlsx(
    raw: bytes, default_category: str | None = None
) -> tuple[list[ParsedQuestion], list[RowError]]:
    """Same contract as parse_questions_csv, reading the first worksheet of
    an .xlsx workbook instead of CSV text. Row 1 is the header row."""
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
    except Exception as exc:
        raise ValueError(f"Could not read this as an Excel (.xlsx) file: {exc}") from exc

    sheet = workbook.active
    if sheet is None:
        return [], []

    rows_iter = sheet.iter_rows(values_only=True)
    try:
        header_row = next(rows_iter)
    except StopIteration:
        return [], []

    headers = [_normalize_header(_cell_str(h)) for h in header_row]
    option_columns = [h for h in headers if h.startswith("option")]

    questions: list[ParsedQuestion] = []
    errors: list[RowError] = []

    for row_number, raw_row in enumerate(rows_iter, start=2):  # header is row 1
        if raw_row is None or all(cell is None for cell in raw_row):
            continue  # trailing blank rows are common in exported sheets
        values = {
            headers[i]: (_cell_str(raw_row[i]) if i < len(raw_row) else "")
            for i in range(len(headers))
            if headers[i]
        }
        result = _parse_row(values, option_columns, row_number, default_category)
        if isinstance(result, RowError):
            errors.append(result)
        else:
            questions.append(result)

    return questions, errors


def parse_questions_file(
    filename: str, raw: bytes, default_category: str | None = None
) -> tuple[list[ParsedQuestion], list[RowError]]:
    """Dispatches to the CSV or XLSX reader based on the uploaded file's
    extension. Raises ValueError (caller turns this into a 422) for an
    unsupported extension or an undecodable CSV."""
    lower_name = (filename or "").lower()
    if lower_name.endswith(".xlsx"):
        return parse_questions_xlsx(raw, default_category)
    if lower_name.endswith(".csv"):
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("CSV file must be UTF-8 encoded") from exc
        return parse_questions_csv(content, default_category)
    raise ValueError("Unsupported file type — upload a .csv or .xlsx file")
