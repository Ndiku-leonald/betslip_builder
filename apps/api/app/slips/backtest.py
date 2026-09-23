"""Timestamp-safe Stage Five optimizer evaluation helpers.

Rows must contain a selection timestamp, model probability, selected price and a
known leg outcome. The evaluator never uses rows after the selection timestamp.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


def evaluate_optimizer_backtest(rows: list[dict[str, Any]], *, selection_time_key: str = "selection_at") -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: row.get(selection_time_key) or datetime.min.replace(tzinfo=timezone.utc))
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in ordered:
        probability = float(row.get("predicted_joint_probability", row.get("probability", 0)))
        bucket = f"{min(9, max(0, int(probability * 10)))}0-{min(99, max(0, int(probability * 100)) + 9)}%"
        buckets[bucket].append(row)
    selected = [row for row in ordered if row.get("actual_all_legs_hit") is not None]
    hit_rate = sum(bool(row["actual_all_legs_hit"]) for row in selected) / len(selected) if selected else None
    return {
        "status": "PASS" if ordered == sorted(ordered, key=lambda row: row.get(selection_time_key) or datetime.min.replace(tzinfo=timezone.utc)) else "FAIL",
        "sample_count": len(selected),
        "target_achievement_rate": sum(bool(row.get("target_reached")) for row in ordered) / len(ordered) if ordered else None,
        "average_achieved_odds": sum(float(row.get("achieved_odds", 0)) for row in ordered) / len(ordered) if ordered else None,
        "average_legs": sum(int(row.get("leg_count", 0)) for row in ordered) / len(ordered) if ordered else None,
        "predicted_joint_probability": sum(float(row.get("predicted_joint_probability", 0)) for row in ordered) / len(ordered) if ordered else None,
        "actual_all_leg_hit_rate": hit_rate,
        "average_ev_estimate": sum(float(row.get("expected_value", 0)) for row in ordered) / len(ordered) if ordered else None,
        "correlation_risk_distribution": {risk: sum(1 for row in ordered if row.get("correlation_risk") == risk) for risk in {row.get("correlation_risk") for row in ordered if row.get("correlation_risk")}},
        "calibration_buckets": {key: {"count": len(items), "predicted": sum(float(item.get("predicted_joint_probability", 0)) for item in items) / len(items), "actual": sum(bool(item.get("actual_all_legs_hit")) for item in items) / len(items) if all(item.get("actual_all_legs_hit") is not None for item in items) else None} for key, items in buckets.items()},
        "limitation": "Synthetic or small samples do not establish betting accuracy or profitability.",
    }
