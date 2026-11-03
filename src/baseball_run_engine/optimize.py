"""Heuristic batting order and salary-only roster optimization.

Optimization is NOT guaranteed global. Positions and bench are future work.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from .events import Hitter
from .advancement import AdvancementKernel
from .fast_markov import FastRunEngine

@dataclass(frozen=True)
class OptimizationResult:
    lineup: tuple[Hitter,...]
    expected_runs: float
    evaluations: int

def optimize_lineup(hitters: list[Hitter],kernel: AdvancementKernel|None=None,
                    restarts: int=2,seed: int=42,innings: int=9,
                    max_passes: int=10) -> OptimizationResult:
    if len(hitters)!=9 or restarts<0: raise ValueError("Need nine hitters and nonnegative restarts")
    kernel = kernel or AdvancementKernel()
    rng = np.random.default_rng(seed)
    engine = FastRunEngine(kernel, innings=innings)
    cache = {}
    def score(order):
        key=tuple(order)
        if key not in cache:
            cache[key]=engine.score([hitters[i] for i in key])
        return cache[key]
    best=tuple(range(9)); best_value=score(best)
    for restart in range(restarts+1):
        order=list(best) if restart==0 else list(rng.permutation(9))
        value=score(order)
        for _ in range(max_passes):
            candidate=None; candidate_value=value
            for i in range(8):
                for j in range(i+1,9):
                    alt=order.copy(); alt[i],alt[j]=alt[j],alt[i]
                    v=score(alt)
                    if v>candidate_value+1e-10:
                        candidate,candidate_value=alt,v
            if candidate is None: break
            order,value=candidate,candidate_value
        if value>best_value:
            best,best_value=tuple(order),value
    return OptimizationResult(tuple(hitters[i] for i in best),best_value,len(cache))

def select_budget_roster(pool: list[Hitter],budget: float,
                         kernel: AdvancementKernel|None=None,seed: int=42,
                         max_rounds: int=3,shortlist: int=4) -> OptimizationResult:
    if len(pool)<9 or budget<0 or shortlist<1: raise ValueError("Invalid roster inputs")
    if len({p.name for p in pool}) != len(pool): raise ValueError("Duplicate player names")
    kernel = kernel or AdvancementKernel()
    engine = FastRunEngine(kernel)
    chosen=sorted(pool,key=lambda p:p.salary)[:9]
    if sum(p.salary for p in chosen)>budget+1e-9:
        raise ValueError("No feasible nine-hitter roster")
    evaluations=0
    def evaluate(roster):
        nonlocal evaluations
        evaluations+=1
        return engine.score(roster)
    def refine(roster):
        nonlocal evaluations
        res=optimize_lineup(roster,kernel,restarts=0,seed=seed,max_passes=5)
        evaluations+=res.evaluations
        return res
    best=refine(chosen)
    for _ in range(max_rounds):
        proposals=[]
        present={p.name for p in best.lineup}
        cost=sum(p.salary for p in best.lineup)
        for slot,player in enumerate(best.lineup):
            for sub in pool:
                if sub.name in present: continue
                if cost-player.salary+sub.salary>budget+1e-9: continue
                candidate=list(best.lineup); candidate[slot]=sub
                proposals.append((evaluate(candidate),candidate))
        if not proposals: break
        proposals.sort(key=lambda x:x[0],reverse=True)
        next_best=best
        for _,roster in proposals[:shortlist]:
            optimized=refine(roster)
            if optimized.expected_runs>next_best.expected_runs+1e-9: next_best=optimized
        if next_best.expected_runs<=best.expected_runs+1e-9: break
        best=next_best
    return OptimizationResult(best.lineup,best.expected_runs,evaluations)
