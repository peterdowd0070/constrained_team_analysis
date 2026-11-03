"""Streamlit front-office UI: baseball lineup-card presentation and Markov analysis."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

from baseball_run_engine.advancement import AdvancementKernel
from baseball_run_engine.blend import blend_files
from baseball_run_engine.events import Event
from baseball_run_engine.fangraphs import fetch_json, save_snapshot
from baseball_run_engine.fast_markov import FastRunEngine
from baseball_run_engine.markov import evaluate_lineup
from baseball_run_engine.optimize import optimize_lineup, select_budget_roster
from baseball_run_engine.projections import read_projection_csv
from baseball_run_engine.retrosheet import download_season, fit_retrosheet, transition_logloss
from baseball_run_engine.salaries import download_2026_salary_csv
from baseball_run_engine.service_time import download_service_index, format_service_days
from baseball_run_engine.market_data import (
    load_enriched_pool, filter_roster_candidates, most_recent, MLB_MINIMUM_BY_YEAR)
from baseball_run_engine.ui_components import THEME, lineup_card, field_diagram, masthead, run_metric

ROOT=Path.cwd()
PROJECTIONS=ROOT/"data"/"projections"
KERNELS=ROOT/"data"/"processed"
SALARIES=ROOT/"data"/"salaries"
SERVICES=ROOT/"data"/"service_time"
REFERENCE_SEASON=2026

def _automatic_market_sources(state, *, refresh=False):
    """Download once per Streamlit session; never retry on every widget rerun."""
    if refresh or not state.get("_market_data_attempted",False):
        state["_market_data_attempted"]=True
        issues=[]
        if most_recent(SALARIES,"*.csv") is None:
            try:
                download_2026_salary_csv(SALARIES,timeout=8)
            except Exception as exc:
                issues.append(f"Salary feed: {exc}")
        if most_recent(SERVICES,"*.json") is None:
            try:
                download_service_index(SERVICES,timeout=8)
            except Exception as exc:
                issues.append(f"Service-time feed: {exc}")
        state["_market_source_issues"]=issues
    return most_recent(SALARIES,"*.csv"),most_recent(SERVICES,"*.json")

def load_hitters(path):
    return read_projection_csv(path)

def validate_lineup(pool, names):
    if len(names)!=9 or len(set(names))!=9:
        raise ValueError("Select nine distinct batters")
    by_name={h.name:h for h in pool}
    if any(name not in by_name for name in names):
        raise ValueError("Unknown hitter")
    return [by_name[name] for name in names]

def has_real_salaries(pool):
    return bool(pool) and all(h.salary>0 for h in pool)

def probability_table(pool):
    return [{"Batter":h.name,**{e.name:round(100*h.probability(e),2) for e in Event}}
            for h in pool]

def _safe_uploaded_name(name):
    return re.sub(r"[^A-Za-z0-9_.-]","_",Path(name.replace(chr(92),"/")).name)[:100]

def _store_upload(file,directory):
    if len(file.getvalue())>30_000_000:
        raise ValueError("Maximum 30 MB per upload")
    directory.mkdir(parents=True,exist_ok=True)
    dest=directory/(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ_")+
                    _safe_uploaded_name(file.name))
    dest.write_bytes(file.getvalue())
    return dest

def _apply_optimized_order(state):
    """Callback executes before Streamlit recreates keyed inputs."""
    candidate=state.get("last_order")
    if candidate:
        for i,name in enumerate(candidate["names"]):
            state[f"lineup_text_{i}"]=name
        state.pop("last_order",None)
        state.pop("last_result",None)

def _clear_lineup(state,index):
    state[f"lineup_text_{index}"]=""

def _choose_player(state,index):
    chosen=state.get(f"lineup_picker_{index}")
    if chosen: state[f"lineup_text_{index}"]=chosen

def resolve_lineup_names(pool,names):
    if len(names)!=9: raise ValueError("Exactly nine hitters required")
    lookup={h.name.casefold():h.name for h in pool}
    resolved=[]
    for name in names:
        actual=lookup.get(name.strip().casefold())
        if actual is None:
            raise ValueError(f"Unknown or incomplete player name: {name!r}")
        resolved.append(actual)
    if len(set(resolved))!=9: raise ValueError("Choose nine different hitters")
    return resolved

def main():
    try:
        import streamlit as st
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError('Install: pip install -e ".[gui]"') from exc
    st.set_page_config(page_title="Lineup Lab | Constrained Team Analysis",
                       page_icon="⚾",layout="wide")
    st.markdown(THEME,unsafe_allow_html=True)
    st.markdown(masthead(),unsafe_allow_html=True)
    st.sidebar.header("FRONT OFFICE")
    paths=sorted(PROJECTIONS.glob("*.csv"),
                 key=lambda p:p.stat().st_mtime,reverse=True) if PROJECTIONS.exists() else []
    if paths:
        options=[str(p) for p in paths]
        pending=st.session_state.pop("_pending_projection_source",None)
        if pending in options:
            st.session_state["projection_source"]=pending
        selection=st.sidebar.selectbox("Projection dataset",options,
                                      key="projection_source")
        file=Path(selection)
    else:
        file=None
        st.sidebar.info("No projections loaded. Download Steamer in DATA HUB.")
    upload=st.sidebar.file_uploader("Import FanGraphs projection CSV",type="csv")
    if upload and st.sidebar.button("Import player data"):
        dest=None
        try:
            dest=_store_upload(upload,PROJECTIONS)
            load_hitters(dest)
            st.session_state["_pending_projection_source"]=str(dest)
            st.rerun()
        except Exception as exc:
            if dest is not None: dest.unlink(missing_ok=True)
            st.sidebar.error(str(exc))
    kernel_paths=sorted(KERNELS.glob("*.json")) if KERNELS.exists() else []
    kernel_name=st.sidebar.selectbox("Runner advancement",
                      ["Simplified / uncalibrated"]+[str(p) for p in kernel_paths])
    empirical=kernel_name!="Simplified / uncalibrated"
    try:
        kernel=AdvancementKernel.load(kernel_name) if empirical else AdvancementKernel()
    except Exception as exc:
        st.sidebar.error(str(exc));kernel=AdvancementKernel();empirical=False
    if not empirical: st.sidebar.warning("Uncalibrated advancement. Runs are illustrative.")
    else: st.sidebar.success("Empirical advancement model loaded.")
    pool=[]
    market=None
    salary_source=service_source=None
    if file:
        salary_source,service_source=_automatic_market_sources(st.session_state)
        for issue in st.session_state.get("_market_source_issues",[]):
            st.sidebar.caption(f"Automatic source unavailable: {issue}")
        try:
            @st.cache_data(show_spinner=False)
            def cached_market_data(projection_path,p_mtime,salary_path,s_mtime,
                                   service_path,t_mtime,year):
                return load_enriched_pool(projection_path,
                    salary_csv=salary_path or None,
                    service_file=service_path or None,season=year)
            market=cached_market_data(
                str(file),file.stat().st_mtime_ns,
                str(salary_source) if salary_source else "",
                salary_source.stat().st_mtime_ns if salary_source else 0,
                str(service_source) if service_source else "",
                service_source.stat().st_mtime_ns if service_source else 0,
                REFERENCE_SEASON)
            pool=market.hitters
        except Exception as exc:
            st.error(f"Could not load market data: {exc}")
            st.stop()
    st.sidebar.caption(f"PLAYER POOL · {len(pool):,} hitters")
    if market:
        st.sidebar.caption(
            f'SALARY MATCHED · {market.report["salary_matched"]:,}/{len(pool):,}')
        st.sidebar.caption(
            f'SERVICE-TIME ESTIMATES · {market.report["service_matched"]:,}/{len(pool):,}')
        st.sidebar.caption("Salary reference: 2026; service time estimated, not official.")
    tabs=st.tabs(["LINEUP CARD","FRONT OFFICE","DATA HUB","DIAGNOSTICS"])
    with tabs[0]:
        if len(pool)<9:
            st.info("No nine-player projection pool loaded. Download Steamer from DATA HUB, or upload an authorized CSV.")
            st.markdown(field_diagram(),unsafe_allow_html=True)
        else:
            key=str(file)
            if st.session_state.get("_lineup_source")!=key:
                for k in range(9):
                    st.session_state.pop(f"lineup_text_{k}",None)
                    st.session_state.pop(f"lineup_picker_{k}",None)
                st.session_state["_lineup_source"]=key
                st.session_state.pop("last_order",None)
                st.session_state.pop("last_result",None)
            names=[h.name for h in pool]
            for i,name in enumerate(names[:9]):
                st.session_state.setdefault(f"lineup_text_{i}",name)
            entered=[]
            with st.expander("EDIT BATTING ORDER",expanded=True):
                for i in range(9):
                    field,picker,clear=st.columns([7,2,1],gap="small")
                    with field:
                        entered.append(st.text_input(
                            f"{i+1:02d} · Batter",key=f"lineup_text_{i}",
                            placeholder="Enter player name"))
                    with picker:
                        st.caption("Find")
                        with st.popover(f"Find #{i+1}",use_container_width=True):
                            st.selectbox(f"Search spot {i+1}",names,index=None,
                                placeholder="Type to find",key=f"lineup_picker_{i}",
                                on_change=_choose_player,args=(st.session_state,i))
                    with clear:
                        st.caption("Clear")
                        st.button("×",key=f"clear_lineup_{i}",use_container_width=True,
                            on_click=_clear_lineup,args=(st.session_state,i))
                st.caption("Editable text: drag to highlight, or press Cmd/Ctrl+A then "
                           "Backspace to replace. × clears the entire name.")
            try:
                selections=resolve_lineup_names(pool,entered)
            except ValueError as exc:
                selections=[]
                st.info(str(exc))
            if len(selections)!=9:
                st.caption("Complete nine distinct names before evaluating.")
            else:
                lineup=validate_lineup(pool,selections)
                left,right=st.columns([1.9,1],gap="large")
                with left: st.markdown(lineup_card(lineup),unsafe_allow_html=True)
                with right:
                    st.markdown(field_diagram(),unsafe_allow_html=True)
                    cached=st.session_state.get("last_result")
                    same=(cached and cached["names"]==tuple(selections)
                          and cached["source"]==key and cached["kernel"]==kernel_name)
                    st.markdown(run_metric(f'{cached["runs"]:.3f}' if same else "—"),
                                unsafe_allow_html=True)
                first,second,third=st.columns([1,1,2])
                if first.button("Evaluate lineup",type="primary",use_container_width=True):
                    result=evaluate_lineup(lineup,kernel)
                    st.session_state["last_result"]={
                        "names":tuple(selections),"source":key,"kernel":kernel_name,
                        "runs":result.total,"per_inning":list(result.per_inning)}
                    st.rerun()
                mode=third.radio("Search",["Quick","Thorough"],horizontal=True,
                                 label_visibility="collapsed")
                if second.button("Optimize order",use_container_width=True):
                    result=optimize_lineup(lineup,kernel,
                                          restarts=0 if mode=="Quick" else 3,
                                          max_passes=5 if mode=="Quick" else 12)
                    st.session_state["last_order"]={"source":key,
                        "names":[h.name for h in result.lineup],
                        "runs":result.expected_runs,"evaluations":result.evaluations}
                cached=st.session_state.get("last_result")
                if cached and cached["source"]==key and cached["kernel"]==kernel_name and cached["names"]==tuple(selections):
                    st.line_chart(pd.DataFrame({"Expected runs by inning":cached["per_inning"]},
                                               index=range(1,10)))
                order=st.session_state.get("last_order")
                if order and order["source"]==key:
                    st.success(f'Local best: {order["runs"]:.3f} runs / game, {order["evaluations"]} evaluations')
                    st.button("Apply optimized order",on_click=_apply_optimized_order,
                              args=(st.session_state,))
    with tabs[1]:
        st.subheader("Constrained nine-hitter roster")
        st.caption("Filters apply to roster selection only; the lineup card can use any player.")
        left,middle,right=st.columns([1,1,1])
        with left:
            exclude_min=st.checkbox("Exclude league-minimum salaries",value=False)
        with middle:
            service_min=st.number_input("Minimum completed MLB service years",
                                        min_value=0,max_value=15,value=0,step=1)
        with right:
            salary_floor=st.number_input("2026 league-minimum threshold (USD)",
                            min_value=0,max_value=5_000_000,value=780_000,step=10_000,
                            disabled=not exclude_min)
        st.caption("2026 CBA minimum: $780,000. Service years use 172 credited days. "
                   "Minimum-service filter excludes unknown records; lower bounds "
                   "pass only if the known minimum satisfies the threshold.")
        if market is None or len(pool)<9:
            st.info("Load projections first.")
        else:
            eligible,summary=filter_roster_candidates(market,
                exclude_minimum_salary=exclude_min,
                league_minimum=float(salary_floor),
                minimum_service_years=int(service_min))
            m1,m2,m3,m4=st.columns(4)
            m1.metric("Eligible hitters",summary["eligible"])
            m2.metric("Unpriced",summary["missing_salary"])
            m3.metric("Minimum salary excluded",summary["at_or_below_minimum"])
            m4.metric("Service-time excluded",
                summary["missing_service"]+summary["below_service_threshold"])
            if salary_source is None:
                st.error("No salary source is available. The Data Hub can retry automatic retrieval, "
                         "or import a salary file. Missing salaries are never counted as $0.")
            if service_min>0 and service_source is None and market.report["service_matched"]==0:
                st.warning("No service-time source available. Cannot verify eligibility.")
            if salary_source and "community_" in salary_source.name:
                st.warning("Community salary data is indicative, not audited cash payroll. "
                           "For 2027 projections these are historical 2026 salaries.")
            if len(eligible)<9:
                st.warning(f"Only {len(eligible)} eligible players after filtering; "
                           "at least nine are required.")
            else:
                minimum=sum(sorted(h.salary for h in eligible)[:9])
                budget=st.number_input("Nine-hitter budget (USD)",min_value=0.0,
                    value=float(max(60_000_000,minimum)),step=1_000_000.0)
                if st.button("Find feasible roster",type="primary"):
                    try:
                        result=select_budget_roster(eligible,budget,kernel,
                                                    max_rounds=2,shortlist=3)
                        st.metric("Runs / 9 offensive innings",f"{result.expected_runs:.3f}")
                        st.dataframe(pd.DataFrame({
                            "Slot":range(1,10),
                            "Hitter":[h.name for h in result.lineup],
                            "Salary":[h.salary for h in result.lineup],
                            "Service":[format_service_days(market.details[h.name].service_days)
                                       if market.details[h.name].service_days is not None else "Unknown"
                                       for h in result.lineup]}),hide_index=True)
                        st.caption("Heuristic roster search; positional eligibility and roster rights "
                                   "are not yet enforced.")
                    except Exception as exc:
                        st.error(f"Optimization failed: {exc}")
    with tabs[2]:
        st.subheader("Data hub")
        left,right=st.columns(2)
        with left:
            system=st.selectbox("Projection provider",["steamer","zips"])
            if st.button("Download current FanGraphs projections"):
                try:
                    payload,url=fetch_json(system,timeout=30)
                    saved=save_snapshot(system,PROJECTIONS,payload=payload,source=url)
                    load_hitters(saved["csv"])
                    st.session_state["_pending_projection_source"]=str(saved["csv"])
                    st.rerun()
                except Exception as exc:
                    st.error(f"FanGraphs fetch failed: {exc}. Upload an authorized CSV export instead.")
            if len(paths)>=2:
                a=st.selectbox("Steamer file",paths,format_func=lambda p:p.name)
                b=st.selectbox("ZiPS file",paths,format_func=lambda p:p.name)
                w=st.slider("Steamer blend weight",0.0,1.0,0.5,0.05)
                if st.button("Blend systems"):
                    try:
                        if a==b: raise ValueError("Choose distinct files")
                        dest=PROJECTIONS/("blend_"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+".csv")
                        st.json(blend_files(a,b,dest,w))
                    except Exception as exc: st.error(str(exc))
        with right:
            season=st.number_input("Retrosheet season",min_value=1900,max_value=2025,value=2025)
            if st.button("Fetch and fit advancement"):
                try:
                    downloaded=download_season(int(season),ROOT/"data"/"raw"/f"{season}plays.zip")
                    estimated,report=fit_retrosheet(downloaded)
                    KERNELS.mkdir(parents=True,exist_ok=True)
                    target=KERNELS/f"advancement_{season}.json"
                    estimated.save(target)
                    st.success(f"Saved: {target}");st.json(report)
                except Exception as exc: st.error(str(exc))
            st.caption("Retrosheet material is copyrighted by Retrosheet.")
        st.markdown("#### Automatic salary and service-time enrichment")
        st.caption("Projections are joined in memory with the latest locally cached "
                   "2026 salary and service-time files. No manual merge is necessary.")
        if st.button("Refresh missing market sources"):
            _automatic_market_sources(st.session_state,refresh=True)
            st.rerun()
        if market:
            st.json({"salary_file":str(salary_source) if salary_source else None,
                     "service_file":str(service_source) if service_source else None,
                     **market.report})
        s1,s2=st.columns(2)
        with s1:
            salary_upload=st.file_uploader("Optional salary CSV override",type="csv",
                                           key="salary_upload")
            if salary_upload and st.button("Import salary source"):
                try:
                    dest=_store_upload(salary_upload,SALARIES)
                    st.success(f"Imported {dest.name}")
                    st.rerun()
                except Exception as exc: st.error(str(exc))
        with s2:
            service_upload=st.file_uploader(
                "Optional service-time CSV or tracker JSON",type=["csv","json"],
                key="service_upload")
            if service_upload and st.button("Import service-time source"):
                dest=None
                try:
                    dest=_store_upload(service_upload,SERVICES)
                    from baseball_run_engine.service_time import read_service_time
                    read_service_time(dest)
                    st.success(f"Imported {dest.name}")
                    st.rerun()
                except Exception as exc:
                    if dest is not None: dest.unlink(missing_ok=True)
                    st.error(str(exc))
        st.caption("Sources are automatically matched by stable IDs where available, "
                   "then normalized names and teams. Unmatched salaries are excluded.")
    with tabs[3]:
        st.subheader("Diagnostics")
        a,b,c=st.columns(3)
        a.metric("Hitter pool",len(pool))
        b.metric("Empirical contexts",len(kernel.observations))
        c.metric("Salary coverage",f'{market.report["salary_matched"]}/{len(pool)}' if market else "0/0")
        if pool: st.dataframe(pd.DataFrame(probability_table(pool[:100])),hide_index=True)
        uploaded=st.file_uploader("Held-out Retrosheet CSV or ZIP",type=["csv","zip"])
        if uploaded and st.button("Validate advancement"):
            if not empirical: st.warning("Load empirical advancement kernel first")
            else:
                try:
                    path=_store_upload(uploaded,ROOT/"data"/"raw")
                    st.json(transition_logloss(kernel,path))
                except Exception as exc: st.error(str(exc))
        if len(pool)>=9 and st.button("Benchmark dense vs sparse solver"):
            from time import perf_counter
            start=perf_counter();exact=evaluate_lineup(pool[:9],kernel).total
            dense_ms=(perf_counter()-start)*1000
            fast=FastRunEngine(kernel)
            start=perf_counter();optimized=fast.score(pool[:9])
            sparse_ms=(perf_counter()-start)*1000
            st.json({"reference_runs":exact,"fast_runs":optimized,
                 "absolute_error":abs(exact-optimized),
                 "dense_ms":dense_ms,"sparse_ms":sparse_ms,
                 "speedup":dense_ms/max(sparse_ms,1e-12)})
        st.caption("Nine offensive innings; no opponent-pitcher, defense, or individual baserunning model.")

if __name__=="__main__":
    main()
