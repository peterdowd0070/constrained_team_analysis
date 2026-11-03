"""Offline regression tests: salary joins and Streamlit callback timing."""
import csv
import json
from pathlib import Path
import pytest
from baseball_run_engine.gui import (
    _apply_optimized_order,_clear_lineup,_choose_player,resolve_lineup_names)
from baseball_run_engine.projections import read_projection_csv
from baseball_run_engine.salaries import (
    clean_name,clean_team,read_salary_csv,merge_salary_csv)

def write(path,rows):
    with path.open("w",newline="") as fh:
        writer=csv.DictWriter(fh,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    return path

def test_name_and_team_aliases():
    assert clean_name("José Ramírez [FG:7]")==clean_name("Jose Ramirez")
    assert clean_team("San Diego Padres")==clean_team("SDP")
    assert clean_team("Oakland Athletics")=="ATH"

def test_match_by_id_and_team(tmp_path):
    projections=write(tmp_path/"p.csv",[
        dict(Name="Jose Ramirez",FGID="42",Team="CLE",PA=550,H=130,
             **{"2B":20,"3B":2},HR=25,BB=60,SO=100),
        dict(Name="Juan Soto",FGID="61",Team="NYM",PA=600,H=160,
             **{"2B":30,"3B":1},HR=35,BB=105,SO=122),
        dict(Name="John Sample",FGID="62",Team="BOS",PA=450,H=100,
             **{"2B":20,"3B":1},HR=10,BB=52,SO=90)])
    salaries=write(tmp_path/"s.csv",[
        dict(player="José Ramírez",team="Cleveland Guardians",salary=25000000,FGID=42,season=2026),
        dict(player="Juan Soto",team="New York Mets",salary=61875000,FGID="",season=2026),
        dict(player="John Sample",team="New York Yankees",salary=1000000,FGID="",season=2026),
        dict(player="John Sample",team="Boston Red Sox",salary=2200000,FGID="",season=2026)])
    target=tmp_path/"out.csv"
    report=merge_salary_csv(projections,salaries,target,season=2026)
    assert report["matched_id"]==1
    assert report["matched_name_team"]==2
    assert [p.salary for p in read_projection_csv(target)]==[25000000,61875000,2200000]
    assert len(read_salary_csv(salaries,season=2026))==4
    with target.open() as fh: rows=list(csv.DictReader(fh))
    assert all(x["SalaryMatched"]=="true" for x in rows)
    assert json.loads(target.with_suffix(".salary-report.json").read_text())["matched_id"]==1

def test_ambiguous_names_not_priced(tmp_path):
    p=write(tmp_path/"p.csv",[dict(Name="John Sample",Team="",PA=300,H=100,
        **{"2B":20,"3B":1},HR=10,BB=40,SO=90)])
    s=write(tmp_path/"s.csv",[
        dict(Player="John Sample",Team="BOS",Salary=2000000),
        dict(Player="John Sample",Team="NYY",Salary=4000000)])
    target=tmp_path/"out.csv"
    report=merge_salary_csv(p,s,target)
    assert report["ambiguous"]==1
    assert read_projection_csv(target)[0].salary==0

def test_salary_season_filter(tmp_path):
    s=write(tmp_path/"salary.csv",[
        dict(Name="A",Salary=100,Season=2025),
        dict(Name="B",Salary=200,Season=2026)])
    assert len(read_salary_csv(s,season=2026))==1

def test_apply_order_before_widget_creation():
    names=[f"Batter {i}" for i in range(9)]
    state={"last_order":{"names":names},"last_result":{"runs":3}}
    _apply_optimized_order(state)
    assert [state[f"lineup_text_{i}"] for i in range(9)]==names
    assert "last_order" not in state
    _clear_lineup(state,0)
    assert state["lineup_text_0"]==""
    state["lineup_picker_0"]="New Batter"
    _choose_player(state,0)
    assert state["lineup_text_0"]=="New Batter"

def test_player_text_resolution():
    fixture=Path(__file__).parents[1]/"examples"/"fictional_projections.csv"
    pool=read_projection_csv(fixture)
    names=[p.name for p in pool[:9]]
    assert resolve_lineup_names(pool,[n.upper() for n in names])==names
    with pytest.raises(ValueError):resolve_lineup_names(pool,[names[0]]*9)
    with pytest.raises(ValueError):resolve_lineup_names(pool,["Partial"]+names[1:])
