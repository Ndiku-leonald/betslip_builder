from __future__ import annotations

import csv
from pathlib import Path

from app.features.basketball import BasketballFeatureEngine
from app.features.football import FootballFeatureEngine


def build_dataset(db, sport: str, include_unfinished: bool = False):
    engine = BasketballFeatureEngine() if sport == "basketball" else FootballFeatureEngine()
    return engine.build(db, include_unfinished=include_unfinished)


def export_rows(rows, path: str) -> str:
    target = Path(path).resolve(); target.parent.mkdir(parents=True, exist_ok=True)
    records = [{"fixture_id": row.fixture_id, "sport": row.sport, "data_cutoff_at": row.data_cutoff_at.isoformat(), **row.values, **(row.actual or {})} for row in rows]
    if target.suffix.lower() == ".parquet":
        try:
            import pandas as pd
            pd.DataFrame(records).to_parquet(target, index=False)
        except ImportError as exc: raise RuntimeError("Parquet export needs pandas and a parquet engine") from exc
    else:
        keys = sorted({key for record in records for key in record})
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=keys); writer.writeheader(); writer.writerows(records)
    return str(target)
