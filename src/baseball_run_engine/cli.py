"""Command-line tools for importing projections and evaluating lineups."""
from __future__ import annotations
import argparse
import json
from .advancement import AdvancementKernel
from .markov import evaluate_lineup
from .monte_carlo import simulate_games
from .optimize import optimize_lineup,select_budget_roster
from .projections import read_projection_csv
from .statcast import fit_kernel_from_statcast
from .fangraphs import fetch_json,save_snapshot,read_export_csv,SYSTEMS
from .blend import blend_files

def _lineup(path,names):
    hitters=read_projection_csv(path)
    if names is None:
        if len(hitters)<9: raise ValueError("Need at least nine hitters")
        return hitters[:9]
    order=[s.strip() for s in names.split(",")]
    if len(order)!=9 or len(set(order))!=9: raise ValueError("Need nine unique names")
    lookup={h.name:h for h in hitters}
    if any(name not in lookup for name in order): raise ValueError("Unknown player in lineup")
    return [lookup[name] for name in order]

def main(argv=None):
    parser=argparse.ArgumentParser(description="Lineup-conditioned Markov baseball runs")
    sub=parser.add_subparsers(dest="command",required=True)
    for cmd in ("evaluate","simulate","optimize","select"):
        p=sub.add_parser(cmd)
        p.add_argument("--projections",required=True)
        p.add_argument("--kernel",default=None)
        p.add_argument("--innings",type=int,default=9)
        if cmd!="select": p.add_argument("--lineup",default=None)
        if cmd=="simulate":
            p.add_argument("--games",type=int,default=10000)
            p.add_argument("--seed",type=int,default=2026)
        if cmd=="optimize":
            p.add_argument("--restarts",type=int,default=2)
            p.add_argument("--seed",type=int,default=42)
        if cmd=="select":
            p.add_argument("--budget",type=float,required=True)
            p.add_argument("--seed",type=int,default=42)
    p=sub.add_parser("fit-advancement")
    p.add_argument("--statcast",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--prior-strength",type=float,default=10.0)
    p=sub.add_parser("fetch-projections")
    p.add_argument("--system",choices=(*SYSTEMS,"both"),default="both")
    p.add_argument("--out-dir",default="data/projections")
    p.add_argument("--csv",default=None)
    p.add_argument("--team",type=int,default=0)
    p.add_argument("--league",choices=("all","al","nl"),default="all")
    p.add_argument("--position",default="all")
    p.add_argument("--timeout",type=float,default=30)
    p=sub.add_parser("blend-projections")
    p.add_argument("--steamer",required=True)
    p.add_argument("--zips",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--weight-steamer",type=float,default=0.5)
    a=parser.parse_args(argv)
    if a.command=="fetch-projections":
        if a.csv and a.system=="both": parser.error("--csv requires a single projection system")
        systems=SYSTEMS if a.system=="both" else (a.system,)
        results=[]
        for system in systems:
            if a.csv: payload,source=read_export_csv(a.csv),f"CSV export: {a.csv}"
            else: payload,source=fetch_json(system,timeout=a.timeout,team=a.team,
                                             league=a.league,position=a.position)
            results.append(save_snapshot(system,a.out_dir,payload=payload,source=source))
        print(json.dumps(results,indent=2)); return
    if a.command=="blend-projections":
        print(json.dumps(blend_files(a.steamer,a.zips,a.output,a.weight_steamer),indent=2)); return
    if a.command=="fit-advancement":
        kernel,report=fit_kernel_from_statcast(a.statcast,a.prior_strength)
        kernel.save(a.output)
        print(json.dumps(report,indent=2)); return
    kernel=AdvancementKernel.load(a.kernel) if a.kernel else AdvancementKernel()
    if a.command=="select":
        result=select_budget_roster(read_projection_csv(a.projections),a.budget,kernel,seed=a.seed)
    else:
        roster=_lineup(a.projections,a.lineup)
        if a.command=="simulate":
            res=simulate_games(roster,a.games,a.innings,a.seed,kernel)
            print(json.dumps({"mean_runs":res.mean,"mc_se":res.standard_error,
                              "quantiles":res.quantiles},indent=2)); return
        if a.command=="evaluate":
            res=evaluate_lineup(roster,kernel,innings=a.innings)
            print(json.dumps({"expected_runs":res.total,"per_inning":res.per_inning,
                              "batting_order":[h.name for h in roster]},indent=2)); return
        result=optimize_lineup(roster,kernel,restarts=a.restarts,seed=a.seed,innings=a.innings)
    print(json.dumps({"expected_runs":result.expected_runs,"evaluations":result.evaluations,
                      "batting_order":[h.name for h in result.lineup],
                      "total_salary":sum(h.salary for h in result.lineup)},indent=2))

if __name__=="__main__":
    main()
