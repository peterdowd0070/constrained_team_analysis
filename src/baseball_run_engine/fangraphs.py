"""Fetch/normalize live FanGraphs ZiPS and Steamer batting projections.

No access-control bypass. Preserve a timestamped snapshot and manifest;
live projections must not be mistaken for historical preseason forecasts.
"""
from __future__ import annotations
import csv
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any,Mapping
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,urlopen

ENDPOINT="https://www.fangraphs.com/api/projections"
SYSTEMS=("steamer","zips")
CANONICAL_COLUMNS=("Name","FGID","Team","PA","H","2B","3B","HR","BB","SO",
                   "HBP","Salary","Positions","ProjectionSystem")

class ProjectionDownloadError(RuntimeError): pass

def _keys(row:Mapping[str,Any]):
    return {str(k).casefold().strip().replace(" ","").replace("_",""):v
            for k,v in row.items() if k is not None}

def _value(row:Mapping[str,Any],*aliases,default=None):
    data=_keys(row)
    for a in aliases:
        v=data.get(a.casefold().replace(" ","").replace("_",""))
        if v is not None and str(v).strip()!="": return v
    return default

def _number(row,*aliases,default=None):
    v=_value(row,*aliases,default=default)
    if v is None: raise ValueError(f"Missing numeric field: {aliases}")
    try: n=float(str(v).replace(",","").replace("$",""))
    except (ValueError,TypeError) as exc: raise ValueError(f"Invalid {aliases}: {v}") from exc
    if not math.isfinite(n) or n<0: raise ValueError(f"Invalid {aliases}: {n}")
    return n

def extract_records(payload:Any):
    if isinstance(payload,list) and all(isinstance(r,dict) for r in payload): return payload
    if isinstance(payload,dict):
        for k in ("data","players","projections","results"):
            v=payload.get(k)
            if isinstance(v,list) and all(isinstance(r,dict) for r in v): return v
    raise ValueError("Unexpected FanGraphs JSON schema: expected player records")

def normalize_projection_row(raw:Mapping[str,Any],system:str):
    if system not in SYSTEMS: raise ValueError("Unsupported system")
    name=_value(raw,"Name","PlayerName","player_name","full_name","player")
    if name is None or not str(name).strip(): raise ValueError("Missing player name")
    pa=_number(raw,"PA","plate_appearances")
    if pa<=0: raise ValueError("Zero PA")
    doubles=_number(raw,"2B","x2b","doubles")
    triples=_number(raw,"3B","x3b","triples")
    hr=_number(raw,"HR","homeruns","home_runs")
    h_val=_value(raw,"H","Hits")
    h=_number(raw,"H","Hits") if h_val is not None else (
        _number(raw,"1B","x1b","singles")+doubles+triples+hr)
    bb=_number(raw,"BB","Walks")
    so=_number(raw,"SO","K","strikeouts")
    hbp=_number(raw,"HBP","hitbypitch",default=0)
    if h<doubles+triples+hr-0.51 or pa<h+bb+so+hbp-0.51:
        raise ValueError("Mutually inconsistent projected counts")
    return {"Name":str(name).strip(),
            "FGID":str(_value(raw,"FGID","playerid","player_id","fgid",default="")),
            "Team":str(_value(raw,"Team","teamname",default="")),
            "PA":str(pa),"H":str(h),"2B":str(doubles),"3B":str(triples),
            "HR":str(hr),"BB":str(bb),"SO":str(so),"HBP":str(hbp),
            "Salary":str(_number(raw,"Salary","salary_usd",default=0)),
            "Positions":str(_value(raw,"Positions","position","pos",default="")),
            "ProjectionSystem":system}

def normalize_records(records:list[Mapping[str,Any]],system:str):
    if not records: raise ValueError("No projection rows")
    output=[]; invalid=[]; zero_pa=0
    for n,row in enumerate(records):
        try: output.append(normalize_projection_row(row,system))
        except ValueError as exc:
            if "Zero PA" in str(exc): zero_pa+=1
            else: invalid.append(f"row {n}: {exc}")
    if invalid:
        raise ValueError(f"Projection schema validation failed for {len(invalid)} rows: {'; '.join(invalid[:4])}")
    if not output: raise ValueError("No usable projections")
    ids=set()
    for row in output:
        k=row["FGID"] or row["Name"]
        if k in ids: raise ValueError(f"Duplicate player {k}")
        ids.add(k)
    name_counts={}
    for row in output: name_counts[row["Name"]]=name_counts.get(row["Name"],0)+1
    for row in output:
        if name_counts[row["Name"]]>1:
            if not row["FGID"]: raise ValueError("Name collision without FGID")
            row["Name"]+=f" [FG:{row['FGID']}]"
    return output,{"received":len(records),"included":len(output),"skipped_zero_pa":zero_pa}

def projection_url(system:str,team:int=0,league:str="all",position:str="all"):
    if system not in SYSTEMS: raise ValueError("Invalid projection system")
    if not isinstance(team,int) or team<0: raise ValueError("Invalid team")
    if league not in ("all","al","nl"): raise ValueError("Invalid league")
    return ENDPOINT+"?"+urlencode({"type":system,"stats":"bat","pos":position,
                                     "team":team,"players":0,"lg":league})

def fetch_json(system:str,*,timeout:float=30,team:int=0,
               league:str="all",position:str="all"):
    url=projection_url(system,team,league,position)
    request=Request(url,headers={"User-Agent":"baseball-run-engine/0.2 (research)",
                                 "Accept":"application/json"})
    try:
        with urlopen(request,timeout=timeout) as response:
            raw=response.read()
            mime=response.headers.get("Content-Type","")
    except HTTPError as exc:
        raise ProjectionDownloadError(f"FanGraphs HTTP {exc.code}; use an authorized CSV export") from exc
    except (URLError,TimeoutError,OSError) as exc:
        raise ProjectionDownloadError(f"FanGraphs unavailable: {exc}; use --csv") from exc
    try: payload=json.loads(raw)
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise ProjectionDownloadError(f"Non-JSON FanGraphs response ({mime}); use --csv") from exc
    return payload,url

def read_export_csv(path:str|Path):
    with Path(path).open(newline="",encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def save_snapshot(system:str,out_dir:str|Path,*,payload:Any,source:str,
                  timestamp:datetime|None=None):
    timestamp=timestamp or datetime.now(timezone.utc)
    stamp=timestamp.strftime("%Y%m%dT%H%M%SZ")
    directory=Path(out_dir); directory.mkdir(parents=True,exist_ok=True)
    rows,stats=normalize_records(extract_records(payload),system)
    prefix=directory/f"{system}_{stamp}"
    csv_path=prefix.with_suffix(".csv")
    with csv_path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=CANONICAL_COLUMNS)
        w.writeheader(); w.writerows(rows)
    raw=json.dumps(payload,ensure_ascii=False,separators=(",",":"))
    if source.startswith("https://"): prefix.with_suffix(".raw.json").write_text(raw)
    manifest={"schema_version":1,"system":system,
              "fetched_at_utc":timestamp.isoformat(),"source":source,
              "raw_sha256":hashlib.sha256(raw.encode()).hexdigest(),
              "normalized_csv":csv_path.name,"counts":stats,
              "note":"Live snapshot, not necessarily a preseason projection"}
    manifest_path=prefix.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest,indent=2)+"\n")
    return {"system":system,"csv":str(csv_path),"manifest":str(manifest_path),**stats}
