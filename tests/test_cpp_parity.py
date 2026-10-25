"""The native baseline checker must reject damaged Python regression output."""

import importlib.util
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("cpp_parity", ROOT / "tools/cpp_parity.py")


@unittest.skipUnless(shutil.which("c++"), "A C++17 compiler is required")
class CppParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temp.name)
        # Load only once it exists, so the first red run explains the missing feature.
        if not SPEC.origin or not Path(SPEC.origin).exists():
            cls.parity = None
            return
        cls.parity = importlib.util.module_from_spec(SPEC)
        SPEC.loader.exec_module(cls.parity)
        cls.binary = cls.parity.compile_checker(cls.directory / "build")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def export(self, case, name="case"):
        self.assertIsNotNone(self.parity, "Python-to-C++ regression exporter is missing")
        directory = self.directory / name
        report = self.parity.export_suite(
            unittest.TestSuite([case]), directory, stream=io.StringIO(),
        )
        return directory, report

    def check(self, directory):
        return subprocess.run(
            [str(self.binary), str(directory / "corpus.parity")],
            text=True, capture_output=True,
        )

    def test_real_python_car_positions_and_regression_assertions_pass_in_cpp(self):
        class DrivingRegression(unittest.TestCase):
            def runTest(self):
                from city import CityMap, Terrain
                from traffic_testbed import TestTrafficSimulation
                city = CityMap(terrain=Terrain(trees=[]))
                city.add_road([(0, 0), (100, 0), (150, 50)])
                traffic = TestTrafficSimulation(spawn_interval=1000)
                car = traffic.spawn_car(city, *city.cul_de_sacs)
                self.assertIsNotNone(car)
                self.assertEqual(car.position, car.points[0])
                for _ in range(6):
                    traffic.update(city, 0.05)
                self.assertGreater(car.distance, 0)
                self.assertGreaterEqual(car.speed, 0)
                self.assertAlmostEqual(sum(h*h for h in car.heading), 1)

        directory, report = self.export(DrivingRegression(), "drive")
        result = self.check(directory)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertGreater(report["motion_samples"], 0)
        self.assertGreaterEqual(report["native_assertions"], 5)
        self.assertEqual(report["python"]["failures"], [])

    def test_cpp_rejects_a_corrupted_numeric_regression_operand(self):
        class SpeedRegression(unittest.TestCase):
            def runTest(self):
                self.assertLessEqual(3.0, 3.0)
        directory, _ = self.export(SpeedRegression(), "bad-speed")
        trace = directory / "corpus.parity"
        source = trace.read_text()
        self.assertIn("f 3.0 f 3.0", source)
        trace.write_text(source.replace("f 3.0 f 3.0", "f 30.0 f 3.0", 1))
        result = self.check(directory)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("assertLessEqual", result.stderr)

    def test_cpp_rejects_a_corrupted_car_position(self):
        class PositionRegression(unittest.TestCase):
            def runTest(self):
                from city import CityMap, Terrain
                from traffic_testbed import TestTrafficSimulation
                city = CityMap(terrain=Terrain(trees=[]))
                city.add_road([(0, 0), (100, 0)])
                traffic = TestTrafficSimulation()
                car = traffic.spawn_car(city, *city.cul_de_sacs)
                car.advance(0.1)
                self.assertGreater(car.distance, 0)
        directory, _ = self.export(PositionRegression(), "bad-position")
        trace = directory / "corpus.parity"
        lines = trace.read_text().splitlines()
        for index, line in enumerate(lines):
            if line.startswith("P "):
                fields = line.split()
                fields[10] = str(float(fields[10]) + 1)
                lines[index] = " ".join(fields)
                break
        else:
            self.fail("Exporter did not include vehicle positions")
        trace.write_text("\n".join(lines) + "\n")
        result = self.check(directory)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("position", result.stderr)

    def test_python_failures_and_skips_remain_visible(self):
        class FailingRegression(unittest.TestCase):
            def runTest(self):
                self.assertEqual(1, 2)
        directory, report = self.export(FailingRegression(), "failure")
        self.assertEqual(len(report["python"]["failures"]), 1)
        self.assertNotEqual(self.check(directory).returncode, 0)

        class SkippedRegression(unittest.TestCase):
            @unittest.skip("optional renderer")
            def runTest(self):
                pass
        directory, report = self.export(SkippedRegression(), "skip")
        self.assertEqual(len(report["python"]["skipped"]), 1)
        self.assertEqual(report["native_assertions"], 0)
        self.assertNotEqual(self.check(directory).returncode, 0, "Empty corpus must not pass")

    def test_unsupported_object_checks_are_accounted_for(self):
        class ObjectRegression(unittest.TestCase):
            def runTest(self):
                self.assertIsInstance(object(), object)
                self.assertEqual([1, 2], [1, 2])
                with self.assertRaises(ValueError):
                    raise ValueError("expected")
        directory, report = self.export(ObjectRegression(), "objects")
        self.assertEqual(report["native_assertions"], 1)
        self.assertEqual(report["python_only_assertions"], 2)
        self.assertEqual(self.check(directory).returncode, 0)

    def test_typed_containers_and_tolerances_preserve_assertion_semantics(self):
        class OperandRegression(unittest.TestCase):
            def runTest(self):
                self.assertEqual({"speed": [1, 2.0]}, {"speed": [1.0, 2]})
                self.assertEqual({"a", "b"}, {"b", "a"})
                self.assertNotEqual([1], (1,))
                self.assertCountEqual([1, 1, 2], [2, 1, 1])
                self.assertIn("turn", "right turn")
                self.assertNotIn(2, {"a": 1})
                self.assertTrue([1])
                self.assertFalse([])
                self.assertIsNone(None)
                self.assertAlmostEqual(0.1 + 0.2, 0.3)
                self.assertAlmostEqual(1, 1.01, delta=0.02)
                self.assertAlmostEqual(1, 1.001, places=2)
                self.assertEqual("newline\n\" and \\ 🩵", "newline\n\" and \\ 🩵")
        directory, report = self.export(OperandRegression(), "operands")
        self.assertEqual(report["native_assertions"], 13)
        result = self.check(directory)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_checker_rejects_truncated_and_unknown_records(self):
        class GoodRegression(unittest.TestCase):
            def runTest(self):
                self.assertEqual(1, 1)
        directory, _ = self.export(GoodRegression(), "malformed")
        trace = directory / "corpus.parity"
        original = trace.read_text()
        for content in ("", original + "UNKNOWN\n", original + "P broken\n",
                        "\n".join(original.splitlines()[:-1]) + "\n"):
            trace.write_text(content)
            self.assertNotEqual(self.check(directory).returncode, 0, repr(content))

    def test_export_restores_hooks_after_execution(self):
        from traffic_testbed import RoutedRoadVehicle
        advance = RoutedRoadVehicle.advance
        assertion = unittest.TestCase.assertEqual
        class SmallRegression(unittest.TestCase):
            def runTest(self):
                self.assertEqual(1, 1)
        self.export(SmallRegression(), "restoration")
        self.assertIs(unittest.TestCase.assertEqual, assertion)
        self.assertIs(RoutedRoadVehicle.advance, advance)

    def test_cpp_uses_python_rounding_at_a_decimal_half_boundary(self):
        class RoundingRegression(unittest.TestCase):
            def runTest(self):
                self.assertAlmostEqual(0.004, 0.0, places=2)
        directory, _ = self.export(RoundingRegression(), "rounding-boundary")
        trace = directory / "corpus.parity"
        trace.write_text(trace.read_text().replace("f 0.004 f 0.0", "f 0.005 f 0.0"))
        # Python's binary 0.005 rounds to 0.01 at two places. Scaling by 100
        # before nearbyint would erase that distinction and falsely pass.
        with self.assertRaises(AssertionError):
            self.assertAlmostEqual(0.005, 0.0, places=2)
        self.assertNotEqual(self.check(directory).returncode, 0)

    def test_cpp_count_equal_checks_string_character_counts(self):
        class CountRegression(unittest.TestCase):
            def runTest(self):
                self.assertCountEqual("aba", "aab")
        directory, _ = self.export(CountRegression(), "string-counts")
        trace = directory / "corpus.parity"
        trace.write_text(trace.read_text().replace("s 616261 s 616162", "s 616262 s 616162"))
        self.assertNotEqual(self.check(directory).returncode, 0)

    def test_sequence_equal_preserves_python_cross_container_comparison(self):
        class SequenceRegression(unittest.TestCase):
            def runTest(self):
                self.assertSequenceEqual([1, 2], (1, 2))
                self.assertSequenceEqual([1], [1], seq_type=list)
                self.assertEqual(1, 1)
        directory, report = self.export(SequenceRegression(), "sequence-types")
        self.assertTrue(report["python"]["successful"])
        result = self.check(directory)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_expected_failures_remain_python_only_and_do_not_fail_native_replay(self):
        class KnownFailure(unittest.TestCase):
            @unittest.expectedFailure
            def runTest(self):
                self.assertEqual(1, 2)
        class GoodRegression(unittest.TestCase):
            def runTest(self):
                self.assertEqual(1, 1)
        self.assertIsNotNone(self.parity, "Python-to-C++ regression exporter is missing")
        directory = self.directory / "expected-failure"
        report = self.parity.export_suite(
            unittest.TestSuite([KnownFailure(), GoodRegression()]), directory,
            stream=io.StringIO(),
        )
        self.assertTrue(report["python"]["successful"])
        self.assertEqual(report["native_assertions"], 1)
        self.assertEqual(report["python_only_assertions"], 1)
        result = self.check(directory)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_baseline_export_does_not_replay_intentional_native_comparator_failures(self):
        class NativeHarness(unittest.TestCase):
            def id(self):
                return 'test_native_parity_extended.NativeExtendedParityTests.test_corruption'
            def runTest(self):
                with self.assertRaises(AssertionError):
                    self.assertEqual(1, 2)
        class OriginalRegression(unittest.TestCase):
            def id(self):
                return 'test_car_brain.OriginalRegression.test_stop'
            def runTest(self):
                self.assertEqual(1, 1)
        self.assertIsNotNone(self.parity)
        directory = self.directory / 'exclude-native-harness'
        suite = self.parity.without_harness(unittest.TestSuite([
            OriginalRegression(), NativeHarness(),
        ]))
        report = self.parity.export_suite(suite, directory, stream=io.StringIO())
        self.assertEqual(report['python']['tests_run'], 1)
        self.assertEqual(self.check(directory).returncode, 0)
