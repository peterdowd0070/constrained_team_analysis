"""Adapter for common FanGraphs-style ZiPS/Steamer CSV exports.

No forecast provider is bundled, scraped, or silently substituted. Run-level
accuracy depends on the user's actual projected event totals.
"""
from __future__ import annotations
import csv
from pathlib import Path
import math
from .events import Event, Hitter


def _get(row: dict[str, str], names: tuple[str, ...], *, default=None):
    lower = {str(k).strip().lower(): v for k, v in row.items() if k is not None}
    for key in names:
        value = lower.get(key.lower())
        if value is not None and str(value).strip() != "":
            return value
    if default is not None:
        return default
    raise ValueError(f"Missing required projection column: one of {names}")


def _number(row, names, default=None) -> float:
    value = _get(row, names, default=default)
    try:
        f = float(str(value).replace(",", "").replace("$", ""))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Non-numeric projection field {names}: {value!r}") from exc
    if not math.isfinite(f) or f < 0:
        raise ValueError(f"Invalid projection value {names}: {f}")
    return f


def from_projection_row(row: dict[str, str]) -> Hitter:
    """Create mutually exclusive outcomes from *projected counting stats*.

    PA,H,2B,3B,HR,BB,SO required. HBP optional (assumed 0 if absent).
    Non-K outs are the remainder; this lumps SF/SH/CI and FC into outs.
    Rounded projections may differ by a fraction; severe inconsistency fails.
    """
    name = str(_get(row, ("Name", "Player", "player_name")))
    pa = _number(row, ("PA",))
    if pa <= 0:
        raise ValueError(f"{name}: PA must be positive")
    h = _number(row, ("H", "Hits"))
    doubles = _number(row, ("2B", "Doubles"))
    triples = _number(row, ("3B", "Triples"))
    hr = _number(row, ("HR", "Home Runs"))
    bb = _number(row, ("BB", "Walks"))
    hbp = _number(row, ("HBP", "Hit By Pitch"), default=0)
    k = _number(row, ("SO", "K", "Strikeouts"))
    singles = h - doubles - triples - hr
    ordinary_outs = pa - h - bb - hbp - k
    if singles < -0.51 or ordinary_outs < -0.51:
        raise ValueError(f"{name}: mutually inconsistent counting stats")
    singles, ordinary_outs = max(0.0, singles), max(0.0, ordinary_outs)
    counts = [k, ordinary_outs, bb, hbp, singles, doubles, triples, hr]
    total = sum(counts)
    if total <= 0:
        raise ValueError(f"{name}: invalid projected totals")
    probabilities = tuple(x / total for x in counts)
    salary = _number(row, ("Salary", "salary_usd", "cost"), default=0)
    raw_positions = str(_get(row, ("Positions", "Position", "Pos"), default=""))
    positions = tuple(x.strip().upper() for x in raw_positions.replace("/", ",").split(",") if x.strip())
    return Hitter(name=name, probabilities=probabilities, salary=salary, positions=positions)


def read_projection_csv(path: str | Path) -> list[Hitter]:
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"Projection CSV is empty: {path}")
    hitters = [from_projection_row(row) for row in rows]
    names = [h.name for h in hitters]
    if len(set(names)) != len(names):
        raise ValueError("Duplicate names in projection CSV; filter/aggregate players first")
    return hitters


def write_event_probabilities(hitters: list[Hitter], path: str | Path) -> None:
    with Path(path).open("w", newline="", encoding="utf8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Name", *[e.name for e in Event], "Salary", "Positions"])
        for h in hitters:
            writer.writerow([h.name, *[f"{p:.9f}" for p in h.probabilities], h.salary,
                             ",".join(h.positions)])
