"""Inputs for future commute-mode choice; no active selector is installed.

Profiles are neutral by default. Parking observations are bounded and queried
by home/work pair and simulated day, so today's trouble is only available to a
future day's choice. Keeping this event-driven avoids resident scans per tick.
"""
from collections import deque
from dataclasses import asdict, dataclass
from math import isfinite


HISTORY_DAYS = 14
PARKING_REASONS = frozenset(('full', 'inaccessible', 'overflow', 'walk_access'))


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError('Invalid ' + label)


def _trip(home, workplace, day):
    _number(day, 'commute day')
    if not all(isinstance(v, str) and v for v in (home, workplace)):
        raise ValueError('Invalid commute endpoints')


@dataclass(frozen=True)
class ModePreferences:
    """Relative mode weights reserved for a future selector; currently inert."""
    car: float = 1.
    walk: float = 1.
    transit: float = 1.

    def __post_init__(self):
        values = (self.car, self.walk, self.transit)
        if (any(isinstance(v, bool) or not isinstance(v, (int, float))
                or not isfinite(v) or v < 0 for v in values) or not any(values)):
            raise ValueError('Mode weights must be finite, nonnegative and not all zero')


@dataclass(frozen=True)
class ParkingExperience:
    day: int
    home: str
    workplace: str
    reason: str


class CommutePreferences:
    def __init__(self):
        self._profiles = {}
        self._parking = {}

    def profile(self, person):
        _number(person, 'resident ID')
        if person not in self._profiles:
            self._profiles[person] = ModePreferences()
        return self._profiles[person]

    def set_profile(self, person, preferences):
        _number(person, 'resident ID')
        if not isinstance(preferences, ModePreferences):
            raise ValueError('Expected mode preferences')
        self._profiles[person] = preferences

    def record_parking(self, person, *, home, workplace, day, reason):
        _number(person, 'resident ID')
        _trip(home, workplace, day)
        if reason not in PARKING_REASONS:
            raise ValueError('Invalid parking experience reason')
        rows = self._parking.get(person)
        if rows and day < rows[-1].day:
            raise ValueError('Parking observations cannot move backward')
        if rows:
            for row in reversed(rows):
                if (row.day, row.home, row.workplace) == (day, home, workplace):
                    return row
        else:
            rows = self._parking[person] = deque(maxlen=HISTORY_DAYS)
        while rows and rows[0].day < day - HISTORY_DAYS + 1:
            rows.popleft()
        row = ParkingExperience(day, home, workplace, reason)
        rows.append(row)
        self.profile(person)
        return row

    def prior_parking(self, person, *, home, workplace, day):
        _number(person, 'resident ID')
        _trip(home, workplace, day)
        return tuple(row for row in self._parking.get(person, ())
                     if day - HISTORY_DAYS <= row.day < day
                     and (row.home, row.workplace) == (home, workplace))

    def to_dict(self):
        return dict(schema=1,
                    profiles=[dict(person=pid, weights=asdict(profile))
                              for pid, profile in sorted(self._profiles.items())],
                    parking=[dict(person=pid, **asdict(row))
                             for pid, rows in sorted(self._parking.items()) for row in rows])

    @classmethod
    def from_dict(cls, data, *, resident_ids=None, max_day=None):
        result = cls()
        try:
            if (not isinstance(data, dict) or type(data.get('schema', 1)) is not int
                    or data.get('schema', 1) != 1):
                raise ValueError('Invalid commute preferences schema')
            seen_profiles, seen_parking, counts = set(), set(), {}
            for info in data.get('profiles', []):
                pid = info['person']
                _number(pid, 'resident ID')
                if pid in seen_profiles or (resident_ids is not None and pid not in resident_ids):
                    raise ValueError('Invalid saved preference resident')
                seen_profiles.add(pid)
                result.set_profile(pid, ModePreferences(**info['weights']))
            for info in data.get('parking', []):
                pid = info['person']
                _number(pid, 'resident ID')
                _trip(info['home'], info['workplace'], info['day'])
                key = pid, info['day'], info['home'], info['workplace']
                counts[pid] = counts.get(pid, 0) + 1
                if (key in seen_parking or counts[pid] > HISTORY_DAYS
                        or (resident_ids is not None and pid not in resident_ids)
                        or (max_day is not None and info['day'] > max_day)):
                    raise ValueError('Invalid saved parking experience')
                seen_parking.add(key)
                result.record_parking(pid, home=info['home'], workplace=info['workplace'],
                                      day=info['day'], reason=info['reason'])
        except (KeyError, TypeError, OverflowError) as error:
            raise ValueError('Invalid saved commute preferences') from error
        return result
