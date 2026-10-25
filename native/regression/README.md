# Python → C++ regression baseline

This is the first stage of the native traffic migration. **The Python engine
still does all driving.** A standalone C++17 program checks its regression output
and actual routed-vehicle positions before we implement a native engine.

From the repository root:

```sh
python tools/cpp_parity.py
```

Requires Python 3.11+ with the normal project requirements and a C++17 compiler
available as `c++` (GCC or Clang). No pytest, CMake, downloaded C++ packages, or
Python embedding library is required. Optional tests retain the original suite's
skips, such as Panda3D tests when that dependency is unavailable.

The command discovers **all existing `tests/test_*.py` regressions**. It excludes
`test_cpp_parity.py` and `test_native_*.py` from this export. These harness tests
deliberately reject corrupted results, so their expected assertion failures must
not be replayed as traffic regressions. They run normally in the Python suite:

```sh
python -m unittest discover -s tests -q
```

For a quick single-module check:

```sh
python tools/cpp_parity.py --pattern test_car_brain.py --output build/cpp-brain-parity
```

The full export can be large: it retains initialization and every successful
`advance` call across long regressions. It is **not a speed benchmark**. The
observation hooks and trace I/O add overhead and are removed after export.

## What C++ checks

- Regression assertion operands, using their original operators, expected values,
  thresholds, test IDs, and source locations. Equality, numeric ordering,
  membership, truth/null checks, count equality, and numeric tolerances have
  native implementations. This is a data-driven assertion port, not a rewrite
  of the Python scenario setup in C++.
- Each imported vehicle's position and heading, independently recomputed from
  its exported route points and longitudinal distance. Absolute tolerance is
  `1e-8`, plus `1e-12` times coordinate magnitude. Export uses full precision.
- Finite numeric state, positive dimensions, nonnegative speed/desired speed/
  stop timer, and recognized brain/signal values.
- Corpus completeness: version, record types, route references, unique test
  results, consecutive sample IDs, trailer totals, and nonempty assertions.

Snapshots also include current lane/progress, wait reason, and claim ID for the
next migration stage. Those fields are diagnostic data at this stage; C++ does
not yet reproduce lane selection, claims, or decisions.

## What remains in Python

Python still constructs scenarios, runs the original regressions, and calculates
the actual outputs being checked. A recorded boolean such as
`assertFalse(cars_overlap(a, b))` replays that boolean; it **does not** independently
reimplement rectangle overlap. Object equality, identity, type checks, expected
exceptions, regex checks, and other unsupported forms remain Python-only. Bare
`assert` statements also run only in Python. These are not counted as native
assertions. `report.json` lists every test's native assertions, recorded motion
samples, Python-only assertions with reasons/source locations, status, and skips.
Expected-failure tests and explicit Python sequence type constraints remain
Python-only too; an unexpected success still fails the run.

Consequently, a green replay proves the native import/checking pipeline agrees
with these saved Python results. It **does not** prove parity of an unimplemented
C++ traffic engine. The next step is to port scenario inputs and behavioral
predicates, then run both engines on identical inputs and compare per-tick outputs.
The existing Python-only coverage inventory makes the remaining port explicit.

Python failures/errors, native assertion failures, invalid/missing data, and an
empty assertion corpus return a nonzero exit code. Skips stay visible and do not
become passes. The integration tests deliberately damage an assertion operand
and an actual vehicle position and verify that C++ rejects both.

## Outputs and replay

Default outputs are ignored build artifacts:

- `build/cpp-parity/corpus.parity`: typed assertion and vehicle-state corpus.
- `build/cpp-parity/report.json`: coverage and original source SHA-256 hashes,
  baseline git revision, Python failures/errors/skips, and limitations.
- `build/cpp-parity/bin/check_python_baseline`: standalone native executable.

Replay without Python:

```sh
build/cpp-parity/bin/check_python_baseline build/cpp-parity/corpus.parity
```

Or compile directly:

```sh
c++ -std=c++17 -O2 -Wall -Wextra -Werror native/regression/check_python_baseline.cpp -o build/check_python_baseline
build/check_python_baseline build/cpp-parity/corpus.parity
```

## Corpus version 1

The text format uses whitespace-separated tokens and UTF-8 strings encoded in
hex (`-` is an empty string), keeping strings with spaces/newlines unambiguous.
The first line is `TRAFFIC_PARITY 1`. Each remaining record occupies one line:

| Record | Contents |
|---|---|
| `A` | Test ID, source file, line, assertion method, actual value, expected value, `[places, delta]` |
| `R` | Route ID, point count, then x/y coordinates |
| `P` | Test ID, sample ID, vehicle ID, route ID, route distance, speed, length, width, total route length, x/y, heading x/y, brain state, turn signal, lane key, lane distance, desired speed, stop timer, wait reason, claim ID |
| `T` | Test ID, Python result status |
| `END` | Assertion count, motion sample count, Python test count |

Value tags: `n` null, `b` boolean, `i` integer, `f` finite float, `s` hex string;
`l` list, `t` tuple, `e` set, `m` dictionary, followed by a count and recursively
encoded items (key/value pairs for dictionaries). Integers outside the exact
double range are Python-only. Numeric float formatting uses Python `repr`.
