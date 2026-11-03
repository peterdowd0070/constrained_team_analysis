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
from baseball_run_engine.ui_components import THEME, lineup_card, field_diagram, masthead, run_metric

ROOT=Path.cwd()
PROJECTIONS=ROOT/"data"/"projections"
KERNELS=ROOT/"data"/"processed"

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
        selection=st.sidebar.selectbox("Projection dataset",[str(p) for p in paths],
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
            st.session_state["projection_source"]=str(dest)
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
    if file:
        try:
            @st.cache_data(show_spinner=False)
            def cached_hitters(path,mtime):
                return load_hitters(path)
            pool=cached_hitters(str(file),file.stat().st_mtime_ns)
        except Exception as exc: st.error(f"Projection data invalid: {exc}")
    st.sidebar.caption(f"PLAYER POOL · {len(pool):,} hitters")
    tabs=st.tabs(["LINEUP CARD","FRONT OFFICE","DATA HUB","DIAGNOSTICS"])
    with tabs[0]:
        if len(pool)<9:
            st.info("No nine-player projection pool loaded. Download Steamer from DATA HUB, or upload an authorized CSV.")
            st.markdown(field_diagram(),unsafe_allow_html=True)
        else:
            key=str(file)
            if st.session_state.get("_lineup_source")!=key:
                for k in range(9): st.session_state.pop(f"lineup_slot_{k}",None)
                st.session_state["_lineup_source"]=key
            options=[h.name for h in pool]
            selections=[]
            with st.expander("EDIT BATTING ORDER",expanded=False):
                cols=st.columns(3)
                for i in range(9):
                    with cols[i%3]:
                        selections.append(st.selectbox(f"{i+1:02d} · Batter",options,
                                       index=i,key=f"lineup_slot_{i}"))
            if len(set(selections))!=9:
                st.warning("Select nine unique batters")
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
                    if st.button("Apply optimized order"):
                        for i,name in enumerate(order["names"]):
                            st.session_state[f"lineup_slot_{i}"]=name
                        st.session_state.pop("last_order",None)
                        st.rerun()
    with tabs[1]:
        st.subheader("Salary-constrained nine")
        st.caption("MVP: salary-only optimization, no fielding eligibility or bench constraints.")
        if len(pool)<9:
            st.info("Load real projections first.")
        elif not has_real_salaries(pool):
            st.warning("FanGraphs projections do not include salaries. Merge verified salary values before optimizing.")
        else:
            minimum=sum(sorted(h.salary for h in pool)[:9])
            budget=st.number_input("Budget (USD)",min_value=0.0,
                                   value=float(max(60000000,minimum)),step=1000000.0)
            if st.button("Find feasible roster",type="primary"):
                result=select_budget_roster(pool,budget,kernel,max_rounds=2,shortlist=3)
                st.metric("Runs / 9 innings",f"{result.expected_runs:.3f}")
                st.dataframe(pd.DataFrame({"Slot":range(1,10),
                    "Hitter":[h.name for h in result.lineup],
                    "Salary":[h.salary for h in result.lineup]}),hide_index=True)
                st.caption("Heuristic only; not a proof of global optimum.")
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
                    st.session_state["projection_source"]=saved["csv"]
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
    with tabs[3]:
        st.subheader("Diagnostics")
        a,b,c=st.columns(3)
        a.metric("Hitter pool",len(pool))
        b.metric("Empirical contexts",len(kernel.observations))
        c.metric("Salary complete","Yes" if has_real_salaries(pool) else "No")
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
