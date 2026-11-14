#!/usr/bin/env python3
"""Synthetic inventory-query scaling probe; this is not an Arcata speed score."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from town_services import ServiceTown


def grouped(town):
    jobs, visits = defaultdict(list), defaultdict(list)
    for job in town.jobs.values():
        if job['stage'] != 'return':
            jobs[job['destination'], job['resource']].append(job['amount'])
    for visit in town.visits.values():
        if visit['purpose'] == 'shopping':
            visits[visit['origin'], visit['resource']].append(visit['amount'])
    return {key: sum(jobs.get(key, ())) + sum(visits.get(key, ()))
            for key in jobs.keys() | visits.keys()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeat', type=int, default=5)
    args = parser.parse_args()
    rows = []
    for n in (0, 100, 1000, 2000):
        town = ServiceTown.__new__(ServiceTown)
        town.jobs = {i: dict(destination=str(i % 4000), resource='food',
                            amount=3.1, stage='return' if i % 7 == 0 else 'outbound') for i in range(n // 10)}
        town.visits = {i: dict(origin=str(i % 4000), purpose='meal' if i % 7 == 0 else 'shopping',
                              resource='food', amount=2.9) for i in range(n)}
        keys = [(str(i), 'food') for i in range(4000)] * 2
        scan, indexed = [], []
        for _ in range(args.repeat):
            start = time.perf_counter()
            expected = [town.incoming(*key) for key in keys]
            scan.append(time.perf_counter() - start)
            start = time.perf_counter()
            totals = town._incoming_totals() if hasattr(town, '_incoming_totals') else grouped(town)
            actual = [totals.get(key, 0) for key in keys]
            indexed.append(time.perf_counter() - start)
            assert actual == expected
        rows.append(dict(jobs=len(town.jobs), visits=len(town.visits), queries=len(keys),
                         scan_seconds=scan, grouped_seconds=indexed,
                         scan_median_seconds=statistics.median(scan), grouped_median_seconds=statistics.median(indexed)))
    args.output.write_text(json.dumps(dict(scope='synthetic; includes group construction each pass; exact result equality', rows=rows), indent=2))


if __name__ == '__main__':
    main()
