"""Compare the legacy and data-first traffic engines on one merge-lab case.

Example:
    python3 tools/compare_traffic_engines.py slip-lane-short-link \
        --seeds 3,7,42 --seconds 120 --repeats 3
    python3 tools/compare_traffic_engines.py dense-network-gauntlet \
        --seeds 7 --seconds 600 --repeats 1 --window-seconds 60
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from traffic_comparison import compare_traffic_engines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", nargs="?", default="slip-lane-short-link")
    parser.add_argument("--seeds", default="3,7,42", help="Comma-separated integer seeds")
    parser.add_argument("--seconds", type=float, default=120.0)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--dt", type=float, default=0.05)
    parser.add_argument("--window-seconds", type=float, default=60.0)
    args = parser.parse_args()
    seeds = tuple(int(value.strip()) for value in args.seeds.split(",") if value.strip())
    result = compare_traffic_engines(
        args.scenario,
        seeds=seeds,
        seconds=args.seconds,
        repeats=args.repeats,
        dt=args.dt,
        window_seconds=args.window_seconds,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
