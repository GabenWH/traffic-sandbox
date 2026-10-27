"""Reusing derived state must not hide source changes or partial mutations."""

import unittest

from simulation_cache import (
    CachedValue,
    CacheCycleError,
    CacheReadError,
    MutationNotAllowedError,
    RevisionSource,
    UndeclaredDependencyError,
)


class SimulationCacheTests(unittest.TestCase):
    def test_lazy_value_reuses_object_until_source_changes(self):
        source = RevisionSource("route")
        route = ["a"]
        builds = []

        def build():
            builds.append(tuple(route))
            return tuple(route)

        cached = CachedValue("route facts", dependencies=(source,), build=build)
        self.assertEqual(builds, [])
        first = cached.get()
        for _ in range(100):
            self.assertIs(cached.get(), first)
        with source.mutate():
            route.append("b")
        self.assertEqual(builds, [("a",)])
        self.assertEqual(cached.get(), ("a", "b"))
        self.assertEqual(builds, [("a",), ("a", "b")])
        self.assertEqual(cached.info().builds, 2)
        self.assertEqual(cached.info().hits, 100)

    def test_none_is_a_cached_value(self):
        builds = []
        cached = CachedValue("missing route", dependencies=(),
                             build=lambda: builds.append(1))
        self.assertIsNone(cached.get())
        self.assertIsNone(cached.get())
        self.assertEqual(builds, [1])

    def test_unrelated_source_changes_do_not_rebuild(self):
        own, unrelated = RevisionSource("own"), RevisionSource("other")
        cached = CachedValue("facts", dependencies=(own,), build=object)
        first = cached.get()
        with unrelated.mutate():
            pass
        self.assertIs(cached.get(), first)
        self.assertEqual(cached.info().builds, 1)

    def test_independent_owner_stamps_do_not_compare_equal(self):
        old = RevisionSource("car-1")
        replacement = RevisionSource("car-1")
        self.assertNotEqual(old.stamp(), replacement.stamp())

    def test_nested_mutations_publish_one_revision_and_no_partial_read(self):
        source = RevisionSource("claims")
        original = source.stamp()
        state = []
        cached = CachedValue("claims", dependencies=(source,),
                             build=lambda: tuple(state))
        cached.get()
        with source.mutate():
            state.append("first")
            with source.mutate():
                state.append("second")
            with self.assertRaises(CacheReadError):
                cached.get()
        self.assertEqual(source.stamp().generation, original.generation + 1)
        self.assertEqual(cached.get(), ("first", "second"))

    def test_partial_mutation_failure_invalidates_old_value(self):
        source = RevisionSource("roster")
        state = ["first"]
        cached = CachedValue("roster", dependencies=(source,),
                             build=lambda: tuple(state))
        cached.get()
        with self.assertRaisesRegex(ValueError, "interrupted"):
            with source.mutate():
                state.append("second")
                raise ValueError("interrupted")
        self.assertEqual(cached.get(), ("first", "second"))

    def test_nested_read_only_scope_blocks_writes_before_body_runs(self):
        source = RevisionSource("poses")
        state = []
        original = source.stamp()
        with source.read_only():
            with source.read_only():
                with self.assertRaises(MutationNotAllowedError):
                    with source.mutate():
                        state.append("partial write")
            with self.assertRaises(MutationNotAllowedError):
                with source.mutate():
                    state.append("partial write")
        self.assertEqual(state, [])
        self.assertEqual(source.stamp(), original)
        with source.mutate():
            state.append("published")
        self.assertEqual(state, ["published"])

    def test_cannot_open_read_phase_during_mutation(self):
        source = RevisionSource("poses")
        with source.mutate():
            with self.assertRaises(CacheReadError):
                with source.read_only():
                    self.fail("partial state became readable")

    def test_builder_cannot_mutate_even_an_unrelated_source(self):
        source, unrelated = RevisionSource("route"), RevisionSource("other")
        changed = []

        def build():
            with unrelated.mutate():
                changed.append(True)

        cached = CachedValue("route", dependencies=(source,), build=build)
        with self.assertRaises(MutationNotAllowedError):
            cached.get()
        self.assertEqual(changed, [])

    def test_failed_builder_does_not_return_old_value_and_can_recover(self):
        source = RevisionSource("route")
        state = {"route": "old"}

        def build():
            if state["route"] == "broken":
                raise ValueError("bad route")
            return state["route"]

        cached = CachedValue("route", dependencies=(source,), build=build)
        self.assertEqual(cached.get(), "old")
        with source.mutate():
            state["route"] = "broken"
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, "bad route"):
                cached.get()
        with source.mutate():
            state["route"] = "new"
        self.assertEqual(cached.get(), "new")
        self.assertEqual(cached.info().failed_builds, 2)

    def test_builder_cannot_clear_another_cached_value(self):
        other = CachedValue("other", dependencies=(), build=object)
        saved = other.get()
        cached = CachedValue("impure", dependencies=(), build=other.clear)
        with self.assertRaises(MutationNotAllowedError):
            cached.get()
        self.assertIs(other.get(), saved)

    def test_cycle_raises_and_unwinds_build_guard(self):
        source = RevisionSource("route")
        cached = CachedValue("cycle", dependencies=(source,),
                             build=lambda: cached.get())
        with self.assertRaises(CacheCycleError):
            cached.get()
        with source.mutate():
            pass

    def test_composed_cache_refreshes_without_reading_inner_first(self):
        source = RevisionSource("topology")
        state = [1]
        inner = CachedValue("inner", dependencies=(source,),
                            build=lambda: state[0])
        outer = CachedValue("outer", dependencies=inner.dependencies,
                            build=lambda: inner.get() * 2)
        self.assertEqual(outer.get(), 2)
        with source.mutate():
            state[0] = 3
        self.assertEqual(outer.get(), 6)

    def test_undeclared_inner_dependency_is_rejected_on_inner_cache_hit(self):
        source = RevisionSource("topology")
        inner = CachedValue("inner", dependencies=(source,), build=lambda: 1)
        inner.get()
        outer = CachedValue("outer", dependencies=(), build=inner.get)
        with self.assertRaises(UndeclaredDependencyError):
            outer.get()

    def test_undeclared_direct_revision_read_is_rejected(self):
        source = RevisionSource("topology")
        cached = CachedValue("untracked", dependencies=(), build=source.stamp)
        with self.assertRaises(UndeclaredDependencyError):
            cached.get()

    def test_clear_releases_value_and_rebuilds_without_changing_source(self):
        source = RevisionSource("route")
        cached = CachedValue("facts", dependencies=(source,), build=object)
        first = cached.get()
        original = source.stamp()
        cached.clear()
        self.assertIsNot(cached.get(), first)
        self.assertEqual(source.stamp(), original)


if __name__ == "__main__":
    unittest.main()
