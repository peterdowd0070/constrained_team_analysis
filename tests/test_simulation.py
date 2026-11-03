import pytest
from pathlib import Path
from baseball_run_engine.events import Event,Hitter
from baseball_run_engine.markov import evaluate_lineup
from baseball_run_engine.monte_carlo import simulate_games
from baseball_run_engine.optimize import optimize_lineup,select_budget_roster
from baseball_run_engine.projections import read_projection_csv

def test_monte_carlo():
    p=tuple(.75 if e==Event.K else .25 if e==Event.HR else 0 for e in Event)
    lineup=[Hitter(str(i),p) for i in range(9)]
    exact=evaluate_lineup(lineup).total
    sim=simulate_games(lineup,games=3000,seed=2026)
    assert abs(sim.mean-exact)<5*sim.standard_error+.07

def test_optimize():
    hitters=read_projection_csv(Path(__file__).parents[1]/'examples/fictional_projections.csv')[:9]
    original=evaluate_lineup(hitters).total
    result=optimize_lineup(hitters,restarts=0,max_passes=1)
    assert result.expected_runs>=original-1e-9

def test_budget():
    players=read_projection_csv(Path(__file__).parents[1]/'examples/fictional_projections.csv')
    result=select_budget_roster(players,65000000,max_rounds=1,shortlist=2)
    assert len(result.lineup)==9
    assert sum(x.salary for x in result.lineup)<=65000000
