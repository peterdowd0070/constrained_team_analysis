"""Runner advancement kernels, separate from projection models."""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
from .events import Event

@dataclass(frozen=True)
class Transition:
    outs: int
    bases: int
    runs: int
    probability: float = 1.0
    def __post_init__(self):
        if not (0 <= self.outs <= 3 and 0 <= self.bases <= 7):
            raise ValueError("invalid bases/outs")
        if self.runs < 0 or not 0 <= self.probability <= 1:
            raise ValueError("invalid runs/probability")

def default_transition(event: Event, outs: int, bases: int) -> Transition:
    if not (0 <= outs <= 2 and 0 <= bases <= 7):
        raise ValueError((outs, bases))
    if event in (Event.K, Event.OUT):
        return Transition(outs + 1, bases if outs + 1 < 3 else 0, 0)
    if event in (Event.BB, Event.HBP):
        if not bases & 1:
            return Transition(outs, bases | 1, 0)
        if not bases & 2:
            return Transition(outs, bases | 2, 0)
        if not bases & 4:
            return Transition(outs, bases | 4, 0)
        return Transition(outs, bases, 1)
    if event == Event.HR:
        return Transition(outs, 0, 1 + bases.bit_count())
    if event == Event.TRIPLE:
        return Transition(outs, 4, bases.bit_count())
    if event == Event.DOUBLE:
        runs = int(bool(bases & 2)) + int(bool(bases & 4))
        return Transition(outs, 2 | (4 if bases & 1 else 0), runs)
    if event == Event.SINGLE:
        runs = int(bool(bases & 4))
        return Transition(outs, 1 | ((bases & 1) << 1) | ((bases & 2) << 1), runs)
    raise ValueError(event)

class AdvancementKernel:
    """Conditional transition distributions by (event, outs_before, bases_before)."""
    def __init__(self, observations: dict[tuple[int,int,int],list[Transition]] | None = None):
        self.observations = observations or {}
        for k, ts in self.observations.items():
            if not ts or abs(sum(t.probability for t in ts) - 1) > 1e-7:
                raise ValueError(f"Invalid kernel distribution {k}")
    def outcomes(self, event: Event, outs: int, bases: int) -> tuple[Transition,...]:
        return tuple(self.observations.get((int(event),outs,bases),
                                           [default_transition(event,outs,bases)]))
    @classmethod
    def from_counts(cls, counts: dict[tuple[int,int,int,int,int,int],float],
                    prior_strength: float=10.0) -> 'AdvancementKernel':
        if prior_strength < 0:
            raise ValueError("prior_strength < 0")
        groups = defaultdict(lambda: defaultdict(float))
        for (e,o,b,ot,bt,r),n in counts.items():
            if n < 0:
                raise ValueError("negative count")
            if n:
                groups[(e,o,b)][(ot,bt,r)] += n
        result = {}
        for key, group in groups.items():
            t = default_transition(Event(key[0]),key[1],key[2])
            group[(t.outs,t.bases,t.runs)] += prior_strength
            total = sum(group.values())
            result[key] = [Transition(*state,weight/total) for state,weight in sorted(group.items())]
        return cls(result)
    def save(self, path: str | Path) -> None:
        rows = [dict(event=e,outs=o,bases=b,next_outs=t.outs,next_bases=t.bases,
                     runs=t.runs,probability=t.probability)
                for (e,o,b),ts in sorted(self.observations.items()) for t in ts]
        Path(path).write_text(json.dumps({"schema_version":1,"transitions":rows},indent=2))
    @classmethod
    def load(cls, path: str | Path) -> 'AdvancementKernel':
        obj = json.loads(Path(path).read_text())
        if obj.get("schema_version") != 1:
            raise ValueError("Unsupported kernel schema")
        groups = defaultdict(list)
        for r in obj["transitions"]:
            groups[(int(r["event"]),int(r["outs"]),int(r["bases"]))].append(
                Transition(int(r["next_outs"]),int(r["next_bases"]),int(r["runs"]),
                           float(r["probability"])))
        return cls(dict(groups))
