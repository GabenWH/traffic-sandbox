"""Lazy derived values with explicit revisions and guarded source mutations.

Owners declare the root sources for each value and perform changes inside
``source.mutate()``. This module does not detect arbitrary in-place mutations.
Builders should return immutable data or read-only views. All access belongs to
the simulation thread; ``read_only()`` is a phase guard, not a thread lock.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Generic, Iterator, TypeVar, cast


T = TypeVar("T")
_MISSING = object()
_BUILD_STACK: ContextVar[tuple[CachedValue[Any], ...]] = ContextVar(
    "simulation_cache_builds", default=(),
)


class CacheError(RuntimeError):
    """An operation would violate the cache's source or evaluation contract."""


class MutationNotAllowedError(CacheError):
    """A write was attempted during observation or cached computation."""


class CacheReadError(CacheError):
    """A read was attempted against incomplete or changing source state."""


class CacheCycleError(CacheError):
    """A cached computation recursively depends on itself."""


class UndeclaredDependencyError(CacheError):
    """A computation reads a revision outside its declared root sources."""


@dataclass(frozen=True)
class RevisionStamp:
    source_token: object
    generation: int


@dataclass(frozen=True)
class CacheInfo:
    hits: int
    builds: int
    failed_builds: int


class RevisionSource:
    """A source owned by one system, changed only through its mutation API."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._stamp = RevisionStamp(object(), 0)
        self._write_depth = 0
        self._read_depth = 0

    def stamp(self) -> RevisionStamp:
        """Return the retained immutable stamp, rejecting partial reads."""
        if self._write_depth:
            raise CacheReadError(f"{self.name!r} is being mutated")
        for parent in _BUILD_STACK.get():
            if self not in parent.dependencies:
                raise UndeclaredDependencyError(
                    f"{parent.name!r} does not declare source {self.name!r}",
                )
        return self._stamp

    @contextmanager
    def mutate(self) -> Iterator[None]:
        """Invalidate on exit, including failure; nested scopes coalesce.

        This does not undo a failed mutation. The owner is responsible for
        validating or recovering its state before allowing the simulation on.
        Check for an effective change before entering to avoid no-op revisions.
        """
        if _BUILD_STACK.get():
            raise MutationNotAllowedError("Cache builders cannot mutate sources")
        if self._read_depth:
            raise MutationNotAllowedError(f"{self.name!r} is in a read phase")
        self._write_depth += 1
        try:
            yield
        finally:
            self._write_depth -= 1
            if not self._write_depth:
                self._stamp = RevisionStamp(
                    self._stamp.source_token, self._stamp.generation + 1,
                )

    @contextmanager
    def read_only(self) -> Iterator[None]:
        """Prevent this source's owner from mutating it during observation."""
        if self._write_depth:
            raise CacheReadError(f"{self.name!r} is being mutated")
        self._read_depth += 1
        try:
            yield
        finally:
            self._read_depth -= 1


class CachedValue(Generic[T]):
    """Keep one current value; rebuild lazily when a declared source changes.

    Composed caches must declare the union of their inner caches' root sources.
    This is checked on nested reads, even when an inner read is a cache hit.
    No registration, invalidation sweep, or eager callback runs on a mutation.
    """

    def __init__(
        self, name: str, *, dependencies: tuple[RevisionSource, ...],
        build: Callable[[], T],
    ) -> None:
        self.name = name
        self._dependencies = tuple(dict.fromkeys(dependencies))
        self._dependency_set = frozenset(self._dependencies)
        self._build = build
        self._stamps: tuple[RevisionStamp, ...] | None = None
        self._value: T | object = _MISSING
        self._hits = self._builds = self._failed_builds = 0

    @property
    def dependencies(self) -> tuple[RevisionSource, ...]:
        return self._dependencies

    def get(self) -> T:
        stack = _BUILD_STACK.get()
        if self in stack:
            raise CacheCycleError(f"Cyclic evaluation of {self.name!r}")
        for parent in stack:
            if not self._dependency_set <= parent._dependency_set:
                raise UndeclaredDependencyError(
                    f"{parent.name!r} omits root sources of {self.name!r}",
                )
        if len(self._dependencies) == 1:
            stamp = self._dependencies[0].stamp()
            if (self._value is not _MISSING and self._stamps is not None
                    and stamp == self._stamps[0]):
                self._hits += 1
                return cast(T, self._value)
            stamps = (stamp,)
        else:
            stamps = tuple(source.stamp() for source in self._dependencies)
        if self._value is not _MISSING and stamps == self._stamps:
            self._hits += 1
            return cast(T, self._value)

        # Discard the invalid value before calling user code. Failed builders
        # cannot expose a previously valid result as a stale fallback.
        self._value, self._stamps = _MISSING, None
        token = _BUILD_STACK.set((*stack, self))
        try:
            value = self._build()
            if stamps != tuple(source.stamp() for source in self._dependencies):
                raise CacheReadError(f"Sources changed while building {self.name!r}")
        except BaseException:
            self._failed_builds += 1
            raise
        finally:
            _BUILD_STACK.reset(token)
        self._value, self._stamps = value, stamps
        self._builds += 1
        return value

    def clear(self) -> None:
        """Release this value without changing its sources or statistics."""
        if _BUILD_STACK.get():
            raise MutationNotAllowedError("Cache builders cannot clear caches")
        self._value, self._stamps = _MISSING, None

    def info(self) -> CacheInfo:
        return CacheInfo(self._hits, self._builds, self._failed_builds)
