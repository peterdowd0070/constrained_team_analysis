"""Load estimated MLB service time (172 credited days per service year).

Data source: RainbowMang0/MLB-Service-Time-Tracker, a NON-OFFICIAL,
transaction-derived feed. Players with missing seasons have lower bounds,
not verified service totals. The official MLB/MLBPA ledger is not public.
"""
from __future__ import annotations
from datetime import datetime, timezone
import csv
import json
import hashlib
from pathlib import Path
from urllib.request import Request, urlopen

SOURCE_URL = ("https://raw.githubusercontent.com/RainbowMang0/"
              "MLB-Service-Time-Tracker/main/docs/data/index.json")
DAYS_PER_YEAR = 172

def parse_service_days(value: object) -> int:
    """Parse MLB Y.DDD notation, e.g. '2.045' -> 389 credited days."""
    if value is None or str(value).strip() == "":
        raise ValueError("Missing service time")
    s = str(value).strip()
    if "." in s:
        year, days = s.split(".", 1)
        if not year.isdigit() or not days.isdigit() or len(days) != 3:
            raise ValueError("Use MLB service notation Y.DDD, e.g. 2.045")
        y, d = int(year), int(days)
        if not 0 <= d < DAYS_PER_YEAR:
            raise ValueError("Service-time day component must be 000..171")
        return DAYS_PER_YEAR * y + d
    if not s.isdigit():
        raise ValueError(f"Invalid service time: {s!r}")
    return int(s) * DAYS_PER_YEAR

def format_service_days(days: int) -> str:
    if days < 0: raise ValueError("Negative service days")
    return f"{days // DAYS_PER_YEAR}.{days % DAYS_PER_YEAR:03d}"

def _base_record(row: dict) -> dict:
    # Deliberately match salary schema: IDs are MLBAM and *not* FGIDs.
    return {"name": str(row["name"]).strip(),
            "mlbam_id": str(row.get("mlbam_id", "")).strip(),
            "team": str(row.get("team", "")).strip(),
            "days": int(row["days"]),
            "missing_seasons": int(row.get("missing_seasons", 0)),
            "estimated": bool(row.get("estimated", True))}

def read_service_time(path: str | Path) -> list[dict]:
    """Read the tracker compact JSON index or an authorized service-time CSV."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        fields = data.get("fields")
        players = data.get("players")
        teams = data.get("teams")
        if not isinstance(fields, list) or not isinstance(players, list) or not isinstance(teams, list):
            raise ValueError("Unexpected service-time index schema")
        required = {"id", "name", "team", "days", "missing_seasons"}
        if not required.issubset(set(fields)):
            raise ValueError("Missing service-time index fields")
        results = []
        for row in players:
            if len(row) != len(fields):
                raise ValueError("Malformed service-time player row")
            p = dict(zip(fields, row))
            idx = int(p["team"])
            if not 0 <= idx < len(teams):
                raise ValueError("Service index team out of bounds")
            results.append(_base_record({
                "name": p["name"],
                "mlbam_id": p["id"],
                "team": teams[idx],
                "days": p["days"],
                "missing_seasons": p["missing_seasons"],
                "estimated": True}))
        return results
    if path.suffix.lower() != ".csv":
        raise ValueError("Service-time source must be .json or .csv")
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows: raise ValueError("Empty service-time CSV")
    result = []
    for row in rows:
        normalized = {str(k).lower().replace("_","").replace(" ",""):v
                      for k,v in row.items() if k is not None}
        def val(*keys, default=""):
            for key in keys:
                item = normalized.get(key.lower().replace("_","").replace(" ",""))
                if item is not None and str(item).strip() != "":
                    return item
            return default
        d = val("ServiceDays","ServiceTimeDays")
        days = int(float(d)) if d != "" else parse_service_days(
            val("ServiceTime","Service"))
        result.append(_base_record({
            "name": val("Name","Player"),
            "mlbam_id": val("MLBID","MLBAMID","PersonID"),
            "team": val("Team"),
            "days": days,
            "missing_seasons": val("MissingSeasons",default=0),
            "estimated": str(val("Estimated",default="true")).lower() not in ("0","false","no")}))
    return result

def download_service_index(directory: str | Path, timeout: int=8) -> tuple[Path,dict]:
    request = Request(SOURCE_URL, headers={"User-Agent":"baseball-run-engine/0.4 (research)",
                                            "Accept":"application/json"})
    with urlopen(request, timeout=timeout) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Service-time index unexpectedly large")
    directory = Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    stamp = datetime.now(timezone.utc)
    out = directory / f"service_index_{stamp:%Y%m%dT%H%M%SZ}.json"
    out.write_bytes(raw)
    try:
        records = read_service_time(out)
        if len(records) < 500:
            raise ValueError("Incomplete service-time index")
    except Exception:
        out.unlink(missing_ok=True)
        raise
    obj = json.loads(raw)
    metadata = {"source":SOURCE_URL,"retrieved_utc":stamp.isoformat(),
                "generated_at":obj.get("generated_at"),"players":len(records),
                "sha256":hashlib.sha256(raw).hexdigest(),
                "official":False,"description":"Transaction-derived estimates; some players have service-time lower bounds"}
    out.with_suffix(".manifest.json").write_text(json.dumps(metadata,indent=2)+"\n")
    return out, metadata
