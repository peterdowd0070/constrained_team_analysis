import pytest
from pathlib import Path
from baseball_run_engine.projections import from_projection_row,read_projection_csv
from baseball_run_engine.events import Event

def test_probabilities():
    h=from_projection_row({'Name':'Test','PA':'100','H':'25','2B':'5',
                           '3B':'1','HR':'4','BB':'15','SO':'20'})
    assert h.probability(Event.SINGLE)==pytest.approx(.15)
    assert h.probability(Event.OUT)==pytest.approx(.40)
    assert sum(h.probabilities)==pytest.approx(1)

def test_fixture():
    players=read_projection_csv(Path(__file__).parents[1]/'examples/fictional_projections.csv')
    assert len(players)==12
    assert players[0].salary>0

def test_bad_counts():
    with pytest.raises(ValueError):
        from_projection_row({'Name':'Bad','PA':'10','H':'10','2B':'7',
                             '3B':'5','HR':'1','BB':'4','SO':'3'})
