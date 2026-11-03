# Constrained Team Analysis — Baseball Run Engine

Research MVP for batting-order and salary-constrained roster analysis using a **216-state Markov reward model**.

The repository separates player projections, runner advancement, exact run evaluation, Monte Carlo simulation, and heuristic optimization. The GUI requires imported player projections and never silently substitutes fictional players. Synthetic fixture players remain in the test/examples directory only. Live ZiPS/Steamer downloads are attempted where FanGraphs permits access, but have not been verified against a live response in this environment.

## Install

```bash
python -m pip install -e '.[dev]'
pytest -q
```

## Browser GUI

Install the optional GUI dependencies and start the Streamlit interface from the repository root:

```bash
python -m pip install -e '.[gui]'
python -m streamlit run src/baseball_run_engine/gui.py
```

The dark OOTP-inspired front office presents a nine-player lineup card, baseball diamond, expected-run panel, and quick/thorough lineup optimization. It loads imported Steamer/ZiPS projections (not synthetic players by default), supports salary-only roster selection, CSV upload, FanGraphs fetch attempts, and Retrosheet parsed-play acquisition. The interface is a local Streamlit application, not a hosted website.

## Retrosheet advancement

Use the GUI's **Download and fit advancement** action to retrieve a season of Retrosheet parsed play data and fit an empirical advancement kernel. See the module `src/baseball_run_engine/retrosheet.py`. Historical parsed play files and access are subject to Retrosheet availability. The resulting kernel does not yet model steals or wild pitches occurring between plate appearances.

Retrosheet material is obtained free of charge and copyrighted by Retrosheet.

## Example commands

```bash
baseball-runs evaluate --projections examples/fictional_projections.csv
baseball-runs simulate --projections examples/fictional_projections.csv --games 10000
baseball-runs optimize --projections examples/fictional_projections.csv --restarts 2
baseball-runs select --projections examples/fictional_projections.csv --budget 65000000
```

To specify nine batters in order, use `--lineup "Name One,Name Two,..."` (all nine must appear in the projections CSV).

## Download ZiPS and Steamer from FanGraphs

The adapter follows the public [baseballr fg_projections documentation](https://billpetti.github.io/baseballr/reference/fg_projections.html):

`https://www.fangraphs.com/api/projections?type=steamer&stats=bat&pos=all&team=0&players=0&lg=all`

For ZiPS, change `type=steamer` to `type=zips`. These are **current/live** projections, not archived historical snapshots; the FanGraphs endpoint may restrict direct access or change its response schema.

```bash
baseball-runs fetch-projections --system both --out-dir data/projections
# Offline fallback: obtain a permitted CSV export from FanGraphs
baseball-runs fetch-projections --system steamer --csv downloaded-steamer.csv --out-dir data/projections
baseball-runs fetch-projections --system zips --csv downloaded-zips.csv --out-dir data/projections
# Use returned timestamped filenames:
baseball-runs blend-projections --steamer data/projections/steamer_TIMESTAMP.csv --zips data/projections/zips_TIMESTAMP.csv --output data/projections/blend.csv
baseball-runs evaluate --projections data/projections/blend.csv
```

FanGraphs historical *full-season* projections are a member feature. For defensible backtests, preserve dated pre-season snapshots, because live forecasts are updated through the season. The importer saves normalized CSV, a provenance manifest, and raw JSON for successful API pulls. It never bypasses access controls.

For independent R-based verification, use `baseballr::fg_projections(type="steamer",stats="bat")` or `type="zips"`.

**Important:** FanGraphs batting projections do not provide salary. The loader defaults missing salary to zero. Merge actual salaries before using `select`; a salary optimization performed without salary data is meaningless. The blend joins by FanGraphs player ID and averages *per-PA outcome rates*, not raw projected counts.

## Architecture

```text
src/baseball_run_engine/
  events.py        # PA categories and Hitter
  projections.py   # projected counts -> eight PA event probabilities
  fangraphs.py     # ZiPS/Steamer JSON API and CSV snapshots
  blend.py         # projection blend by FanGraphs ID
  state.py         # (outs, occupied bases, next batter) indexing
  advancement.py   # state transition kernel / smoothing
  statcast.py      # experimental empirical transition fitter
  retrosheet.py    # parsed-play advancement fit and validation
  gui.py           # Streamlit browser application
  markov.py        # exact reference evaluator (dense)
  fast_markov.py   # cached sparse LU evaluator for lineup and roster search
  ui_components.py # OOTP-inspired lineup card and styling
  monte_carlo.py   # stochastic validation
  optimize.py      # heuristic lineup and roster search
  cli.py           # console application
tests/             # regression / contract tests
docs/              # equations and limitations
```

Each hitter has categorical outcomes `K, OUT, BB, HBP, SINGLE, DOUBLE, TRIPLE, HR`. The Markov system uses 216 transient states (3 outs x 8 base masks x 9 batter slots). Solve `(I-Q)v=g` for expected inning runs and `(I-Q)F=H` for the distribution of next-inning leadoff hitters; propagate across nine offensive innings. See [model formulation](docs/mathematical_model.md).

## Empirical advancement (experimental)

```bash
baseball-runs fit-advancement --statcast path/to/statcast.csv --output data/advancement.json
baseball-runs evaluate --projections my_predictions.csv --kernel data/advancement.json
```

Requires `game_pk, inning, inning_topbot, at_bat_number, pitch_number, events, outs_when_up, on_1b, on_2b, on_3b, bat_score, post_bat_score`. The estimator uses the subsequent PA's pre-state as an approximate previous PA after-state; it drops ambiguous records and needs external play-by-play validation.

## Limitations

* The fallback advancement model is a *simplified deterministic rule*, not an empirically accurate MLB process; double plays, steals, sac flies, and errors need improved treatment.
* All eight PA event rates are unconditional; no park, pitcher, handedness, game-state or substitution effects.
* Evaluation models nine complete **offensive** innings (not 8.5, walk-offs, extra innings).
* `optimize` and `select` are local heuristics and do not guarantee global optimality.
* Roster selection presently enforces **salary only**, not positional eligibility, bench or availability.
* Before comparing real roster options, calibrate advancement, validate projected totals, and benchmark forecast-vs-actual runs.

## Next steps

Integrate validated play-by-play advancement; freeze preseason ZiPS/Steamer datasets and backtest; add positional eligibility and lineup platoons; propagate projection uncertainty; optionally connect the 14-zone batting model.

## Performance

The optimizer uses `FastRunEngine` to compile the base/out advancement kernel once, cache each player's event-conditioned 24-state matrices, and solve the sparse 216-state linear system for each batting order. The original dense solver remains the correctness reference. The GUI diagnostics tab offers a one-lineup timing and numerical comparison; speedups depend on data and hardware. Avoid interpreting heuristic lineup search as exhaustive 9! optimization.
