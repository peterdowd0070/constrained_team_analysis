"""Exact 216-state Markov run engine, with nine-inning lineup continuation."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from scipy.linalg import solve
from .events import Event,Hitter
from .advancement import AdvancementKernel
from .state import N_STATES,index,unpack

@dataclass(frozen=True)
class ExpectedRuns:
    total: float
    per_inning: tuple[float,...]
    leadoff_distributions: np.ndarray
    inning_value: np.ndarray
    next_leadoff: np.ndarray
    @property
    def per_game(self): return self.total

def transition_matrices(lineup: list[Hitter], kernel: AdvancementKernel|None=None):
    if len(lineup) != 9: raise ValueError("Need exactly nine hitters")
    kernel = kernel or AdvancementKernel()
    q = np.zeros((N_STATES,N_STATES))
    end = np.zeros((N_STATES,9))
    rewards = np.zeros(N_STATES)
    for s in range(N_STATES):
        outs,bases,slot = unpack(s)
        nxt = (slot+1)%9
        for event in Event:
            p = lineup[slot].probability(event)
            if p == 0: continue
            for t in kernel.outcomes(event,outs,bases):
                mass = p*t.probability
                rewards[s] += mass*t.runs
                if t.outs == 3:
                    end[s,nxt] += mass
                else:
                    q[s,index(t.outs,t.bases,nxt)] += mass
    if not np.allclose(q.sum(axis=1)+end.sum(axis=1),1,atol=1e-8):
        raise ValueError("Invalid transition probabilities")
    return q,end,rewards

def evaluate_lineup(lineup: list[Hitter], kernel: AdvancementKernel|None=None,
                    innings: int=9, start_batter: int=0) -> ExpectedRuns:
    if innings < 1 or not 0 <= start_batter < 9: raise ValueError("Invalid game settings")
    q,end,rewards = transition_matrices(lineup,kernel)
    try:
        solved = solve(np.eye(N_STATES)-q,np.column_stack((rewards,end)),
                       assume_a="gen",check_finite=False)
    except np.linalg.LinAlgError as exc:
        raise ValueError("Nonterminating/singular inning process") from exc
    v,f = solved[:,0],solved[:,1:]
    ids = np.array([index(0,0,k) for k in range(9)])
    values = v[ids]
    inning_end = f[ids,:]
    probs = np.zeros(9); probs[start_batter] = 1
    starts = [probs.copy()]
    runs = []
    for _ in range(innings):
        runs.append(float(probs@values))
        probs = probs@inning_end
        starts.append(probs.copy())
    return ExpectedRuns(float(sum(runs)),tuple(runs),np.stack(starts),v,f)

def remaining_inning_runs(fitted: ExpectedRuns,outs: int,bases: int,next_batter: int):
    return float(fitted.inning_value[index(outs,bases,next_batter)])
