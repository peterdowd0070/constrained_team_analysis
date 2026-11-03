"""Streamlit GUI for offensive lineup optimization."""
from pathlib import Path
import streamlit as st
import pandas as pd
from baseball_run_engine.projections import read_projection_csv
from baseball_run_engine.advancement import AdvancementKernel
from baseball_run_engine.markov import evaluate_lineup
from baseball_run_engine.optimize import optimize_lineup, select_budget_roster
from baseball_run_engine.fangraphs import fetch_json, save_snapshot
from baseball_run_engine.retrosheet import download_season, fit_retrosheet

BASE = Path.cwd()
DATA = BASE / "data" / "projections"
KERNELS = BASE / "data" / "processed"
DEMO = BASE / "examples" / "fictional_projections.csv"

def main():
    st.set_page_config(page_title="Constrained Team Analysis", layout="wide")
    st.title("Constrained Team Analysis")
    st.caption("Projection-driven batting order and roster optimization")
    files = sorted(DATA.glob("*.csv")) if DATA.exists() else []
    source = st.sidebar.selectbox("Batting projections", ["Fictional demo"] + [str(x) for x in files])
    upload = st.sidebar.file_uploader("Import projection CSV", type="csv")
    if upload is not None and st.sidebar.button("Save imported file"):
        DATA.mkdir(parents=True, exist_ok=True)
        target = DATA / Path(upload.name).name
        target.write_bytes(upload.getvalue())
        try:
            read_projection_csv(target)
            st.sidebar.success("Saved. Select the file in the dropdown.")
        except Exception as exc:
            target.unlink(missing_ok=True)
            st.sidebar.error(str(exc))
    chosen_file = DEMO if source == "Fictional demo" else Path(source)
    try:
        pool = read_projection_csv(chosen_file)
    except Exception as exc:
        st.error(f"Cannot read projections: {exc}")
        st.stop()
    kernel_files = sorted(KERNELS.glob("*.json")) if KERNELS.exists() else []
    kernel_name = st.sidebar.selectbox("Advancement model", ["Simplified"] + [str(x) for x in kernel_files])
    try:
        kernel = AdvancementKernel() if kernel_name == "Simplified" else AdvancementKernel.load(kernel_name)
    except Exception as exc:
        st.error(str(exc))
        st.stop()
    if source == "Fictional demo":
        st.warning("Demo player projections are fictional.")
    if kernel_name == "Simplified":
        st.warning("Runner advancement is an uncalibrated approximation.")
    a,b,c = st.tabs(["Lineup", "Roster", "Download data"])
    with a:
        if len(pool) < 9:
            st.error("Need at least nine hitters")
        else:
            names = [p.name for p in pool]
            slots = st.columns(3)
            selected = [slots[i%3].selectbox(f"Batting {i+1}", names, index=i, key=f"bat{i}") for i in range(9)]
            if len(set(selected)) != 9:
                st.info("Choose nine distinct hitters.")
            else:
                selected_pool = {p.name:p for p in pool}
                lineup = [selected_pool[name] for name in selected]
                if st.button("Calculate expected runs", type="primary"):
                    try:
                        result = evaluate_lineup(lineup, kernel)
                        st.metric("Expected runs / 9 offensive innings", f"{result.total:.3f}")
                        st.line_chart(pd.DataFrame({"Expected runs by inning":result.per_inning}))
                    except Exception as exc:
                        st.error(str(exc))
                if st.button("Optimize batting order"):
                    try:
                        result = optimize_lineup(lineup, kernel, restarts=0, max_passes=5)
                        st.metric("Optimized expected runs", f"{result.expected_runs:.3f}")
                        st.dataframe(pd.DataFrame({"Order":range(1,10),"Batter":[h.name for h in result.lineup]}), hide_index=True)
                        st.caption("Local search; not guaranteed globally optimal.")
                    except Exception as exc:
                        st.error(str(exc))
    with b:
        st.caption("Nine-hitter salary-only optimization; positions are not yet enforced.")
        if len(pool) < 9 or any(p.salary <= 0 for p in pool):
            st.warning("Requires at least nine hitters with populated positive salaries.")
        else:
            minimum = sum(sorted(p.salary for p in pool)[:9])
            budget = st.number_input("Salary budget (USD)", value=float(max(minimum,60000000)), min_value=0.0, step=1000000.0)
            if st.button("Optimize roster"):
                try:
                    result = select_budget_roster(pool, budget, kernel, max_rounds=2, shortlist=3)
                    st.metric("Expected runs", f"{result.expected_runs:.3f}")
                    st.dataframe(pd.DataFrame({"Slot":range(1,10),"Batter":[p.name for p in result.lineup],"Salary":[p.salary for p in result.lineup]}),hide_index=True)
                except Exception as exc:
                    st.error(str(exc))
    with c:
        st.subheader("FanGraphs current projections")
        system = st.selectbox("Projection system", ["zips","steamer"])
        if st.button("Fetch FanGraphs"):
            try:
                payload, url = fetch_json(system)
                outcome = save_snapshot(system, DATA, payload=payload, source=url)
                st.success(f"Saved {outcome['included']} players to {outcome['csv']}")
            except Exception as exc:
                st.error(f"Download unavailable: {exc}. Use an authorized CSV export.")
        st.subheader("Retrosheet advancement")
        year = st.number_input("Season", min_value=1900, max_value=2025, value=2025)
        if st.button("Download and fit advancement"):
            try:
                path = download_season(int(year), BASE/"data"/"raw"/f"{year}plays.zip")
                fitted,report = fit_retrosheet(path)
                KERNELS.mkdir(parents=True, exist_ok=True)
                target = KERNELS/f"advancement_{year}.json"
                fitted.save(target)
                st.success(f"Saved {target}")
                st.json(report)
            except Exception as exc:
                st.error(str(exc))
    st.caption("Retrosheet data obtained free of charge and copyrighted by Retrosheet.")

if __name__ == "__main__":
    main()
