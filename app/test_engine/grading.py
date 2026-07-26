from app.models.stage3_test_a import TestASession


def grade_submission(session: TestASession, answers: dict[str, list[int]]) -> float:
    """Grades submitted answers against the session's stored question
    snapshot. A missing answer for a question counts as wrong, not an
    error — candidates can skip questions. Extra/unknown keys in answers
    are ignored.

    A question is correct only if the candidate's selected option indices
    are EXACTLY the set in `correct_indices` — for a single-answer question
    that's one index either matching or not; for a multi-select question
    ("select all that apply") this requires picking every correct option and
    no incorrect one, with no partial credit for a partial match.

    Returns a percentage score (0-100), rounded to 2 decimal places.
    """
    questions = session.generated_questions
    if not questions:
        return 0.0

    correct = 0
    for question in questions:
        given = set(answers.get(question["question_id"]) or [])
        expected = set(question.get("correct_indices", []))
        if given == expected:
            correct += 1

    return round(correct / len(questions) * 100, 2)
