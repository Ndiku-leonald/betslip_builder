from __future__ import annotations

from app.config import get_settings


def rank_live_markets(values: list[dict], *, profile: str = "balanced") -> list[dict]:
    """Transparent live ranking; all hard gates remain visible in the payload."""
    settings = get_settings()
    thresholds = {"conservative": (0.60, 60.0, 0.02), "balanced": (0.53, settings.live_min_confidence, 0.01), "aggressive": (0.45, 35.0, 0.03)}.get(profile, (0.53, settings.live_min_confidence, 0.01))
    result = []
    for item in values:
        status = item.get("status")
        freshness = item.get("freshness", {})
        probability = item.get("model_resolved_win_probability") if item.get("model_resolved_win_probability") is not None else item.get("model_probability")
        edge = item.get("novig_probability_edge")
        calibration = item.get("calibration_status", "INSUFFICIENT_EVIDENCE")
        gates = {
            "market_open": status == "CURRENT" and item.get("market_status", "unknown") == "open",
            "price_fresh": freshness.get("status") == "CURRENT",
            "probability_available": probability is not None,
            "data_quality": float(item.get("data_quality", 0)) >= settings.live_min_quality * 100,
            "confidence": float(item.get("confidence", 0)) >= thresholds[1],
            "edge": edge is not None and edge >= thresholds[2],
            "calibration": calibration in {"CALIBRATED", "PARTIALLY_CALIBRATED", "fitted", "family_fitted", "raw_dynamic_line"},
        }
        eligible = all(gates.values()) and probability >= thresholds[0]
        item = dict(item)
        item["suitability"] = "ELIGIBLE" if eligible else "NOT_ELIGIBLE"
        item["ranking_components"] = {"probability": probability, "edge": edge, "data_quality": item.get("data_quality"), "confidence": item.get("confidence"), "freshness": freshness, "calibration_status": calibration, "gates": gates}
        if eligible:
            item["ranking_score"] = round(100 * (0.28 * float(probability) + 0.20 * float(item.get("confidence", 0)) / 100 + 0.18 * float(item.get("data_quality", 0)) / 100 + 0.14 * min(1, max(0, float(edge))) + 0.10 * min(1, max(0, float(item.get("expected_value", 0) or 0))) + 0.10 * (1 if freshness.get("status") == "CURRENT" else 0)), 2)
            result.append(item)
    return sorted(result, key=lambda item: item["ranking_score"], reverse=True)
