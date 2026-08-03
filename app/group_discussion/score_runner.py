"""Run GDPI scoring across a session's participants from stored transcript."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.group_discussion.scoring import (
    compute_overall_score,
    match_speaker_to_participant,
    parse_speaker_turns,
    score_gd_participant,
)
from app.models.group_discussion import GdSession

logger = logging.getLogger(__name__)


def score_session_participants(db: Session, session: GdSession) -> GdSession:
    """Score each matched participant via Claude. Skips unmatched speakers.

    Requires session.transcript_text. Does not change Application.status.
    """
    transcript = (session.transcript_text or session.transcript_vtt or "").strip()
    if not transcript:
        raise ValueError("Session has no transcript to score")

    roster: list[tuple[str, str | None]] = []
    by_app_id: dict[str, GdParticipant] = {}
    for p in session.participants:
        if p.role != "candidate":
            continue
        name = p.application.applicant.full_name if p.application and p.application.applicant else None
        app_id = str(p.application_id)
        roster.append((app_id, name))
        by_app_id[app_id] = p
        p.scoring_status = "pending"
        p.scores = None
        p.overall_score = None
        p.score_rationale = None
        p.speaker_labels = None

    turns_by_speaker = parse_speaker_turns(transcript)
    # Aggregate speaker labels → application_id
    turns_by_app: dict[str, list[str]] = {}
    labels_by_app: dict[str, list[str]] = {}
    unmatched_speakers: list[str] = []

    for speaker, utterances in turns_by_speaker.items():
        app_id = match_speaker_to_participant(speaker, roster)
        if app_id is None:
            unmatched_speakers.append(speaker)
            continue
        turns_by_app.setdefault(app_id, []).extend(utterances)
        labels_by_app.setdefault(app_id, []).append(speaker)

    topic_hint = session.label
    now = datetime.now(timezone.utc)

    for app_id, participant in by_app_id.items():
        utterances = turns_by_app.get(app_id)
        if not utterances:
            participant.scoring_status = "skipped"
            participant.score_rationale = (
                "No transcript turns matched this candidate's name to a speaker label."
            )
            participant.scored_at = now
            continue

        name = (
            participant.application.applicant.full_name
            if participant.application and participant.application.applicant
            else "Candidate"
        )
        candidate_turns = "\n".join(utterances)
        participant.scoring_status = "scoring"
        participant.speaker_labels = labels_by_app.get(app_id)
        db.flush()

        try:
            scores, rationale = score_gd_participant(
                candidate_name=name or "Candidate",
                candidate_turns=candidate_turns,
                full_transcript=transcript,
                topic_hint=topic_hint,
            )
            participant.scores = scores
            participant.overall_score = compute_overall_score(scores)
            participant.score_rationale = rationale
            participant.scoring_status = "scored"
            participant.scored_at = now
        except Exception as exc:
            logger.exception("GD scoring failed for application %s", app_id)
            participant.scoring_status = "failed"
            participant.score_rationale = str(exc)[:500]
            participant.scored_at = now

    if unmatched_speakers:
        # Soft note on session artifacts_error without wiping recording success.
        note = "Unmatched speakers (not scored): " + ", ".join(sorted(set(unmatched_speakers)))
        existing = session.artifacts_error or ""
        session.artifacts_error = (existing + " | " + note).strip(" |")[:800]

    session.status = "scored"
    session.updated_at = now
    db.commit()
    db.refresh(session)
    return session
