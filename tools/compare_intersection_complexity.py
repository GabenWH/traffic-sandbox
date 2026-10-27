"""Run a paired scaling comparison of unsignalized, four-way-stop, and roundabout.

Example:
    python3 tools/compare_intersection_complexity.py \
        --seeds 0-29 --seconds 90 --output /tmp/intersection-complexity.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from intersection_complexity import DEMAND_LEVELS, compare_intersection_complexity


def _parse_seeds(value: str) -> tuple[int, ...]:
    value = value.strip()
    if "-" in value and "," not in value:
        first, last = (int(item.strip()) for item in value.split("-", 1))
        if first > last:
            raise argparse.ArgumentTypeError("Seed range must be ascending")
        return tuple(range(first, last + 1))
    try:
        return tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as error:
        raise argparse.ArgumentTypeError("Use comma-separated seeds or START-END") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=_parse_seeds, default=tuple(range(30)))
    parser.add_argument("--seconds", type=float, default=90.0)
    parser.add_argument("--dt", type=float, default=0.05)
    parser.add_argument("--max-cars", type=int, default=80)
    parser.add_argument(
        "--levels",
        type=lambda value: tuple(item.strip() for item in value.split(",") if item.strip()),
        default=tuple(DEMAND_LEVELS),
        help="Comma-separated demand levels: low, medium, high",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--progress-every", type=int, default=30)
    args = parser.parse_args()
    total = len(args.seeds) * len(args.levels) * 3

    def show_progress(message: str) -> None:
        completed = int(message.split("/", 1)[0])
        if completed % args.progress_every == 0 or completed == total:
            print(f"[{message}]", file=sys.stderr, flush=True)

    result = compare_intersection_complexity(
        seeds=args.seeds,
        seconds=args.seconds,
        dt=args.dt,
        max_cars=args.max_cars,
        demand_levels=args.levels,
        progress=show_progress,
    )
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output is None:
        print(rendered)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
