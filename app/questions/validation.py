class InvalidCorrectAnswer(Exception):
    """correct_answer doesn't resolve to any of the given options or a valid
    letter label."""


def resolve_correct_answer_text(options: list[str], correct_answer: str | None) -> str:
    """Resolves correct_answer to the literal option text it refers to.

    Accepts two conventions already in use across this codebase: an exact
    match against one of the option strings, or a single letter (A, B, C, ...)
    naming the option's 1-indexed-from-A position — this is how the CSV
    bulk-upload path (app/questions/bulk_import.py) has been used, while the
    single-question-create endpoint has no enforced convention at all.

    Raises InvalidCorrectAnswer if neither resolves.
    """
    text = (correct_answer or "").strip()
    if not text:
        raise InvalidCorrectAnswer("correct_answer is empty")
    if text in options:
        return text
    if len(text) == 1 and text.isalpha():
        index = ord(text.upper()) - ord("A")
        if 0 <= index < len(options):
            return options[index]
    raise InvalidCorrectAnswer(
        f"correct_answer {text!r} does not match any option in {options!r} "
        "and is not a valid letter label"
    )


def resolve_correct_answers_text(
    options: list[str], correct_answers: list[str] | None
) -> list[str]:
    """Multi-select counterpart to resolve_correct_answer_text: resolves each
    entry in `correct_answers` independently (same exact-text-or-letter-label
    rule as above), de-duplicating while preserving order.

    Raises InvalidCorrectAnswer if the list is empty/missing, or if any
    single entry doesn't resolve — same "reject the whole question rather
    than silently drop one option" philosophy as the single-answer path.
    """
    if not correct_answers:
        raise InvalidCorrectAnswer("correct_answers is empty")

    resolved: list[str] = []
    for raw in correct_answers:
        text = resolve_correct_answer_text(options, raw)
        if text not in resolved:
            resolved.append(text)
    return resolved
