"""Regression tests for sparse run evaluator and lineup presentation."""
import pytest
from pathlib import Path
from baseball_run_engine.projections import read_projection_csv
from baseball_run_engine.markov import evaluate_lineup
from baseball_run_engine.fast_markov import FastRunEngine
from baseball_run_engine.optimize import optimize_lineup
from baseball_run_engine.ui_components import lineup_card, batting_line

FIXTURE=Path(__file__).parents[1]/"examples"/"fictional_projections.csv"

def test_sparse_matches_reference():
    lineup=read_projection_csv(FIXTURE)[:9]
    exact=evaluate_lineup(lineup).total
    assert FastRunEngine().score(lineup)==pytest.approx(exact,abs=1e-8)

def test_sparse_swap():
    lineup=read_projection_csv(FIXTURE)[:9]
    swapped=lineup.copy()
    swapped[0],swapped[5]=swapped[5],swapped[0]
    assert FastRunEngine().score(swapped)==pytest.approx(evaluate_lineup(swapped).total,abs=1e-8)

def test_optimizer_fast_score():
    lineup=read_projection_csv(FIXTURE)[:9]
    best=optimize_lineup(lineup,restarts=0,max_passes=2)
    assert best.expected_runs >= evaluate_lineup(lineup).total - 1e-8

def test_lineup_card_escapes_names():
    from baseball_run_engine.events import Hitter
    lineup=read_projection_csv(FIXTURE)[:9]
    p=lineup[0]
    lineup[0]=Hitter("<img src=x>",p.probabilities,p.salary,p.positions)
    markup=lineup_card(lineup)
    assert "<img" not in markup
    assert "&lt;img" in markup
    assert len(lineup)==9

def test_batting_line_bounds():
    for player in read_projection_csv(FIXTURE)[:9]:
        rates=batting_line(player)
        assert 0 <= rates["AVG"] <= 1
        assert 0 <= rates["OBP"] <= 1
