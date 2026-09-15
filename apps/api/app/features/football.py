from __future__ import annotations

from datetime import datetime, timezone
from math import log1p

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.common import FeatureRow, load_history, mean, persist_features, safe_ratio
from app.features.quality import quality_score


class FootballFeatureEngine:
    feature_version = "football_features_v1"

    def __init__(self, minimum_history: int = 5, elo_initial: float = 1500.0, elo_k: float = 20.0, home_advantage: float = 60.0, windows: tuple[int, int] = (5, 10)) -> None:
        self.minimum_history, self.elo_initial, self.elo_k, self.home_advantage, self.windows = minimum_history, elo_initial, elo_k, home_advantage, windows

    def build(self, db: Session, include_unfinished: bool = False) -> list[FeatureRow]:
        from app.models import Fixture, Sport, TeamMatchStatistic
        sport_id = db.scalar(select(Sport.id).where(Sport.slug == "football"))
        fixtures = list(db.scalars(select(Fixture).where(Fixture.sport_id == sport_id, Fixture.kickoff_at.is_not(None)).order_by(Fixture.kickoff_at, Fixture.id))) if sport_id else []
        stats_rows = db.scalars(select(TeamMatchStatistic)).all()
        stats = {(item.fixture_id, item.team_id): item for item in stats_rows}
        histories: dict[str, list[dict]] = {}
        elos: dict[str, float] = {}
        competition_totals: dict[str, list[tuple[float, float]]] = {}
        output: list[FeatureRow] = []
        for fixture in fixtures:
            if fixture.kickoff_at is None:
                continue
            kickoff = fixture.kickoff_at if fixture.kickoff_at.tzinfo else fixture.kickoff_at.replace(tzinfo=timezone.utc)
            home_hist = histories.get(fixture.home_team_id, [])
            away_hist = histories.get(fixture.away_team_id, [])
            # Histories are only appended after a completed fixture below.
            values = self._values(home_hist, away_hist, elos.get(fixture.home_team_id, self.elo_initial), elos.get(fixture.away_team_id, self.elo_initial), competition_totals.get(fixture.competition_id or "", []), kickoff, stats, fixture)
            sample = min(len(home_hist), len(away_hist))
            stat_count = sum(1 for item in (home_hist[-self.windows[0]:] + away_hist[-self.windows[0]:]) if item.get("stats"))
            quality = quality_score(history_count=sample, minimum_history=self.minimum_history, stats_fraction=safe_ratio(stat_count, 2 * self.windows[0]), competition_seen=bool(competition_totals.get(fixture.competition_id or "")))
            actual = {"home_goals": float(fixture.home_score), "away_goals": float(fixture.away_score), "home_win": float(fixture.home_score > fixture.away_score), "draw": float(fixture.home_score == fixture.away_score), "away_win": float(fixture.home_score < fixture.away_score)} if fixture.status == "finished" and fixture.home_score is not None and fixture.away_score is not None else None
            if actual is not None or include_unfinished:
                output.append(FeatureRow(fixture.id, "football", kickoff, values, quality, actual))
            if actual is None:
                continue
            hg, ag = fixture.home_score, fixture.away_score
            home_hist = histories.setdefault(fixture.home_team_id, [])
            away_hist = histories.setdefault(fixture.away_team_id, [])
            home_hist.append({"kickoff": kickoff, "gf": hg, "ga": ag, "result": 1 if hg > ag else .5 if hg == ag else 0, "stats": stats.get((fixture.id, fixture.home_team_id)), "is_home": True})
            away_hist.append({"kickoff": kickoff, "gf": ag, "ga": hg, "result": 1 if ag > hg else .5 if hg == ag else 0, "stats": stats.get((fixture.id, fixture.away_team_id)), "is_home": False})
            competition_totals.setdefault(fixture.competition_id or "", []).append((float(hg), float(ag)))
            home_rating = elos.get(fixture.home_team_id, self.elo_initial)
            away_rating = elos.get(fixture.away_team_id, self.elo_initial)
            expected = 1 / (1 + 10 ** ((away_rating - (home_rating + self.home_advantage)) / 400))
            factor = 1 + 0.1 * log1p(abs(hg - ag))
            result = 1 if hg > ag else .5 if hg == ag else 0
            delta = self.elo_k * factor * (result - expected)
            elos[fixture.home_team_id], elos[fixture.away_team_id] = home_rating + delta, away_rating - delta
        return output

    def _values(self, home: list[dict], away: list[dict], home_elo: float, away_elo: float, comp: list[tuple[float, float]], kickoff: datetime, stats: dict, fixture) -> dict[str, float]:
        def window(items, n):
            return items[-n:]
        def rest(items):
            return max(0.0, (kickoff - items[-1]["kickoff"]).total_seconds() / 86400) if items else 30.0
        values = {"home_elo": home_elo, "away_elo": away_elo, "elo_diff": home_elo + self.home_advantage - away_elo, "home_rest_days": rest(home), "away_rest_days": rest(away), "home_matches_7d": float(sum((kickoff - x["kickoff"]).total_seconds() <= 7 * 86400 for x in home)), "away_matches_7d": float(sum((kickoff - x["kickoff"]).total_seconds() <= 7 * 86400 for x in away))}
        for n in self.windows:
            h, a = window(home, n), window(away, n)
            values.update({f"home_goals_for_avg_{n}": mean([x["gf"] for x in h], 1.3), f"home_goals_against_avg_{n}": mean([x["ga"] for x in h], 1.3), f"away_goals_for_avg_{n}": mean([x["gf"] for x in a], 1.0), f"away_goals_against_avg_{n}": mean([x["ga"] for x in a], 1.0), f"home_points_avg_{n}": mean([x["result"] * 3 if x["result"] != .5 else 1 for x in h], 1.5), f"away_points_avg_{n}": mean([x["result"] * 3 if x["result"] != .5 else 1 for x in a], 1.2), f"home_clean_sheet_rate_{n}": safe_ratio(sum(x["ga"] == 0 for x in h), len(h), .3), f"away_failed_to_score_rate_{n}": safe_ratio(sum(x["gf"] == 0 for x in a), len(a), .3)})
            for prefix, items in (("home", h), ("away", a)):
                shot_values = [x["stats"].shots for x in items if x.get("stats") and x["stats"].shots is not None]
                sot_values = [x["stats"].shots_on_target for x in items if x.get("stats") and x["stats"].shots_on_target is not None]
                xg_values = [x["stats"].expected_goals for x in items if x.get("stats") and x["stats"].expected_goals is not None]
                if shot_values: values[f"{prefix}_shots_avg_{n}"] = mean(shot_values)
                if sot_values: values[f"{prefix}_shots_on_target_avg_{n}"] = mean(sot_values)
                if xg_values: values[f"{prefix}_xg_avg_{n}"] = mean(xg_values)
        values["league_home_goals_avg"] = mean([x[0] for x in comp], 1.3)
        values["league_away_goals_avg"] = mean([x[1] for x in comp], 1.0)
        return values

    def build_and_persist(self, db: Session, include_unfinished: bool = True) -> list[FeatureRow]:
        rows = self.build(db, include_unfinished)
        persist_features(db, rows, self.feature_version)
        return rows
