"""Eight mutually exclusive MVP plate-appearance outcomes."""
from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum
import numpy as np


class Event(IntEnum):
    K = 0
    OUT = 1  # all non-strikeout outs, including sacrifices; MVP approximation
    BB = 2  # includes intentional walks
    HBP = 3
    SINGLE = 4
    DOUBLE = 5
    TRIPLE = 6
    HR = 7


EVENT_NAMES = tuple(e.name for e in Event)


@dataclass(frozen=True)
class Hitter:
    name: str
    probabilities: tuple[float, ...]
    salary: float = 0.0
    positions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        p = np.asarray(self.probabilities, dtype=float)
        if p.shape != (len(Event),) or not np.isfinite(p).all() or np.any(p < 0):
            raise ValueError(f"{self.name}: invalid probability vector {p}")
        if not np.isclose(p.sum(), 1, atol=1e-8):
            raise ValueError(f"{self.name}: probabilities sum to {p.sum()}, not 1")
        if not np.isfinite(self.salary) or self.salary < 0:
            raise ValueError(f"{self.name}: salary must be nonnegative")

    def probability(self, event: Event) -> float:
        return self.probabilities[int(event)]
