import base64
import os

import anthropic

MODEL = "claude-sonnet-5"

_PROCTORING_TOOL = {
    "name": "submit_proctoring_review",
    "description": (
        "Submit the academic-integrity review of a candidate's interview snapshots."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "faces_per_snapshot": {
                "type": "array",
                "items": {"type": "integer", "minimum": 0},
                "description": (
                    "Number of distinct human faces visible in each snapshot, in the "
                    "same order the images were provided. 0 if the frame is blank, "
                    "too dark, or no face is clearly visible — never guess a face is "
                    "present if you can't actually see one."
                ),
            },
            "flagged": {
                "type": "boolean",
                "description": (
                    "True only if a snapshot shows clear evidence of a second person, "
                    "a substituted candidate, or another concrete integrity concern "
                    "actually visible in the images. False for ordinary issues like "
                    "poor lighting, an off-center camera angle, or one person's face "
                    "being partially out of frame."
                ),
            },
            "notes": {
                "type": "string",
                "description": (
                    "1-3 factual sentences describing exactly what's visible that led "
                    "to this flagged value, or a brief confirmation nothing unusual "
                    "was seen. Describe only what is visible in the images — never "
                    "speculate about intent or identity."
                ),
            },
        },
        "required": ["faces_per_snapshot", "flagged", "notes"],
    },
}

_PROMPT = """You are reviewing snapshots automatically captured during a candidate's live video interview for a college admissions process, purely for academic-integrity verification — checking that the interview appears to be taken alone and unassisted by anyone else physically present.

The images below are frames grabbed at random moments from the candidate's own webcam feed during their interview, shown in the order they were captured. This is not a security or law-enforcement context — treat ambiguous or low-quality frames conservatively (assume nothing is wrong) rather than reporting a concern you aren't actually confident is visible.

Call submit_proctoring_review with your findings."""


def review_snapshots(snapshot_bytes: list[bytes]) -> tuple[dict, str]:
    """Sends 2-3 interview snapshots to Claude in a single vision call for a
    combined multi-face-detection + academic-integrity review, using
    tool-calling for reliable structured output — same pattern as
    app/interview_engine/scoring.py's score_transcript.

    Returns (review, notes): review has exactly {faces_per_snapshot, flagged},
    matching the ProctoringReview schema (minus notes/reviewed_at, which the
    caller attaches). Raises on API failure or empty input; the caller (a
    background job) is responsible for catching and recording that failure.
    """
    if not snapshot_bytes:
        raise ValueError("review_snapshots requires at least one snapshot")

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    content: list[dict] = [{"type": "text", "text": _PROMPT}]
    for image_bytes in snapshot_bytes:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                },
            }
        )

    message = client.messages.create(
        model=MODEL,
        max_tokens=512,
        tools=[_PROCTORING_TOOL],
        tool_choice={"type": "tool", "name": _PROCTORING_TOOL["name"]},
        messages=[{"role": "user", "content": content}],
    )

    tool_use = next(block for block in message.content if block.type == "tool_use")
    result = dict(tool_use.input)
    notes = result.pop("notes")
    return result, notes
