"""Exploratory extraction of empirical advancement kernels from Statcast pitch CSV.

Infer next base/out state from next PA in the same half-inning; exclude ambiguous
boundaries. NOT a complete official play-by-play scoring reconstruction.
"""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import pandas as pd
from .advancement import AdvancementKernel
from .events import Event

MAP_EVENTS={
    "strikeout":Event.K,"strikeout_double_play":Event.K,
    "walk":Event.BB,"intent_walk":Event.BB,"hit_by_pitch":Event.HBP,
    "single":Event.SINGLE,"double":Event.DOUBLE,"triple":Event.TRIPLE,
    "home_run":Event.HR,"field_out":Event.OUT,"force_out":Event.OUT,
    "grounded_into_double_play":Event.OUT,"double_play":Event.OUT,
    "triple_play":Event.OUT,"sac_fly":Event.OUT,"sac_bunt":Event.OUT,
    "fielders_choice_out":Event.OUT,"other_out":Event.OUT}
REQUIRED={"game_pk","inning","inning_topbot","at_bat_number","pitch_number",
          "events","outs_when_up","on_1b","on_2b","on_3b","bat_score","post_bat_score"}

def fit_kernel_from_statcast(path:str|Path,prior_strength:float=10.0):
    raw=pd.read_csv(path,usecols=lambda c:c in REQUIRED,low_memory=False)
    missing=REQUIRED-set(raw.columns)
    if missing: raise ValueError(f"Missing Statcast columns: {sorted(missing)}")
    raw=raw[raw.events.notna()].copy()
    raw=raw.sort_values(["game_pk","at_bat_number","pitch_number"])
    raw=raw.drop_duplicates(["game_pk","at_bat_number"],keep="last")
    raw["next_game"]=raw.game_pk.shift(-1)
    raw["next_inning"]=raw.inning.shift(-1)
    raw["next_half"]=raw.inning_topbot.shift(-1)
    raw["next_outs"]=raw.outs_when_up.shift(-1)
    for base in ("on_1b","on_2b","on_3b"):
        raw["next_"+base]=raw[base].shift(-1)
    raw=raw.loc[raw.events.isin(MAP_EVENTS)]
    counts=Counter(); skips=Counter()
    for row in raw.itertuples(index=False):
        ev=MAP_EVENTS[row.events]
        if pd.isna(row.outs_when_up) or pd.isna(row.bat_score) or pd.isna(row.post_bat_score):
            skips["missing_score_or_outs"]+=1; continue
        outs=int(row.outs_when_up)
        if not 0<=outs<=2: skips["bad_pre_outs"]+=1; continue
        bases=int(pd.notna(row.on_1b))|(int(pd.notna(row.on_2b))<<1)|(int(pd.notna(row.on_3b))<<2)
        runs=int(round(float(row.post_bat_score)-float(row.bat_score)))
        if not 0<=runs<=4: skips["bad_run_delta"]+=1; continue
        same=(row.next_game==row.game_pk and row.next_inning==row.inning
              and row.next_half==row.inning_topbot)
        if same:
            if pd.isna(row.next_outs): skips["missing_next_outs"]+=1; continue
            new_outs=int(row.next_outs)
            new_bases=int(pd.notna(row.next_on_1b))|(int(pd.notna(row.next_on_2b))<<1)|(int(pd.notna(row.next_on_3b))<<2)
        elif row.next_game==row.game_pk and (
            (outs==2 and ev in (Event.K,Event.OUT)) or
            (outs==1 and row.events in ("grounded_into_double_play","double_play","strikeout_double_play")) or
            (outs==0 and row.events=="triple_play")):
            new_outs,new_bases=3,0
        else:
            skips["ambiguous_end_of_half"]+=1; continue
        if not outs<=new_outs<=3 or (new_outs==3 and new_bases!=0):
            skips["invalid_outs"]+=1; continue
        counts[(int(ev),outs,bases,new_outs,new_bases,runs)]+=1
    kernel=AdvancementKernel.from_counts(counts,prior_strength)
    return kernel,{"observations":sum(counts.values()),"contexts":len(kernel.observations),
                   **{f"skipped_{k}":v for k,v in skips.items()}}
