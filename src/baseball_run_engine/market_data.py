"""In-memory salary + service-time joins and explicit eligibility filters.

No intermediate merged CSV is required. Missing salaries are never treated as
free players. Service-time estimates are tracked separately from their
lower-bound/official status.
"""
from __future__ import annotations
import csv
from dataclasses import dataclass, replace
from pathlib import Path
from .projections import from_projection_row
from .salaries import read_salary_csv, clean_name, clean_team, _field
from .service_time import read_service_time, parse_service_days, DAYS_PER_YEAR

MLB_MINIMUM_BY_YEAR = {2022:700_000,2023:720_000,2024:740_000,
                       2025:760_000,2026:780_000}

@dataclass(frozen=True)
class PlayerMarketInfo:
    salary_known: bool = False
    salary_match: str = "unmatched"
    service_days: int | None = None
    service_estimated: bool = True
    service_lower_bound: bool = False
    service_match: str = "unmatched"

@dataclass
class EnrichedPool:
    hitters: list
    details: dict[str, PlayerMarketInfo]
    report: dict

def _lookup(records: list[dict], row: dict, *,
            id_field: str, with_team: bool, strict_team: bool) -> tuple[dict|None,str]:
    fg_id = _field(row,id_field)
    name_key = clean_name(_field(row,"Name","Player"))
    team = clean_team(_field(row,"Team"))
    if fg_id:
        ids=[r for r in records if r.get(id_field)==fg_id]
        if len(ids)==1: return ids[0],"id"
        if len(ids)>1: return None,"ambiguous"
    names=[r for r in records if r.get("name_key")==name_key]
    if team and with_team:
        matched=[r for r in names if r.get("team")==team]
        if len(matched)==1: return matched[0],"name_team"
        if len(matched)>1: return None,"ambiguous"
        if strict_team and any(r.get("team") for r in names):
            return None,"team_mismatch"
    if len(names)==1:
        return names[0],"name"
    return None,("ambiguous" if names else "unmatched")

def _projection_service(row: dict) -> tuple[int|None,bool]:
    days=_field(row,"ServiceDays","ServiceTimeDays")
    if days:
        try: return int(float(days)),False
        except ValueError: return None,False
    yrs=_field(row,"ServiceTime","MLBServiceTime")
    if yrs:
        try: return parse_service_days(yrs),False
        except ValueError: return None,False
    return None,False

def load_enriched_pool(projections: str|Path, salary_csv: str|Path|None=None,
                       service_file: str|Path|None=None, *,
                       season: int=2026) -> EnrichedPool:
    with Path(projections).open(newline="",encoding="utf-8-sig") as f:
        rows=list(csv.DictReader(f))
    if not rows: raise ValueError("Empty projections dataset")
    salaries=read_salary_csv(salary_csv,season=season) if salary_csv is not None else []
    service=read_service_time(service_file) if service_file is not None else []
    service_records=[{**r,"name_key":clean_name(r["name"]),
                      "team":clean_team(r["team"])}
                     for r in service]
    pool=[]
    details={}
    matches={"salary_id":0,"salary_name_team":0,"salary_name":0,
             "service_id":0,"service_name_team":0,"service_name":0,
             "salary_missing":0,"service_missing":0,"service_lower_bounds":0}
    for row in rows:
        hitter=from_projection_row(row)
        salary_match="existing" if hitter.salary>0 else "unmatched"
        if salaries:
            matched,salary_match=_lookup(salaries,row,id_field="fgid",
                                        with_team=True,strict_team=True)
            # Never fall back to a stale embedded salary if source was selected
            hitter=replace(hitter,salary=matched["price"] if matched else 0.0)
        if hitter.salary>0:
            key="salary_"+salary_match
            if key in matches: matches[key]+=1
        else:
            matches["salary_missing"]+=1
        service_days,service_floor=_projection_service(row)
        service_estimated=not bool(_field(row,"ServiceOfficial"))
        service_match="existing" if service_days is not None else "unmatched"
        if service_records:
            record,service_match=_lookup(service_records,row,id_field="mlbam_id",
                                           with_team=True,strict_team=False)
            # Explicit dataset is authoritative for *this estimator*; unmatched
            # fields from projection CSV remain if available.
            if record is not None:
                service_days=record["days"]
                service_floor=record["missing_seasons"]>0
                service_estimated=record["estimated"]
        if service_days is None: matches["service_missing"]+=1
        else:
            if service_floor:matches["service_lower_bounds"]+=1
            key="service_"+service_match
            if key in matches:matches[key]+=1
        if hitter.name in details:
            raise ValueError(f"Duplicate hitter name: {hitter.name}")
        pool.append(hitter)
        details[hitter.name]=PlayerMarketInfo(
            salary_known=hitter.salary>0,salary_match=salary_match,
            service_days=service_days,service_estimated=service_estimated,
            service_lower_bound=service_floor,service_match=service_match)
    report={"players":len(pool),"salary_source":str(salary_csv) if salary_csv else "projection",
            "service_source":str(service_file) if service_file else "projection",
            "season":season,"salary_matched":len(pool)-matches["salary_missing"],
            "service_matched":len(pool)-matches["service_missing"],**matches}
    return EnrichedPool(pool,details,report)

def filter_roster_candidates(data: EnrichedPool, *,
                             exclude_minimum_salary: bool=False,
                             league_minimum: float=780_000,
                             minimum_service_years: int=0) -> tuple[list,dict]:
    if not isinstance(minimum_service_years,int) or minimum_service_years<0:
        raise ValueError("Service threshold must be whole credited years >= 0")
    if league_minimum<0: raise ValueError("League minimum cannot be negative")
    threshold=minimum_service_years*DAYS_PER_YEAR
    eligible=[]
    counts={"missing_salary":0,"at_or_below_minimum":0,
            "missing_service":0,"below_service_threshold":0}
    for hitter in data.hitters:
        status=data.details[hitter.name]
        if not status.salary_known or hitter.salary<=0:
            counts["missing_salary"]+=1
        elif exclude_minimum_salary and hitter.salary<=league_minimum:
            counts["at_or_below_minimum"]+=1
        elif threshold>0 and status.service_days is None:
            counts["missing_service"]+=1
        elif threshold>0 and status.service_days<threshold:
            counts["below_service_threshold"]+=1
        else:
            eligible.append(hitter)
    return eligible,{"eligible":len(eligible),"total":len(data.hitters),
                     "service_threshold_days":threshold,
                     "minimum_salary_threshold":league_minimum,
                     "exclude_minimum_salary":exclude_minimum_salary,**counts}

def most_recent(folder: str|Path,pattern: str) -> Path|None:
    folder=Path(folder)
    options=[f for f in folder.glob(pattern) if f.is_file()] if folder.exists() else []
    return max(options,key=lambda f:f.stat().st_mtime_ns) if options else None
