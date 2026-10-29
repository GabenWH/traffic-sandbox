"""Household identity and lazy housing memory; no movement-tick updates."""
from dataclasses import dataclass, field
from math import exp, isfinite

DAY = 86400.0
YEAR = 365 * DAY
MONTH = YEAR / 12


@dataclass
class HousingMemory:
    buffer: float = 40.0
    target: float = 40.0
    updated_at: float = 0.0

    def value_at(self, time):
        if not isfinite(time) or time < self.updated_at:
            raise ValueError('Housing memory requires finite monotonic time')
        return self.target + (self.buffer-self.target)*exp(-(time-self.updated_at)/(2*YEAR))

    def observe(self, satisfaction, time):
        self.buffer = self.value_at(time)
        self.updated_at = time
        self.target = 10 + .7*max(0, min(100, satisfaction))

    def moved(self, time):
        self.buffer, self.target, self.updated_at = 75.0, 75.0, time


@dataclass
class Household:
    id: str
    home: str
    members: list[int]
    memory: HousingMemory = field(default_factory=HousingMemory)
    moving_to: str | None = None
    arrived: list[int] = field(default_factory=list)
    cargo: dict = field(default_factory=dict)
    belongings: dict = field(default_factory=dict)
    last_score: float = 0.0
    meal_credit: float = 0.0
