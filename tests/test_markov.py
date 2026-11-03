import numpy as np
import pytest
from baseball_run_engine.events import Hitter,Event
from baseball_run_engine.markov import evaluate_lineup,transition_matrices
from baseball_run_engine.state import index,unpack

def h(name,p):
    return Hitter(name,tuple(float(p.get(e,0)) for e in Event))

def test_state_roundtrip():
    for k in range(9):
        for o in range(3):
            for b in range(8):
                assert unpack(index(o,b,k))==(o,b,k)

def test_all_outs():
    result=evaluate_lineup([h(str(k),{Event.K:1}) for k in range(9)])
    assert result.total==pytest.approx(0)
    assert result.leadoff_distributions[1,3]==pytest.approx(1)
    assert result.leadoff_distributions[-1,0]==pytest.approx(1)

def test_analytic_hr():
    # Three outs, 25% homer, 75% strikeout -> expected one HR per inning.
    res=evaluate_lineup([h(str(k),{Event.K:0.75,Event.HR:0.25}) for k in range(9)])
    assert res.total==pytest.approx(9,abs=1e-8)

def test_row_mass():
    q,end,reward=transition_matrices([h(str(k),{Event.K:.5,Event.BB:.25,Event.HR:.25}) for k in range(9)])
    assert np.allclose(q.sum(axis=1)+end.sum(axis=1),1)
    assert np.all(reward>=0)
