from typing import Any


def quality_score(*, history_count: int, minimum_history: int, stats_fraction: float, competition_seen: bool) -> dict[str, Any]:
    history = min(100.0, 100.0 * history_count / max(1, minimum_history * 2))
    recent = min(100.0, 100.0 * history_count / max(1, minimum_history))
    stats = max(0.0, min(100.0, stats_fraction * 100.0))
    competition = 100.0 if competition_seen else 50.0
    overall = round(0.35 * history + 0.30 * recent + 0.20 * stats + 0.15 * competition, 2)
    return {"historical_sample": round(history, 2), "recent_form": round(recent, 2), "statistics_completeness": round(stats, 2), "competition_coverage": round(competition, 2), "overall": overall, "history_count": history_count}
