#!/usr/bin/env python3
"""Export the existing Python regressions for independent native baseline checks.

This is deliberately test tooling, not a second implementation of the engine.
See native/regression/README.md for coverage boundaries and the wire format.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import functools
import hashlib
import inspect
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def hex_text(value):
    return str(value).encode("utf-8").hex() or "-"


def pack(value, depth=0):
    """Encode portable values, refusing opaque Python equality semantics."""
    if depth > 30:
        raise TypeError("container nesting exceeds 30")
    if value is None:
        return "n"
    if isinstance(value, bool):
        return f"b {int(value)}"
    if isinstance(value, int):
        # C++ double cannot represent arbitrary Python integers exactly.
        if abs(value) > 2**53:
            raise TypeError("integer outside exact double range")
        return f"i {value}"
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("nonfinite assertion operand")
        return f"f {value!r}"
    if isinstance(value, str):
        return f"s {hex_text(value)}"
    if isinstance(value, (list, tuple, set, frozenset)):
        tag = "l" if isinstance(value, list) else "t" if isinstance(value, tuple) else "e"
        encoded = [pack(item, depth+1) for item in value]
        if tag == "e":
            encoded.sort()
        return " ".join([tag, str(len(encoded)), *encoded])
    if isinstance(value, dict):
        encoded = [f"{pack(key, depth+1)} {pack(item, depth+1)}"
                   for key, item in value.items()]
        return " ".join(["m", str(len(encoded)), *encoded])
    raise TypeError(f"Python object: {type(value).__module__}.{type(value).__name__}")


NATIVE_METHODS = {
    "assertEqual", "assertNotEqual", "assertTrue", "assertFalse", "assertIsNone",
    "assertIsNotNone", "assertGreater", "assertGreaterEqual", "assertLess",
    "assertLessEqual", "assertAlmostEqual", "assertIn", "assertNotIn",
    "assertCountEqual", "assertListEqual", "assertTupleEqual", "assertDictEqual",
    "assertSetEqual", "assertSequenceEqual", "assertMultiLineEqual",
}
UNARY_METHODS = {"assertTrue", "assertFalse", "assertIsNone", "assertIsNotNone"}


class Corpus:
    def __init__(self, output):
        self.output = output
        self.test = "outside-test"
        self.test_records = {}
        self.routes = {}
        self.motion_samples = 0
        self.assertions = 0
        self.python_only = 0
        self.assertion_depth = 0
        self.write("TRAFFIC_PARITY", 1)

    def write(self, *parts):
        self.output.write(" ".join(map(str, parts)) + "\n")

    def entry(self):
        return self.test_records.setdefault(self.test, {
            "id": self.test, "native_assertions": 0, "motion_samples": 0,
            "python_only_assertions": [], "status": "running",
        })

    def assertion(self, method, args, kwargs, filename, line):
        location = {"file": filename, "line": line, "method": method}
        try:
            if self.entry().get("expected_failure"):
                raise TypeError("expected-failure test remains Python-only")
            if method not in NATIVE_METHODS:
                raise TypeError("Python identity/type/exception/regex assertion")
            if method == "assertSequenceEqual" and kwargs.get(
                "seq_type", args[3] if len(args) > 3 else None,
            ) is not None:
                raise TypeError("explicit Python sequence type constraint")
            unary = method in UNARY_METHODS
            if not args or (len(args) < 2 and not unary):
                raise TypeError("keyword-only assertion operands")
            if method in {"assertIsNone", "assertIsNotNone"}:
                first = "n" if args[0] is None else "b 1"
            else:
                first = pack(args[0])
            second = pack(None if unary else args[1])
            places, delta = 7, None
            if method == "assertAlmostEqual":
                places = kwargs.get("places", args[2] if len(args) > 2 else 7)
                places = 7 if places is None else places
                delta = kwargs.get("delta", args[4] if len(args) > 4 else None)
                if not isinstance(places, int) or not -300 <= places <= 300:
                    raise TypeError("unsupported decimal precision")
            options = pack([places, delta])
        except TypeError as error:
            self.python_only += 1
            self.entry()["python_only_assertions"].append({**location, "reason": str(error)})
            return
        self.assertions += 1
        self.entry()["native_assertions"] += 1
        self.write("A", hex_text(self.test), hex_text(filename), line,
                   hex_text(method), first, second, options)

    def position(self, car):
        if self.entry().get("expected_failure"):
            return
        points = tuple(tuple(point) for point in car.points)
        if points not in self.routes:
            route = len(self.routes) + 1
            self.routes[points] = route
            self.write("R", route, len(points), *(repr(v) for p in points for v in p))
        route = self.routes[points]
        self.motion_samples += 1
        self.entry()["motion_samples"] += 1
        # Resolve the current lane without invoking occupancy queries or changing it.
        lane_key, lane_distance = "", 0.0
        for start, end, key, offset in car.route_segments:
            if car.distance < end or end == car.total_length:
                lane_key = json.dumps(key, separators=(",", ":"))
                lane_distance = offset + max(0, min(end-start, car.distance-start))
                break
        self.write(
            "P", hex_text(self.test), self.motion_samples, hex_text(car.id), route,
            repr(car.distance), repr(car.speed), repr(car.length), repr(car.width),
            repr(car.total_length), *(repr(v) for v in (*car.position, *car.heading)),
            hex_text(car.brain.state), hex_text(car.brain.signal_intent),
            hex_text(lane_key), repr(lane_distance), repr(car.brain.desired_speed),
            repr(car.brain.stopped_elapsed), hex_text(car.brain.wait_reason),
            hex_text(car.claimed_movement.id if car.claimed_movement else ""),
        )


class RecordingResult(unittest.TextTestResult):
    def __init__(self, stream, descriptions, verbosity, *, corpus):
        super().__init__(stream, descriptions, verbosity)
        self.corpus = corpus

    def startTest(self, test):
        super().startTest(test)
        self.corpus.test = test.id()
        method = getattr(test, test._testMethodName, None)
        self.corpus.entry()["expected_failure"] = bool(
            getattr(test, "__unittest_expecting_failure__", False)
            or getattr(method, "__unittest_expecting_failure__", False)
        )

    def stopTest(self, test):
        entry = self.corpus.entry()
        if entry["status"] == "running":
            entry["status"] = "passed"
        self.corpus.write("T", hex_text(test.id()), hex_text(entry["status"]))
        super().stopTest(test)

    def addFailure(self, test, err):
        self.corpus.entry()["status"] = "failed"
        super().addFailure(test, err)

    def addError(self, test, err):
        self.corpus.entry()["status"] = "error"
        super().addError(test, err)

    def addSkip(self, test, reason):
        self.corpus.entry().update(status="skipped", skip_reason=reason)
        super().addSkip(test, reason)

    def addSubTest(self, test, subtest, err):
        if err is not None:
            self.corpus.entry()["status"] = "failed"
        super().addSubTest(test, subtest, err)

    def addUnexpectedSuccess(self, test):
        self.corpus.entry()["status"] = "unexpected_success"
        super().addUnexpectedSuccess(test)

    def addExpectedFailure(self, test, err):
        self.corpus.entry()["status"] = "expected_failure"
        super().addExpectedFailure(test, err)


def assertion_hook(corpus, name, original):
    @functools.wraps(original)
    def observe(self, *args, **kwargs):
        if corpus.assertion_depth:
            return original(self, *args, **kwargs)
        frame = inspect.currentframe().f_back
        try:
            filename = str(Path(frame.f_code.co_filename).resolve().relative_to(ROOT))
        except ValueError:
            filename = frame.f_code.co_filename
        line = frame.f_lineno
        del frame
        corpus.assertion(name, args, kwargs, filename, line)
        corpus.assertion_depth += 1
        try:
            return original(self, *args, **kwargs)
        finally:
            corpus.assertion_depth -= 1
    return observe


def export_suite(suite, output_dir, *, stream=None):
    from traffic_testbed import RoutedRoadVehicle
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "corpus.parity").open("w", encoding="utf-8") as output:
        corpus = Corpus(output)
        original_advance = RoutedRoadVehicle.advance
        original_init = RoutedRoadVehicle.__post_init__

        def advance(car, elapsed_seconds):
            result = original_advance(car, elapsed_seconds)
            corpus.position(car)
            return result

        def initialize(car):
            original_init(car)
            corpus.position(car)

        with ExitStack() as hooks:
            for name in dir(unittest.TestCase):
                if name.startswith("assert") and callable(getattr(unittest.TestCase, name)):
                    original = getattr(unittest.TestCase, name)
                    hooks.enter_context(patch.object(
                        unittest.TestCase, name, assertion_hook(corpus, name, original),
                    ))
            hooks.enter_context(patch.object(RoutedRoadVehicle, "advance", advance))
            hooks.enter_context(patch.object(RoutedRoadVehicle, "__post_init__", initialize))
            runner = unittest.TextTestRunner(
                stream=stream or sys.stderr, verbosity=1,
                resultclass=functools.partial(RecordingResult, corpus=corpus),
            )
            result = runner.run(suite)
        corpus.write("END", corpus.assertions, corpus.motion_samples, result.testsRun)

    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = "unknown"
    report = {
        "schema": 1, "baseline_revision": revision,
        "source_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(ROOT.glob("*.py")) + sorted((ROOT / "tests").glob("test_*.py"))
            + [Path(__file__).resolve()] + sorted((ROOT / "native/regression").glob("*.cpp"))
            + sorted((ROOT / "native/regression").glob("*.hpp"))
        },
        "native_assertions": corpus.assertions,
        "python_only_assertions": corpus.python_only,
        "motion_samples": corpus.motion_samples, "routes": len(corpus.routes),
        "python": {
            "tests_run": result.testsRun, "successful": result.wasSuccessful(),
            "failures": [{"id": test.id(), "traceback": detail} for test, detail in result.failures],
            "errors": [{"id": test.id(), "traceback": detail} for test, detail in result.errors],
            "skipped": [{"id": test.id(), "reason": detail} for test, detail in result.skipped],
            "expected_failures": [test.id() for test, _detail in result.expectedFailures],
            "unexpected_successes": [test.id() for test in result.unexpectedSuccesses],
        },
        "coverage": list(corpus.test_records.values()),
        "limits": [
            "Replays Python outputs; does not implement C++ car logic or scenario setup.",
            "Boolean assertions replay recorded Python booleans, not their source expressions.",
            "Python object/type/identity/exception assertions remain Python-only.",
            "Bare Python assert statements run in Python, not in the native assertion replay.",
            "Expected-failure tests remain Python-only; unexpected successes still fail the run.",
            "Observation hooks add overhead; this run is not a performance benchmark.",
        ],
    }
    (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def compile_checker(build_dir):
    compiler = shutil.which("c++")
    if compiler is None:
        raise RuntimeError("Install a C++17 compiler (c++/g++) to run native parity checks")
    directory = Path(build_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    binary = directory / "check_python_baseline"
    subprocess.run([
        compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
        str(ROOT / "native/regression/check_python_baseline.cpp"), "-o", str(binary),
    ], check=True)
    return binary


def without_harness(suite):
    result = unittest.TestSuite()
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            result.addTests(without_harness(item))
        elif not item.id().startswith(("test_cpp_parity.", "test_native_")):
            result.addTest(item)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/cpp-parity")
    parser.add_argument("--pattern", default="test_*.py", help="unittest discovery pattern")
    options = parser.parse_args(argv)
    suite = without_harness(unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=options.pattern))
    report = export_suite(suite, options.output)
    binary = compile_checker(options.output / "bin")
    native = subprocess.run([str(binary), str(options.output / "corpus.parity")],
                            capture_output=True, text=True)
    print(native.stdout, end="")
    print(native.stderr, end="", file=sys.stderr)
    report["native"] = {"exit_code": native.returncode, "stdout": native.stdout, "stderr": native.stderr}
    (options.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "python_tests": report["python"]["tests_run"],
        "python_successful": report["python"]["successful"],
        "python_skipped": len(report["python"]["skipped"]),
        "native_assertions": report["native_assertions"],
        "python_only_assertions": report["python_only_assertions"],
        "motion_samples": report["motion_samples"],
        "native_exit_code": native.returncode, "report": str(options.output / "report.json"),
    }, indent=2))
    return 0 if report["python"]["successful"] and native.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
