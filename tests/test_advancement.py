import pytest
from baseball_run_engine.advancement import AdvancementKernel,Transition,default_transition
from baseball_run_engine.events import Event

def test_walk_force():
    assert default_transition(Event.BB,0,0)==Transition(0,1,0)
    assert default_transition(Event.BB,0,1)==Transition(0,3,0)
    assert default_transition(Event.BB,0,3)==Transition(0,7,0)
    assert default_transition(Event.BB,0,7)==Transition(0,7,1)

def test_hits():
    assert default_transition(Event.SINGLE,1,7)==Transition(1,7,1)
    assert default_transition(Event.DOUBLE,1,7)==Transition(1,6,2)
    assert default_transition(Event.TRIPLE,1,7)==Transition(1,4,3)
    assert default_transition(Event.HR,1,7)==Transition(1,0,4)

def test_empirical_roundtrip(tmp_path):
    c={(int(Event.OUT),0,1,2,0,0):3}
    kernel=AdvancementKernel.from_counts(c,prior_strength=2)
    ts=kernel.outcomes(Event.OUT,0,1)
    assert len(ts)==2
    assert sum(t.probability for t in ts)==pytest.approx(1)
    path=tmp_path/'kernel.json'
    kernel.save(path)
    assert AdvancementKernel.load(path).outcomes(Event.OUT,0,1)==ts
