"""Retrosheet parsed play-by-play loader and empirical advancement estimation.

Source: https://www.retrosheet.org/downloads/plays.html

The information used here was obtained free of charge from and is copyrighted
by Retrosheet. Interested parties may contact Retrosheet at 20 Sunset Rd.,
Newark, DE 19711.
"""
from __future__ import annotations

from collections import Counter
import csv
import io
import json
import math
from pathlib import Path
from urllib.request import Request, urlopen
from zipfile import ZipFile

from .advancement import AdvancementKernel
from .events import Event

URL_TEMPLATE = "https://www.retrosheet.org/downloads/plays/{year}plays.zip"
COLUMNS = ("pa", "single", "double", "triple", "hr", "hbp", "walk", "k",
           "outs_pre", "outs_post", "br1_pre", "br2_pre", "br3_pre",
           "br1_post", "br2_post", "br3_post", "runs")


def download_season(year: int, destination: str | Path, timeout: int = 90) -> Path:
    if not 1900 <= year <= 2100:
        raise ValueError("Invalid season")
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".partial")
    req = Request(URL_TEMPLATE.format(year=year),
                  headers={"User-Agent": "baseball-run-engine/0.2 (research)"})
    try:
        with urlopen(req, timeout=timeout) as src, temp.open("wb") as out:
            while block := src.read(1024 * 1024):
                out.write(block)
        with ZipFile(temp) as z:
            if z.testzip() is not None:
                raise ValueError("Corrupt Retrosheet archive")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    return path


def _as_int(value, field: str) -> int:
    try:
        return int(str(value).strip())
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid {field}: {value!r}") from exc


def _occupied(value) -> bool:
    return str(value or "").strip().lower() not in ("", "nan", "none", "null", "0")


def _bases(row, suffix: str) -> int:
    return sum(1 << i for i in (0, 1, 2) if _occupied(row[f"br{i + 1}_{suffix}"]))


def _event(row) -> Event:
    for field, kind in (
        ("single", Event.SINGLE), ("double", Event.DOUBLE),
        ("triple", Event.TRIPLE), ("hr", Event.HR), ("walk", Event.BB),
        ("hbp", Event.HBP), ("k", Event.K),
    ):
        if _as_int(row[field] or "0", field) == 1:
            return kind
    return Event.OUT  # Sacrifices, FC, ROE, interference, and other PA outs.


def iter_plays(path: str | Path):
    path = Path(path)
    if path.suffix == ".zip":
        with ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if len(names) != 1:
                raise ValueError(f"Expected exactly one CSV; found {names}")
            with z.open(names[0]) as inp:
                with io.TextIOWrapper(inp, encoding="utf-8-sig", newline="") as text:
                    reader = csv.DictReader(text)
                    _check_fields(reader.fieldnames)
                    yield from reader
    else:
        with path.open(newline="", encoding="utf-8-sig") as inp:
            reader = csv.DictReader(inp)
            _check_fields(reader.fieldnames)
            yield from reader


def _check_fields(fields):
    missing = sorted(set(COLUMNS).difference(fields or ()))
    if missing:
        raise ValueError(f"Missing Retrosheet columns: {missing}")


def read_observations(path: str | Path):
    counts = Counter()
    report = Counter()
    for row in iter_plays(path):
        report["total_rows"] += 1
        if str(row["pa"]).strip() != "1":
            report["non_pa_rows"] += 1
            try:
                report["runs_on_non_pa_plays"] += _as_int(row["runs"], "runs")
            except ValueError:
                report["bad_non_pa_runs"] += 1
            continue
        report["pa_rows"] += 1
        try:
            event = _event(row)
            outs, nxt = (_as_int(row[c], c) for c in ("outs_pre", "outs_post"))
            runs = _as_int(row["runs"], "runs")
            if not (0 <= outs <= 2 and outs <= nxt <= 3 and 0 <= runs <= 4):
                raise ValueError("Invalid outs or runs")
            bases = _bases(row, "pre")
            final_bases = 0 if nxt == 3 else _bases(row, "post")
            if runs > bases.bit_count() + 1:
                raise ValueError("Runs exceed runners + batter")
        except ValueError:
            report["skipped_bad_pa"] += 1
            continue
        counts[(int(event), outs, bases, nxt, final_bases, runs)] += 1
        report["accepted_pa"] += 1
        report["runs_on_pa_plays"] += runs
        report[f"event_{event.name}"] += 1
    if not counts:
        raise ValueError("No valid Retrosheet plate appearances found")
    report["contexts"] = len({key[:3] for key in counts})
    report["unique_transitions"] = len(counts)
    return counts, dict(report)


def fit_retrosheet(path: str | Path, prior_strength: float = 5.0):
    counts, report = read_observations(path)
    return AdvancementKernel.from_counts(counts, prior_strength), report


def transition_logloss(kernel: AdvancementKernel, path: str | Path,
                       floor: float = 1e-8):
    """Held-out per-PA transition log loss, with a scoring floor for unseen events."""
    counts, _ = read_observations(path)
    total = sum(counts.values())
    loss = unseen = 0.0
    for (event, outs, bases, nxt, next_bases, runs), n in counts.items():
        prob = next((t.probability for t in kernel.outcomes(Event(event), outs, bases)
                     if (t.outs, t.bases, t.runs) == (nxt, next_bases, runs)), 0.0)
        if prob == 0.0:
            unseen += n
        loss -= n * math.log(max(prob, floor))
    return {"heldout_pa": total, "average_nll": loss / total,
            "fraction_unseen": unseen / total, "heldout_source": str(path)}


def write_report(report: dict, path: str | Path):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n")
