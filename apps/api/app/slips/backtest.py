"""Timestamp-safe Stage Five optimizer evaluation helpers."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _timestamp_contract(row: dict[str, Any], selection_time_key: str) -> tuple[bool, str | None]:
    selection = _parse_timestamp(row.get(selection_time_key))
    odds = _parse_timestamp(row.get("odds_observed_at"))
    prediction = _parse_timestamp(row.get("prediction_generated_at"))
    fixture_start = _parse_timestamp(row.get("fixture_start_at"))
    if not all((selection, odds, prediction, fixture_start)):
        return False, "missing_timestamp"
    if odds > selection:
        return False, "odds_observed_after_selection"
    if prediction > selection:
        return False, "prediction_generated_after_selection"
    is_prematch = str(row.get("mode", "prematch")).lower() in {"prematch", "pre_match"} and not row.get("is_live", False)
    if is_prematch and selection >= fixture_start:
        return False, "selection_not_before_fixture_start"
    final_at = _parse_timestamp(row.get("outcome_final_at") or row.get("final_at"))
    if final_at is not None and final_at < selection:
        return False, "outcome_available_before_selection"
    return True, None


def evaluate_optimizer_backtest(rows: list[dict[str, Any]], *, selection_time_key: str = "selection_at") -> dict[str, Any]:
    safe_rows: list[dict[str, Any]] = []
    rejected_leakage = 0
    missing_timestamps = 0
    rejection_reasons: dict[str, int] = {}
    for row in rows:
        valid, reason = _timestamp_contract(row, selection_time_key)
        if not valid:
            if reason == "missing_timestamp":
                missing_timestamps += 1
            else:
                rejected_leakage += 1
            rejection_reasons[reason or "invalid_timestamp"] = rejection_reasons.get(reason or "invalid_timestamp", 0) + 1
            continue
        safe_rows.append(row)
    safe_rows.sort(key=lambda row: _parse_timestamp(row.get(selection_time_key)) or datetime.min.replace(tzinfo=timezone.utc))
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in safe_rows:
        probability = float(row.get("predicted_joint_probability", row.get("probability", 0)))
        bucket = f"{min(9, max(0, int(probability * 10)))}0-{min(99, max(0, int(probability * 100)) + 9)}%"
        buckets[bucket].append(row)
    selected = [row for row in safe_rows if row.get("actual_all_legs_hit") is not None]
    hit_rate = sum(bool(row["actual_all_legs_hit"]) for row in selected) / len(selected) if selected else None
    return {
        "status": "PASS" if rejected_leakage == 0 else "REJECTED_LEAKAGE",
        "sample_count": len(selected),
        "evaluated_rows": len(safe_rows),
        "timestamp_safe_rows": len(safe_rows),
        "rejected_leakage_rows": rejected_leakage,
        "missing_timestamp_rows": missing_timestamps,
        "rejection_reasons": rejection_reasons,
        "target_achievement_rate": sum(bool(row.get("target_reached")) for row in safe_rows) / len(safe_rows) if safe_rows else None,
        "average_achieved_odds": sum(float(row.get("achieved_odds", 0)) for row in safe_rows) / len(safe_rows) if safe_rows else None,
        "average_legs": sum(int(row.get("leg_count", 0)) for row in safe_rows) / len(safe_rows) if safe_rows else None,
        "predicted_joint_probability": sum(float(row.get("predicted_joint_probability", 0)) for row in safe_rows) / len(safe_rows) if safe_rows else None,
        "actual_all_leg_hit_rate": hit_rate,
        "average_ev_estimate": sum(float(row.get("expected_value", 0)) for row in safe_rows) / len(safe_rows) if safe_rows else None,
        "correlation_risk_distribution": {risk: sum(1 for row in safe_rows if row.get("correlation_risk") == risk) for risk in {row.get("correlation_risk") for row in safe_rows if row.get("correlation_risk")}},
        "calibration_buckets": {key: {"count": len(items), "predicted": sum(float(item.get("predicted_joint_probability", 0)) for item in items) / len(items), "actual": sum(bool(item.get("actual_all_legs_hit")) for item in items) / len(items) if all(item.get("actual_all_legs_hit") is not None for item in items) else None} for key, items in buckets.items()},
        "limitation": "Synthetic or small samples do not establish betting accuracy or profitability.",
    }
