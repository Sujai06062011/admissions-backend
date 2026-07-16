from app.models.stage3_test_a import TestASession


def grade_submission(session: TestASession, answers: dict[str, int]) -> float:
    """Grades submitted answers against the session's stored question
    snapshot. A missing answer for a question counts as wrong, not an error —
    candidates can skip questions. Extra/unknown keys in answers are ignored.

    Returns a percentage score (0-100), rounded to 2 decimal places.
    """
    questions = session.generated_questions
    if not questions:
        return 0.0

    correct = sum(
        1
        for question in questions
        if answers.get(question["question_id"]) == question["correct_index"]
    )
    return round(correct / len(questions) * 100, 2)
