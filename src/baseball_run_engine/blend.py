"""Blend ZiPS/Steamer per-PA projected event rates by FanGraphs ID."""
from __future__ import annotations
import csv
from pathlib import Path
import math
from .fangraphs import CANONICAL_COLUMNS,normalize_records,read_export_csv
COUNTS=("H","2B","3B","HR","BB","SO","HBP")

def blend_files(steamer:str|Path,zips:str|Path,output:str|Path,
                weight_steamer:float=0.5):
    if not math.isfinite(weight_steamer) or not 0<=weight_steamer<=1:
        raise ValueError("weight_steamer must be in [0,1]")
    a,_=normalize_records(read_export_csv(steamer),"steamer")
    b,_=normalize_records(read_export_csv(zips),"zips")
    left={r["FGID"]:r for r in a if r["FGID"]}
    right={r["FGID"]:r for r in b if r["FGID"]}
    if not left or not right: raise ValueError("Require FanGraphs IDs for both systems")
    shared=sorted(left.keys()&right.keys())
    if not shared: raise ValueError("No matching FanGraphs IDs")
    blended=[]
    w=weight_steamer
    for fgid in shared:
        l,r=left[fgid],right[fgid]
        lpa,rpa=float(l["PA"]),float(r["PA"])
        pa=w*lpa+(1-w)*rpa
        row=dict(l)
        row["PA"]=str(pa)
        row["ProjectionSystem"]="steamer_zips_blend"
        for field in COUNTS:
            rate=w*float(l[field])/lpa+(1-w)*float(r[field])/rpa
            row[field]=str(pa*rate)
        if sum(float(row[c]) for c in ("H","BB","SO","HBP"))>pa+0.51:
            raise ValueError(f"Inconsistent outcomes for {fgid}")
        blended.append(row)
    path=Path(output); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=CANONICAL_COLUMNS)
        writer.writeheader(); writer.writerows(blended)
    return {"output":str(path),"matched":len(shared),
            "steamer_only":len(left)-len(shared),"zips_only":len(right)-len(shared)}
