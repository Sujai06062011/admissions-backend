"""Ensure every program has a gd_score PreferenceConfig at 10% soft weight.

Idempotent: skips programs that already have a gd_score row (does not overwrite
an admin-tuned weight).

Usage:
    python scripts/ensure_gd_preference_weight.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.models.core import Program  # noqa: E402
from app.models.stage2 import PreferenceConfig  # noqa: E402
from app.preferences.matching import ensure_gd_score_preference  # noqa: E402


def main() -> None:
    db = SessionLocal()
    try:
        programs = db.query(Program).all()
        inserted = 0
        for program in programs:
            before = (
                db.query(PreferenceConfig)
                .filter(
                    PreferenceConfig.program_id == program.id,
                    PreferenceConfig.field_name == "gd_score",
                )
                .first()
            )
            ensure_gd_score_preference(db, program.id)
            if before is None:
                inserted += 1
                print(f"inserted gd_score@0.10 for {program.name} ({program.id})")
        db.commit()
        print(f"done — inserted {inserted}, skipped {len(programs) - inserted}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
