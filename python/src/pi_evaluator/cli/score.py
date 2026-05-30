"""pi-eval score: write a subjective score sidecar for a completed trial."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from ..adapters.per_trial_directory_adapter import PerTrialDirectoryAdapter
from ..domain.types import SubjectiveScore


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="pi-eval score",
        description="Attach a subjective score to a completed trial.",
    )
    p.add_argument("--base-dir", required=True, help="Trial storage root directory.")
    p.add_argument("--trial-id", required=True, help="ID of the completed trial.")
    p.add_argument(
        "--score",
        required=True,
        type=float,
        help="Subjective score in [0.0, 1.0].",
    )
    p.add_argument("--scorer", required=True, help="Scorer identity (e.g. user:alice).")
    p.add_argument("--notes", default="", help="Free-text notes (optional).")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not (0.0 <= args.score <= 1.0):
        print(
            f"error: --score must be in [0.0, 1.0]; got {args.score}",
            file=sys.stderr,
        )
        return 1

    ss = SubjectiveScore(
        score=args.score,
        notes=args.notes,
        scorer=args.scorer,
        timestamp=datetime.now(UTC).isoformat(),
    )
    adapter = PerTrialDirectoryAdapter(args.base_dir)
    try:
        adapter.write_subjective_score(args.trial_id, ss)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
