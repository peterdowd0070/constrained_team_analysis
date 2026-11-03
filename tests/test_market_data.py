"""Contract tests for service time, automatic joins, and candidate filtering."""
import csv
import json
import pytest
from baseball_run_engine.market_data import (
    load_enriched_pool, filter_roster_candidates, MLB_MINIMUM_BY_YEAR)
from baseball_run_engine.service_time import (
    parse_service_days, format_service_days, read_service_time)

def put_csv(path, rows):
    with path.open("w",newline="",encoding="utf-8") as fh:
        writer=csv.DictWriter(fh,fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    return path

def fixtures(tmp_path):
    projections=[]
    salary_rows=[]
    service_rows=[]
    teams=["New York Mets","Boston Red Sox","Chicago Cubs"]
    for i in range(12):
        team=teams[i%3]
        projections.append({"Name":f"Player {i}","FGID":str(100+i),"Team":team,
                            "PA":500,"H":145,"2B":24,"3B":2,"HR":20,
                            "BB":55,"SO":105})
        salary_rows.append({"Name":f"Player {i}","FGID":str(100+i),"Team":team,
                            "Salary":str(780_000 if i<3 else 1_500_000+i*1000),
                            "Season":"2026"})
        service_rows.append([500+i,f"Player {i}",[1,2,3][i%3],1,172*i,1,0,0,1,None])
    p=put_csv(tmp_path/"projections.csv",projections)
    s=put_csv(tmp_path/"salaries.csv",salary_rows)
    # Tracker format: integers refer to the teams and positions arrays.
    j=tmp_path/"service.json"
    j.write_text(json.dumps({
        "teams":["","New York Mets","Boston Red Sox","Chicago Cubs"],
        "fields":["id","name","team","position","days","on_40_man",
                  "missing_seasons","super_two","has_page","birth_year"],
        "players":service_rows}))
    return p,s,j

def test_service_format_not_decimal():
    assert parse_service_days("2.045")==2*172+45
    assert parse_service_days("3.000")==3*172
    assert format_service_days(3*172+45)=="3.045"
    with pytest.raises(ValueError):
        parse_service_days("2.172")
    with pytest.raises(ValueError):
        parse_service_days("2.5")
    assert MLB_MINIMUM_BY_YEAR[2026]==780_000

def test_auto_enrichment_without_intermediate_csv(tmp_path):
    p,s,j=fixtures(tmp_path)
    merged=load_enriched_pool(p,s,j,season=2026)
    assert len(merged.hitters)==12
    assert merged.report["salary_matched"]==12
    assert merged.report["service_matched"]==12
    assert merged.details["Player 3"].service_days==3*172
    assert merged.hitters[3].salary==pytest.approx(1_503_000)
    assert len(list(tmp_path.glob("*merged*")))==0

def test_filter_minimum_salary_and_service(tmp_path):
    p,s,j=fixtures(tmp_path)
    pool=load_enriched_pool(p,s,j,season=2026)
    elig,counts=filter_roster_candidates(pool,
          exclude_minimum_salary=True,league_minimum=780_000,
          minimum_service_years=3)
    assert len(elig)==9
    assert counts["at_or_below_minimum"]==3
    assert all(h.salary>780_000 for h in elig)
    assert all(pool.details[h.name].service_days>=3*172 for h in elig)
    assert filter_roster_candidates(pool)[1]["eligible"]==12

def test_service_missing_excluded_when_threshold_active(tmp_path):
    p,s,j=fixtures(tmp_path)
    pool=load_enriched_pool(p,s,season=2026)
    elig,report=filter_roster_candidates(pool,minimum_service_years=1)
    assert not elig
    assert report["missing_service"]==12

def test_name_team_matching_and_mismatch(tmp_path):
    p,s,j=fixtures(tmp_path)
    with s.open() as fh: rows=list(csv.DictReader(fh))
    rows[5]["FGID"]=""
    rows[6]["FGID"]=""
    rows[6]["Team"]="Somewhere Else"
    put_csv(s,rows)
    pool=load_enriched_pool(p,s,j,season=2026)
    assert pool.details["Player 5"].salary_match=="name_team"
    assert pool.details["Player 6"].salary_known is False
    assert pool.report["salary_missing"]==1

def test_service_lower_bound_handling(tmp_path):
    p,s,j=fixtures(tmp_path)
    raw=json.loads(j.read_text())
    # Player 7 has >=7 years, so the minimum satisfies a >=3-year filter.
    raw["players"][7][6]=2
    # Player 2 has <=2 estimated years; a >=3-year requirement is not met.
    raw["players"][2][6]=1
    j.write_text(json.dumps(raw))
    pool=load_enriched_pool(p,s,j,season=2026)
    assert pool.details["Player 7"].service_lower_bound
    selected,_=filter_roster_candidates(pool,minimum_service_years=3)
    assert "Player 7" in [h.name for h in selected]
    assert "Player 2" not in [h.name for h in selected]

def test_service_time_csv_parser(tmp_path):
    service=put_csv(tmp_path/"service.csv",[
        {"Name":"A","Team":"BOS","ServiceTime":"2.045"},
        {"Name":"B","Team":"NYM","ServiceTime":"3.000"}])
    rows=read_service_time(service)
    assert rows[0]["days"]==389
    assert rows[1]["days"]==516
