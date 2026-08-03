"""Pick GD participants from an eligible pool.

Strategies: composite | gender_mix | random | manual.
"""

from __future__ import annotations

import random
import uuid
from collections import defaultdict

from app.models.stage1 import Application

STRATEGIES = frozenset({"composite", "gender_mix", "random", "manual"})


def _composite_score(app: Application) -> float:
    match = app.preference_match_result
    if match is None or match.composite_score is None:
        return float("-inf")
    return float(match.composite_score)


def _gender(app: Application) -> str:
    data = app.profile_data.data if app.profile_data and isinstance(app.profile_data.data, dict) else {}
    raw = data.get("gender")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower()
    return "unknown"


def pick_participants(
    eligible: list[Application],
    *,
    strategy: str,
    target_size: int,
    application_ids: list[uuid.UUID] | None = None,
) -> list[Application]:
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown assignment_strategy: {strategy}")
    if target_size < 2 or target_size > 12:
        raise ValueError("target_size must be between 2 and 12")

    if strategy == "manual" or application_ids is not None:
        if not application_ids:
            raise ValueError("manual assignment requires application_ids")
        by_id = {app.id: app for app in eligible}
        missing = [str(i) for i in application_ids if i not in by_id]
        if missing:
            raise ValueError(
                "These applications are not eligible for GD (need both scores, "
                f"campus status, and not already in an active session): {', '.join(missing)}"
            )
        # Preserve caller order for manual picks.
        return [by_id[i] for i in application_ids]

    pool = list(eligible)
    if strategy == "composite":
        pool.sort(key=_composite_score, reverse=True)
        return pool[:target_size]

    if strategy == "random":
        random.shuffle(pool)
        return pool[:target_size]

    # gender_mix — round-robin across gender buckets, fill by composite within bucket
    buckets: dict[str, list[Application]] = defaultdict(list)
    for app in sorted(pool, key=_composite_score, reverse=True):
        buckets[_gender(app)].append(app)

    # Prefer known genders first, unknown last
    keys = sorted((k for k in buckets if k != "unknown")) + (
        ["unknown"] if "unknown" in buckets else []
    )
    picked: list[Application] = []
    indices = {k: 0 for k in keys}
    while len(picked) < target_size and any(indices[k] < len(buckets[k]) for k in keys):
        progressed = False
        for key in keys:
            if len(picked) >= target_size:
                break
            i = indices[key]
            if i < len(buckets[key]):
                picked.append(buckets[key][i])
                indices[key] = i + 1
                progressed = True
        if not progressed:
            break
    return picked
