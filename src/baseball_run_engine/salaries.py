"""Salary ingestion with conservative ID/name/team joins. Never price missing players at $0."""
from __future__ import annotations
import csv, json, re, hashlib, unicodedata
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen

COMMUNITY_2026_URL=("https://raw.githubusercontent.com/jrue/python_lesson_2026/"
                    "main/mlb-salaries-2026.csv")
TEAMS={"arizona diamondbacks":"ARI","atlanta braves":"ATL",
"baltimore orioles":"BAL","boston red sox":"BOS","chicago cubs":"CHC",
"chicago white sox":"CHW","cincinnati reds":"CIN","cleveland guardians":"CLE",
"colorado rockies":"COL","detroit tigers":"DET","houston astros":"HOU",
"kansas city royals":"KCR","los angeles angels":"LAA","los angeles dodgers":"LAD",
"miami marlins":"MIA","milwaukee brewers":"MIL","minnesota twins":"MIN",
"new york mets":"NYM","new york yankees":"NYY","oakland athletics":"ATH",
"athletics":"ATH","philadelphia phillies":"PHI","pittsburgh pirates":"PIT",
"san diego padres":"SDP","san francisco giants":"SFG","seattle mariners":"SEA",
"st. louis cardinals":"STL","st louis cardinals":"STL","tampa bay rays":"TBR",
"texas rangers":"TEX","toronto blue jays":"TOR","washington nationals":"WSN"}
ALIASES={"KC":"KCR","SD":"SDP","SF":"SFG","TB":"TBR","CWS":"CHW",
         "OAK":"ATH","WSH":"WSN","WAS":"WSN"}

def clean_name(value):
    value=unicodedata.normalize("NFKD",str(value))
    value="".join(c for c in value if not unicodedata.combining(c))
    value=re.sub(r"\s*\[FG:[^]]+\]\s*$","",value,flags=re.I)
    return re.sub(r"[^a-z0-9]","",value.casefold())

def clean_team(value):
    v=str(value or "").strip().casefold()
    if not v: return ""
    if v in TEAMS: return TEAMS[v]
    return ALIASES.get(v.upper(),v.upper())

def _field(row,*names):
    normalized={str(k).strip().casefold().replace(" ","").replace("_",""):v
                for k,v in row.items() if k is not None}
    for n in names:
        value=normalized.get(n.casefold().replace(" ","").replace("_",""))
        if value is not None and str(value).strip()!="": return str(value).strip()
    return ""

def read_salary_csv(path,*,season=None):
    with Path(path).open(encoding="utf-8-sig",newline="") as fh:
        rows=list(csv.DictReader(fh))
    if not rows: raise ValueError("Salary CSV is empty")
    out=[]
    for row in rows:
        yr=_field(row,"Season","Year","yearID")
        if season is not None and yr and int(yr)!=season: continue
        value=_field(row,"Salary","salary_usd","Cash Salary","2026 Salary","AAV")
        if not value: continue
        try: price=float(re.sub(r"[$,\s]","",value))
        except ValueError as exc: raise ValueError(f"Invalid salary: {value!r}") from exc
        if not 0<price<float("inf"): continue
        name=_field(row,"Name","Player","player_name")
        fgid=_field(row,"FGID","FanGraphsID","FanGraphs ID")
        if name or fgid:
            out.append({"name":name,"name_key":clean_name(name),"fgid":fgid,
                        "team":clean_team(_field(row,"Team","TeamName")),"price":price})
    if not out: raise ValueError("No valid salary records for season")
    return out

def download_2026_salary_csv(directory,*,timeout=25):
    """Community 2026 data: salary basis unverified; not an authoritative payroll."""
    request=Request(COMMUNITY_2026_URL,headers={
        "User-Agent":"constrained-team-analysis/0.3 (personal research)",
        "Accept":"text/csv,text/plain"})
    with urlopen(request,timeout=timeout) as response: raw=response.read(4_000_001)
    if len(raw)>4_000_000: raise ValueError("Salary CSV exceeds 4 MB")
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc)
    path=directory/f"community_2026_{stamp:%Y%m%dT%H%M%SZ}.csv"
    path.write_bytes(raw)
    try:
        rows=read_salary_csv(path,season=2026)
        if len(rows)<100: raise ValueError("Unexpectedly few salary rows")
    except Exception:
        path.unlink(missing_ok=True);raise
    meta={"source":COMMUNITY_2026_URL,"retrieved_utc":stamp.isoformat(),
          "season":2026,"salary_records":len(rows),
          "basis":"unverified; not necessarily cash-payroll or CBT AAV",
          "sha256":hashlib.sha256(raw).hexdigest()}
    path.with_suffix(".manifest.json").write_text(json.dumps(meta,indent=2)+"\n")
    return path,meta

def merge_salary_csv(projections,salaries,output,*,season=None,basis="reported / unverified"):
    """Prefer FGID, then same name and team, then unique normalized name.

    Ambiguous or missing costs receive SalaryMatched=false and Salary=0;
    optimizer must explicitly exclude those players.
    """
    incoming=read_salary_csv(salaries,season=season)
    with Path(projections).open(encoding="utf-8-sig",newline="") as fh:
        reader=csv.DictReader(fh)
        if reader.fieldnames is None: raise ValueError("Empty projections CSV")
        fields=list(reader.fieldnames);projected=list(reader)
    ids={};names={}
    for s in incoming:
        if s["fgid"]: ids.setdefault(s["fgid"],[]).append(s)
        if s["name_key"]: names.setdefault(s["name_key"],[]).append(s)
    report={"matched_id":0,"matched_name_team":0,"matched_name":0,
            "ambiguous":0,"unmatched":0}
    unresolved=[]
    for row in projected:
        fgid=_field(row,"FGID","FanGraphsID")
        name=_field(row,"Name","Player")
        team=clean_team(_field(row,"Team","TeamName"))
        options=ids.get(fgid,[]) if fgid else []
        mode="matched_id" if options else "matched_name"
        if not options:
            options=names.get(clean_name(name),[])
            if team:
                exact=[s for s in options if s["team"]==team]
                if exact:options=exact;mode="matched_name_team"
        prices={s["price"] for s in options}
        if options and len(prices)==1:
            row["Salary"]=str(next(iter(prices)))
            row["SalaryMatched"]="true"
            row["SalaryBasis"]=basis
            report[mode]+=1
        else:
            row["Salary"]="0";row["SalaryMatched"]="false";row["SalaryBasis"]=""
            status="ambiguous" if options else "unmatched"
            report[status]+=1
            unresolved.append({"Name":name,"Team":team,"Reason":status})
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    cols=list(dict.fromkeys([*fields,"Salary","SalaryMatched","SalaryBasis"]))
    with output.open("w",encoding="utf-8",newline="") as fh:
        writer=csv.DictWriter(fh,fieldnames=cols,extrasaction="ignore")
        writer.writeheader();writer.writerows(projected)
    full={"output":str(output),"projection_rows":len(projected),
          "salary_records":len(incoming),"season":season,"basis":basis,
          **report,"unresolved":unresolved[:50]}
    output.with_suffix(".salary-report.json").write_text(json.dumps(full,indent=2)+"\n")
    return full
