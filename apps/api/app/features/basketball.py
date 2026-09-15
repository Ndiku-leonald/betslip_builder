from __future__ import annotations

from datetime import timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.common import FeatureRow, mean, persist_features, safe_ratio
from app.features.quality import quality_score
from app.models import Fixture, Sport, TeamMatchStatistic


class BasketballFeatureEngine:
    feature_version = "basketball_features_v1"

    def __init__(self, minimum_history: int = 5, elo_initial: float = 1500.0, elo_k: float = 18.0, home_advantage: float = 65.0) -> None:
        self.minimum_history, self.elo_initial, self.elo_k, self.home_advantage = minimum_history, elo_initial, elo_k, home_advantage

    def build(self, db: Session, include_unfinished: bool = False) -> list[FeatureRow]:
        sport_id = db.scalar(select(Sport.id).where(Sport.slug == "basketball"))
        fixtures = list(db.scalars(select(Fixture).where(Fixture.sport_id == sport_id, Fixture.kickoff_at.is_not(None)).order_by(Fixture.kickoff_at, Fixture.id))) if sport_id else []
        stat_rows = db.scalars(select(TeamMatchStatistic)).all()
        stats = {(x.fixture_id, x.team_id): x for x in stat_rows}
        history: dict[str, list[dict]] = {}
        elo: dict[str, float] = {}
        output: list[FeatureRow] = []
        index = 0
        while index < len(fixtures):
            kickoff = fixtures[index].kickoff_at if fixtures[index].kickoff_at.tzinfo else fixtures[index].kickoff_at.replace(tzinfo=timezone.utc)
            batch = []
            while index < len(fixtures):
                candidate = fixtures[index].kickoff_at if fixtures[index].kickoff_at.tzinfo else fixtures[index].kickoff_at.replace(tzinfo=timezone.utc)
                if candidate != kickoff: break
                batch.append(fixtures[index]); index += 1
            staged = []
            for fixture in batch:
                home, away = history.get(fixture.home_team_id, []), history.get(fixture.away_team_id, [])
                values = self._values(home, away, elo.get(fixture.home_team_id, self.elo_initial), elo.get(fixture.away_team_id, self.elo_initial), kickoff)
                stat_count = sum(1 for x in (home[-10:] + away[-10:]) if x.get("stats"))
                comp_count = sum(1 for x in history.get(f"competition:{fixture.competition_id}", []))
                quality = quality_score(history_count=min(len(home), len(away)), minimum_history=self.minimum_history, stats_fraction=safe_ratio(stat_count, 20), competition_seen=comp_count > 0, competition_sample=comp_count)
                actual = {"home_points": float(fixture.home_score), "away_points": float(fixture.away_score), "home_win": float(fixture.home_score > fixture.away_score), "away_win": float(fixture.home_score < fixture.away_score), "margin": float(fixture.home_score - fixture.away_score), "total": float(fixture.home_score + fixture.away_score)} if fixture.status == "finished" and fixture.home_score is not None and fixture.away_score is not None else None
                if actual is not None or include_unfinished: output.append(FeatureRow(fixture.id, "basketball", kickoff, values, quality, actual))
                staged.append((fixture, actual))
            for fixture, actual in staged:
                if actual is None: continue
                hp, ap = fixture.home_score, fixture.away_score
                history.setdefault(fixture.home_team_id, []).append({"kickoff": kickoff, "pf": hp, "pa": ap, "margin": hp - ap, "stats": stats.get((fixture.id, fixture.home_team_id))})
                history.setdefault(fixture.away_team_id, []).append({"kickoff": kickoff, "pf": ap, "pa": hp, "margin": ap - hp, "stats": stats.get((fixture.id, fixture.away_team_id))})
                history.setdefault(f"competition:{fixture.competition_id}", []).append({"kickoff": kickoff})
                hr, ar = elo.get(fixture.home_team_id, self.elo_initial), elo.get(fixture.away_team_id, self.elo_initial)
                elo[fixture.home_team_id], elo[fixture.away_team_id] = self.update_ratings(hr, ar, hp, ap)
        return output

    def _values(self, home: list[dict], away: list[dict], home_elo: float, away_elo: float, kickoff) -> dict[str, float]:
        def rest(items): return max(0.0, (kickoff - items[-1]["kickoff"]).total_seconds() / 86400) if items else 14.0
        values = {"home_elo": home_elo, "away_elo": away_elo, "elo_diff": home_elo + self.home_advantage - away_elo, "home_rest_days": rest(home), "away_rest_days": rest(away), "home_back_to_back": float(bool(home and (kickoff - home[-1]["kickoff"]).total_seconds() <= 36 * 3600)), "away_back_to_back": float(bool(away and (kickoff - away[-1]["kickoff"]).total_seconds() <= 36 * 3600))}
        for n in (5, 10):
            h, a = home[-n:], away[-n:]
            values.update({f"home_points_for_avg_{n}": mean([x["pf"] for x in h], 105), f"home_points_against_avg_{n}": mean([x["pa"] for x in h], 105), f"away_points_for_avg_{n}": mean([x["pf"] for x in a], 102), f"away_points_against_avg_{n}": mean([x["pa"] for x in a], 102), f"home_margin_avg_{n}": mean([x["margin"] for x in h]), f"away_margin_avg_{n}": mean([x["margin"] for x in a]), f"home_games_7d_{n}": float(sum((kickoff - x["kickoff"]).total_seconds() <= 7 * 86400 for x in h)), f"away_games_7d_{n}": float(sum((kickoff - x["kickoff"]).total_seconds() <= 7 * 86400 for x in a))})
            for prefix, items in (("home", h), ("away", a)):
                stat_items = [x["stats"] for x in items if x.get("stats")]
                percentage_fields = (("fg_pct", "field_goals_made", "field_goals_attempted"), ("three_pct", "three_pointers_made", "three_pointers_attempted"), ("ft_pct", "free_throws_made", "free_throws_attempted"))
                for key, made_field, attempted_field in percentage_fields:
                    vals = [getattr(s, made_field) / getattr(s, attempted_field) for s in stat_items if getattr(s, made_field) is not None and getattr(s, attempted_field) and getattr(s, attempted_field) > 0]
                    if vals: values[f"{prefix}_{key}_avg_{n}"] = mean(vals)
                for key, field in (("field_goals_made", "field_goals_made"), ("three_pointers_made", "three_pointers_made"), ("free_throws_made", "free_throws_made"), ("rebounds", "total_rebounds"), ("turnovers", "turnovers"), ("assists", "assists")):
                    vals = [getattr(s, field) for s in stat_items if getattr(s, field) is not None]
                    if vals: values[f"{prefix}_{key}_avg_{n}"] = mean(vals)
                possessions, points = [], []
                for s in stat_items:
                    if s.field_goals_attempted is not None and s.free_throws_attempted is not None and s.offensive_rebounds is not None and s.turnovers is not None:
                        poss = s.field_goals_attempted + .44 * s.free_throws_attempted - s.offensive_rebounds + s.turnovers
                        if poss > 0: possessions.append(poss); points.append(s.points or 0)
                if possessions:
                    values[f"{prefix}_estimated_possessions_avg_{n}"] = mean(possessions)
                    values[f"{prefix}_estimated_pace_avg_{n}"] = mean(possessions)
                    values[f"{prefix}_estimated_offensive_rating_avg_{n}"] = safe_ratio(sum(points), sum(possessions), 1) * 100
            if f"home_estimated_possessions_avg_{n}" in values and f"away_estimated_possessions_avg_{n}" in values:
                values[f"estimated_game_pace_avg_{n}"] = (values[f"home_estimated_possessions_avg_{n}"] + values[f"away_estimated_possessions_avg_{n}"]) / 2
        return values

    def update_ratings(self, home_rating: float, away_rating: float, home_score: float, away_score: float) -> tuple[float, float]:
        expected = 1 / (1 + 10 ** ((away_rating - (home_rating + self.home_advantage)) / 400))
        result = 1.0 if home_score > away_score else 0.0
        delta = self.elo_k * (result - expected) * (1 + min(1.0, abs(home_score - away_score) / 20))
        return home_rating + delta, away_rating - delta

    def build_and_persist(self, db: Session, include_unfinished: bool = True) -> list[FeatureRow]:
        rows = self.build(db, include_unfinished)
        persist_features(db, rows, self.feature_version)
        return rows
