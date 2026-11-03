"""Monte Carlo verification of the exact expected-runs solver."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from .events import Event,Hitter
from .advancement import AdvancementKernel

@dataclass(frozen=True)
class SimulationResult:
    runs: np.ndarray
    @property
    def mean(self): return float(self.runs.mean())
    @property
    def standard_error(self):
        return float(self.runs.std(ddof=1)/np.sqrt(len(self.runs))) if len(self.runs)>1 else float("nan")
    @property
    def quantiles(self): return {str(int(100*q)):float(np.quantile(self.runs,q)) for q in (0.05,0.5,0.95)}

def simulate_games(lineup: list[Hitter],games: int=10000,innings: int=9,
                   seed: int=2026,kernel: AdvancementKernel|None=None,
                   max_pas_per_inning: int=1000) -> SimulationResult:
    if len(lineup)!=9 or games<=0 or innings<=0: raise ValueError("Invalid simulation settings")
    kernel = kernel or AdvancementKernel()
    rng = np.random.default_rng(seed)
    runs = np.zeros(games,dtype=np.int32)
    for game in range(games):
        slot = 0
        for _ in range(innings):
            outs=bases=0
            for _ in range(max_pas_per_inning):
                event = Event(rng.choice(8,p=lineup[slot].probabilities))
                transitions = kernel.outcomes(event,outs,bases)
                probs = [t.probability for t in transitions]
                t = transitions[int(rng.choice(len(transitions),p=probs))]
                runs[game] += t.runs
                outs,bases = t.outs,t.bases
                slot = (slot+1)%9
                if outs==3: break
            else:
                raise RuntimeError("Nonterminating inning")
    return SimulationResult(runs)
