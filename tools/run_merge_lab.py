"""Run one repeatable merge-lab scenario and print its safety/timing report.

Examples:
    python3 tools/run_merge_lab.py --list
    python3 tools/run_merge_lab.py roundabout-continuous-pressure --seconds 80
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from merge_lab import MergeLab, scenario_catalog


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", nargs="?", default="roundabout-continuous-pressure")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--dt", type=float, default=0.05)
    parser.add_argument("--list", action="store_true", help="List scenarios and exit")
    parser.add_argument("--trace", type=Path, help="Write the complete frame trace as JSON")
    args = parser.parse_args()
    if args.list:
        for scenario in scenario_catalog():
            print(f"{scenario.name}: {scenario.description} [{', '.join(scenario.conditions)}]")
        return
    report = MergeLab(args.seed).run(args.scenario, seconds=args.seconds, dt=args.dt)
    if args.trace is not None:
        args.trace.write_text(json.dumps({"frames": [asdict(frame) for frame in report.frames]}, indent=2))
    # The short report is intentionally easy to paste into an issue or chat.
    print(json.dumps({
        "scenario": report.scenario,
        "seed": report.seed,
        "seconds": report.seconds,
        "completed": report.completed,
        "remaining": report.remaining,
        "overlap_pair_ticks": report.overlap_pair_ticks,
        "first_overlap": report.first_overlap,
        "timing_summary_ms": report.timing_summary_ms,
        "frames": len(report.frames),
    }, indent=2))


if __name__ == "__main__":
    main()
