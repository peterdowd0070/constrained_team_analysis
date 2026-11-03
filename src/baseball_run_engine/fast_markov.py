"""Sparse Markov evaluator for repeated lineup-order scoring.

Compiles the advancement kernel and caches conditional per-hitter transitions;
the reference dense solver remains available in markov.py.
"""
from __future__ import annotations
import numpy as np
from scipy.sparse import coo_matrix, eye
from scipy.sparse.linalg import splu
from .advancement import AdvancementKernel
from .events import Event, Hitter


def compile_advancement(kernel: AdvancementKernel | None = None):
    kernel = kernel if kernel is not None else AdvancementKernel()
    transition = np.zeros((8, 24, 24), dtype=float)
    end = np.zeros((8, 24), dtype=float)
    rewards = np.zeros((8, 24), dtype=float)
    for event in Event:
        for outs in range(3):
            for bases in range(8):
                s = 8*outs+bases
                for t in kernel.outcomes(event, outs, bases):
                    m = t.probability
                    if t.outs == 3: end[int(event),s] += m
                    else: transition[int(event),s,8*t.outs+t.bases] += m
                    rewards[int(event),s] += m*t.runs
    if not np.allclose(transition.sum(axis=2)+end, 1, atol=1e-8):
        raise ValueError("Invalid advancement kernel")
    return transition, end, rewards


class FastRunEngine:
    """Evaluate expected runs with sparse LU; exact up to floating-point error."""
    def __init__(self, kernel: AdvancementKernel | None = None, *,
                 innings: int = 9):
        if innings < 1: raise ValueError("Invalid innings")
        self.advance, self.end, self.rewards = compile_advancement(kernel)
        self.innings = innings
        self._cache = {}

    def _hitter(self, hitter: Hitter):
        key = tuple(hitter.probabilities)
        if key not in self._cache:
            p = np.asarray(key, dtype=float)
            self._cache[key] = (
                np.einsum("e,est->st", p, self.advance),
                np.einsum("e,es->s", p, self.end),
                np.einsum("e,es->s", p, self.rewards),
            )
        return self._cache[key]

    def score(self, lineup: list[Hitter] | tuple[Hitter,...],
              start_batter: int = 0) -> float:
        if len(lineup) != 9 or not 0 <= start_batter < 9:
            raise ValueError("Nine hitters required")
        tables = [self._hitter(h) for h in lineup]
        rr=[]; cc=[]; vv=[]
        end=np.zeros((216,9),dtype=float)
        runs=np.empty(216,dtype=float)
        for k,(mat,terminal,reward) in enumerate(tables):
            a,b=np.nonzero(mat)
            rr.extend((a+24*k).tolist())
            cc.extend((b+24*((k+1)%9)).tolist())
            vv.extend(mat[a,b].tolist())
            end[24*k:24*(k+1),(k+1)%9]=terminal
            runs[24*k:24*(k+1)]=reward
        q=coo_matrix((vv,(rr,cc)),shape=(216,216)).tocsc()
        try:
            solution=splu(eye(216,format="csc")-q).solve(np.column_stack((runs,end)))
        except RuntimeError as exc:
            raise ValueError("Nonterminating inning process") from exc
        starts=np.arange(9)*24
        values=solution[starts,0]
        continuation=solution[starts,1:]
        probs=np.zeros(9); probs[start_batter]=1.
        total=0.
        for _ in range(self.innings):
            total+=float(probs @ values)
            probs=probs @ continuation
        return total
