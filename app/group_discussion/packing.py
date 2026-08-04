"""Shuffle-and-pack candidates into GD groups sized [min_size, max_size]."""

from __future__ import annotations

import math
import random
import uuid

from app.models.stage1 import Application


def compute_group_sizes(n: int, min_size: int, max_size: int) -> list[int]:
    """Return group sizes summing to n, each in [min_size, max_size]."""
    if min_size < 1 or max_size < min_size:
        raise ValueError("Invalid min_size / max_size")
    if n < min_size:
        raise ValueError(
            f"Need at least {min_size} candidates to form a group (got {n})"
        )
    if n <= max_size:
        return [n]

    num_groups = math.ceil(n / max_size)
    if num_groups * min_size > n:
        raise ValueError(
            f"Cannot pack {n} candidates into groups of {min_size}–{max_size}. "
            "Adjust the selection or group size settings in Preferences."
        )

    while math.ceil(n / num_groups) > max_size:
        num_groups += 1
        if num_groups * min_size > n:
            raise ValueError(
                f"Cannot pack {n} candidates into groups of {min_size}–{max_size}."
            )

    base, rem = divmod(n, num_groups)
    sizes = [base + (1 if i < rem else 0) for i in range(num_groups)]
    if min(sizes) < min_size or max(sizes) > max_size:
        raise ValueError(
            f"Cannot pack {n} candidates into groups of {min_size}–{max_size}."
        )
    return sizes


def shuffle_pack(
    applications: list[Application],
    *,
    min_size: int,
    max_size: int,
    seed: int | None = None,
) -> list[list[Application]]:
    sizes = compute_group_sizes(len(applications), min_size, max_size)
    pool = list(applications)
    rng = random.Random(seed)
    rng.shuffle(pool)
    groups: list[list[Application]] = []
    idx = 0
    for size in sizes:
        groups.append(pool[idx : idx + size])
        idx += size
    return groups


def ids_of(groups: list[list[Application]]) -> list[list[uuid.UUID]]:
    return [[app.id for app in group] for group in groups]
