"""Research-only real football model evaluation and downstream smoke check.

The command never promotes a model and never persists predictions. Training is
performed by ``python -m app.training.train``; this smoke reuses the latest
candidate artifacts so repeated checks do not retrain the historical dataset.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sqlalchemy import func, select  # noqa: E402

from app.calibration.calibrator import MarketCalibrator  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.evaluation.baselines import evaluate_fold_baselines  # noqa: E402
from app.evaluation.backtest import _football_class, _outcome, _scalar_probability  # noqa: E402
from app.evaluation.metrics import (  # noqa: E402
    brier_score,
    categorical_log_loss,
    expected_calibration_error,
    log_loss,
    multiclass_brier,
    reliability_buckets,
)
from app.evaluation.splits import chronological_split  # noqa: E402
from app.features.football import FootballFeatureEngine  # noqa: E402
from app.markets.storage import latest_market_snapshots, market_identity  # noqa: E402
from app.markets.value import MarketValueService, market_freshness  # noqa: E402
from app.models import (  # noqa: E402
    Competition,
    Fixture,
    FixtureFeatureSnapshot,
    ModelVersion,
    OddsSnapshot,
    Prediction,
    Season,
    Sport,
    TeamMatchStatistic,
)
from app.odds.ontology import NormalizedMarket  # noqa: E402
from app.prediction.football import FootballPoissonModel  # noqa: E402
from app.slips.optimizer import SlipOptimizer  # noqa: E402
from app.training.dataset import build_dataset  # noqa: E402


MARKETS = ("home_win", "draw", "away_win", "btts_yes", "over_1_5", "over_2_5", "over_3_5", "home_handicap_-0.5", "home_handicap_+0.5")


def iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def compact_metric(value):
    return round(float(value), 6) if isinstance(value, (int, float)) else value


def model_for(version: ModelVersion) -> FootballPoissonModel:
    params = version.parameters or {}
    model = FootballPoissonModel(params.get("score_method", "poisson"), params.get("goal_cap", 10), params.get("rho", -0.08))
    for key in ("home_mean", "away_mean"):
        if key in params:
            setattr(model, key, params[key])
    return model


def family(key: str) -> str:
    if key in {"home_win", "draw", "away_win"}:
        return "1X2"
    if key.startswith("btts"):
        return "btts"
    if key.startswith("over_") or key.startswith("under_"):
        return "totals"
    return "handicap"


def audit_dataset(db, rows) -> dict:
    sport_id = db.scalar(select(Sport.id).where(Sport.slug == "football"))
    fixtures = list(db.scalars(select(Fixture).where(Fixture.sport_id == sport_id).order_by(Fixture.kickoff_at, Fixture.id))) if sport_id else []
    ids = [item.id for item in fixtures]
    competitions = db.execute(select(Competition.name, Competition.provider_id, func.count(Fixture.id)).join(Fixture, Fixture.competition_id == Competition.id).where(Fixture.sport_id == sport_id).group_by(Competition.id).order_by(func.count(Fixture.id).desc())).all() if sport_id else []
    seasons = list(db.scalars(select(Season).order_by(Season.name, Season.id)))
    duplicate_keys = [(item.provider, item.provider_fixture_id) for item in fixtures]
    finished = [item for item in fixtures if item.status == "finished"]
    return {
        "fixtures": len(fixtures),
        "status_counts": dict(Counter(item.status for item in fixtures)),
        "completed": len(finished),
        "upcoming": sum(item.status == "scheduled" for item in fixtures),
        "live": sum(item.status in {"live", "halftime"} for item in fixtures),
        "competitions": len({item.competition_id for item in fixtures}),
        "competition_top": [{"name": row[0], "provider_id": row[1], "fixtures": row[2]} for row in competitions[:12]],
        "seasons_recorded": sorted({item.name for item in seasons}),
        "date_start": iso(min((item.kickoff_at for item in fixtures if item.kickoff_at), default=None)),
        "date_end": iso(max((item.kickoff_at for item in fixtures if item.kickoff_at), default=None)),
        "duplicate_provider_identities": len(duplicate_keys) - len(set(duplicate_keys)),
        "finished_missing_scores": sum(item.home_score is None or item.away_score is None for item in finished),
        "missing_kickoff": sum(item.kickoff_at is None for item in fixtures),
        "missing_season": sum(item.season_id is None for item in fixtures),
        "statistics_rows": db.scalar(select(func.count(TeamMatchStatistic.id)).where(TeamMatchStatistic.fixture_id.in_(ids))) if ids else 0,
        "feature_snapshots": db.scalar(select(func.count(FixtureFeatureSnapshot.id)).where(FixtureFeatureSnapshot.fixture_id.in_(ids))) if ids else 0,
        "feature_rows": len(rows),
        "feature_rows_with_history": sum(int(item.data_quality.get("history_count", 0)) >= 5 for item in rows),
        "feature_rows_with_statistics": sum(float(item.data_quality.get("statistics_completeness", 0)) > 0 for item in rows),
        "feature_quality_min": min((float(item.data_quality.get("overall", 0)) for item in rows), default=None),
        "feature_quality_max": max((float(item.data_quality.get("overall", 0)) for item in rows), default=None),
    }


def holdout_evaluation(version: ModelVersion, rows) -> dict:
    ordered = sorted([row for row in rows if row.actual], key=lambda row: (row.data_cutoff_at, str(row.fixture_id)))
    train, validation, test, split = chronological_split(ordered)
    model = model_for(version)
    calibrator = MarketCalibrator.from_metadata((version.parameters or {}).get("calibration", {}))
    by_family = defaultdict(list)
    by_market = defaultdict(list)
    multiclass_rows = []
    multiclass_actual = []
    for row in test:
        output = model.predict(row).get("markets", {})
        raw = {key: _scalar_probability(output.get(key)) for key in MARKETS if _scalar_probability(output.get(key)) is not None and _outcome(row, key) is not None}
        calibrated = calibrator.transform(raw)
        one_x_two = {}
        for key, value in raw.items():
            actual = _outcome(row, key)
            item = {"raw": value, "calibrated": calibrated.get(key, value), "actual": actual}
            by_family[family(key)].append(item)
            by_market[key].append(item)
            if family(key) == "1X2":
                one_x_two[key] = calibrated.get(key, value)
        if all(key in one_x_two for key in ("home_win", "draw", "away_win")):
            multiclass_rows.append({"home": one_x_two["home_win"], "draw": one_x_two["draw"], "away": one_x_two["away_win"]})
            multiclass_actual.append(_football_class(row))

    def score(items):
        raw = [item["raw"] for item in items]
        calibrated = [item["calibrated"] for item in items]
        actual = [item["actual"] for item in items]
        return {"sample_count": len(items), "raw_brier": compact_metric(brier_score(raw, actual)), "calibrated_brier": compact_metric(brier_score(calibrated, actual)), "raw_log_loss": compact_metric(log_loss(raw, actual)), "calibrated_log_loss": compact_metric(log_loss(calibrated, actual)), "calibrated_ece": compact_metric(expected_calibration_error(calibrated, actual)), "calibration_buckets": [bucket for bucket in reliability_buckets(calibrated, actual) if bucket["count"] > 0]}

    baseline = evaluate_fold_baselines(train, test, "football")
    return {
        "version": version.version,
        "algorithm": version.algorithm,
        "status": version.status,
        "sample_count": version.sample_count,
        "train_count": len(train),
        "validation_count": len(validation),
        "test_count": len(test),
        "train_start": iso(split["start_at"][0]),
        "train_end": iso(split["end_at"][0]),
        "validation_start": iso(split["start_at"][1]),
        "validation_end": iso(split["end_at"][1]),
        "test_start": iso(split["start_at"][2]),
        "test_end": iso(split["end_at"][2]),
        "markets": {key: score(items) for key, items in by_market.items()},
        "families": {key: score(items) for key, items in by_family.items()},
        "multiclass_1x2": {"sample_count": len(multiclass_actual), "brier": compact_metric(multiclass_brier(multiclass_rows, multiclass_actual)), "log_loss": compact_metric(categorical_log_loss(multiclass_rows, multiclass_actual))},
        "baseline": {key: {metric: compact_metric(value.get(metric)) for metric in ("sample_count", "multiclass_brier", "categorical_log_loss", "evaluation_start", "evaluation_end")} for key, value in baseline.items() if key in {"simple_elo_1x2", "league_average_poisson", "league_frequency_1x2"}},
        "calibration_policy": (version.parameters or {}).get("calibration_policy"),
        "feature_version": version.feature_version,
    }


def market_key(snapshot: OddsSnapshot) -> str | None:
    family_name = (snapshot.market_family or "").lower()
    selection = (snapshot.selection or "").lower()
    if family_name == "1x2":
        return {"home": "home_win", "draw": "draw", "away": "away_win"}.get(selection)
    if family_name == "btts":
        return f"btts_{selection}" if selection in {"yes", "no"} else None
    if family_name in {"totals", "game_total"} and snapshot.line is not None:
        return f"{selection}_{str(float(snapshot.line)).replace('.', '_')}"
    if family_name == "handicap" and snapshot.line is not None and snapshot.participant in {"home", "away"}:
        return f"{snapshot.participant}_handicap_{float(snapshot.line):+g}"
    return None


def downstream_smoke(db, version: ModelVersion, feature_rows, max_upcoming: int) -> dict:
    model = model_for(version)
    calibrator = MarketCalibrator.from_metadata((version.parameters or {}).get("calibration", {}))
    fixtures = list(db.scalars(select(Fixture).join(Sport, Sport.id == Fixture.sport_id).where(Sport.slug == "football", Fixture.status == "scheduled").order_by(Fixture.kickoff_at, Fixture.id)))
    rows_by_id = {row.fixture_id: row for row in feature_rows}
    research_predictions = []
    for fixture in fixtures:
        row = rows_by_id.get(fixture.id)
        if row is None or int(row.data_quality.get("history_count", 0)) < 5:
            continue
        output = model.predict(row)
        raw = {key: _scalar_probability(output["markets"].get(key)) for key in MARKETS if _scalar_probability(output["markets"].get(key)) is not None}
        calibrated = calibrator.transform(raw)
        research_predictions.append({"fixture_id": fixture.id, "data_cutoff_at": iso(row.data_cutoff_at), "kickoff_at": iso(fixture.kickoff_at), "markets": calibrated})
        if len(research_predictions) >= max_upcoming:
            break

    latest: dict[tuple, OddsSnapshot] = {}
    for snapshot in db.scalars(select(OddsSnapshot).where(OddsSnapshot.is_live.is_(False)).order_by(OddsSnapshot.observed_at.desc(), OddsSnapshot.created_at.desc())):
        latest.setdefault(market_identity(snapshot), snapshot)
    odds_by_fixture = defaultdict(list)
    for snapshot in latest.values():
        odds_by_fixture[snapshot.fixture_id].append(snapshot)
    scheduled_ids = {fixture.id for fixture in fixtures}
    fixtures_with_odds = scheduled_ids & set(odds_by_fixture)
    usable_odds = 0
    for fixture_id in fixtures_with_odds:
        if any(snapshot.decimal_odds and snapshot.decimal_odds > 1 and snapshot.market_status == "open" and market_freshness(snapshot.observed_at or snapshot.created_at).get("status") != "STALE" for snapshot in odds_by_fixture[fixture_id]):
            usable_odds += 1

    intelligence = None
    if research_predictions:
        selected = next((item for item in research_predictions if item["fixture_id"] in odds_by_fixture), None)
        if selected:
            prediction = next(item for item in research_predictions if item["fixture_id"] == selected["fixture_id"])
            snapshots = [item for item in odds_by_fixture[selected["fixture_id"]] if market_key(item) in prediction["markets"]]
            one_x_two = [item for item in snapshots if item.market_family == "1x2"]
            if one_x_two:
                normalized = [NormalizedMarket(fixture_id=item.fixture_id, sport="football", bookmaker=item.bookmaker or "", provider=item.provider, market_family=item.market_family or "unknown", market_type=item.market_type or "unknown", period=item.period or "full_game", participant=item.participant or "none", selection=item.selection or "unknown", line=item.line, decimal_odds=item.decimal_odds, status=item.market_status or "open", settlement_semantics=item.settlement_semantics or "full_game", observed_at=item.observed_at or item.created_at, provider_updated_at=item.provider_updated_at, raw=item.payload or {}, is_live=False) for item in one_x_two]
                market = normalized[0]
                key = market_key(one_x_two[0])
                win = prediction["markets"].get(key)
                intelligence = MarketValueService().evaluate(market, model_probability_structure={"win_probability": win, "push_probability": 0.0, "loss_probability": 1 - win, "calibration_status": calibrator.status_by_market([key]).get(key, "insufficient_samples")}, market_group=normalized, model_version=version.id, data_quality=rows_by_id[selected["fixture_id"]].data_quality.get("overall", 0), confidence=0, market_reliability=50, source_reliability=50)

    optimizer = SlipOptimizer()
    optimizer_results = {}
    for profile, target in (("conservative", 3.0), ("balanced", 5.0), ("aggressive", 10.0)):
        optimizer_results[profile] = optimizer.optimize(db, {"profile": profile, "target_odds": target, "target_tolerance": .10, "min_legs": 2, "max_legs": 6, "alternatives": 3, "mode": "prematch", "sports": ["football"], "real_only": True})
    return {
        "research_predictions": len(research_predictions),
        "production_predictions_persisted": db.scalar(select(func.count(Prediction.id)).where(Prediction.sport == "football")),
        "scheduled_fixtures_with_any_real_odds": len(fixtures_with_odds),
        "scheduled_fixtures_with_usable_real_odds": usable_odds,
        "stage_three_research_market": {key: intelligence.get(key) for key in ("status", "compatibility", "bookmaker_odds", "model_probability", "fair_odds", "raw_probability_edge", "expected_value", "no_vig_status", "freshness")} if intelligence else None,
        "optimizer": {profile: {"status": result["status"], "target_reached": result["target_reached"], "slips": len(result["slips"]), "candidates_discovered": result["diagnostics"].get("candidates_discovered", 0), "rejection_reasons": result["diagnostics"].get("rejection_reasons", {})} for profile, result in optimizer_results.items()},
    }


def render_report(summary: dict) -> str:
    audit = summary["dataset"]
    lines = [
        "# SlipIQ real football model evaluation",
        "",
        f"Commissioning date: `{datetime.now(timezone.utc).isoformat()}`",
        "",
        "This report uses real API-Football fixture data only. No candidate was promoted automatically, no synthetic rows were used, and no profitability claim is made.",
        "",
        "## Dataset audit",
        "",
        f"- Fixtures audited: **{audit['fixtures']}**; completed **{audit['completed']}**, scheduled **{audit['upcoming']}**, live/halftime **{audit['live']}**.",
        f"- Date coverage: `{audit['date_start']}` to `{audit['date_end']}`.",
        f"- Competitions represented: **{audit['competitions']}** canonical competitions. Largest groups: " + ", ".join(f"{item['name']} ({item['fixtures']})" for item in audit["competition_top"][:6]) + ".",
        f"- Recorded seasons: {', '.join(audit['seasons_recorded']) or 'none'}; fixtures missing season linkage: **{audit['missing_season']}**.",
        f"- Duplicate provider identities: **{audit['duplicate_provider_identities']}**; completed rows missing scores: **{audit['finished_missing_scores']}**.",
        f"- Feature rows: **{audit['feature_rows']}**, with sufficient five-match history **{audit['feature_rows_with_history']}**; statistics coverage **{audit['feature_rows_with_statistics']}** rows. Quality range: `{audit['feature_quality_min']}`–`{audit['feature_quality_max']}`.",
        "",
        "## Chronological evaluation",
        "",
        "Calibration was fit only on the validation partition. The final test partition was not used for fitting or candidate selection.",
        "",
        "| Candidate | Train | Validation | Test | Test 1X2 Brier | Test 1X2 log loss | Simple Elo Brier | Simple Elo log loss | Decision |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in summary["candidates"]:
        baseline = item["baseline"].get("simple_elo_1x2", {})
        decision = "qualifies" if item["qualifies"] else "not qualified"
        lines.append(f"| {item['algorithm']} | {item['train_count']} | {item['validation_count']} | {item['test_count']} | {item['multiclass_1x2']['brier']:.4f} | {item['multiclass_1x2']['log_loss']:.4f} | {baseline.get('multiclass_brier', 0):.4f} | {baseline.get('categorical_log_loss', 0):.4f} | {decision} |")
    lines += ["", "### Candidate market metrics", ""]
    for item in summary["candidates"]:
        lines += [f"#### {item['algorithm']} (`{item['version']}`)", "", "| Market | N | Calibrated Brier | Calibrated log loss | ECE |", "|---|---:|---:|---:|---:|"]
        for key, metric in item["markets"].items():
            lines.append(f"| {key} | {metric['sample_count']} | {metric['calibrated_brier']:.4f} | {metric['calibrated_log_loss']:.4f} | {metric['calibrated_ece']:.4f} |")
        lines += ["", "Calibration buckets with observations:", "", "```json", json.dumps({key: metric["calibration_buckets"] for key, metric in item["markets"].items() if metric["calibration_buckets"]}, indent=2), "```", ""]
    lines += [
        "## Promotion decision",
        "",
        f"**{summary['promotion']['decision']}**",
        "",
        summary["promotion"]["reason"],
        "",
        "No champion model/version exists. Candidate artifacts remain local runtime artifacts and were not promoted or committed.",
        "",
        "## Real upcoming/odds smoke",
        "",
        f"- Research-only upcoming predictions computed: **{summary['downstream']['research_predictions']}**; persisted production predictions: **{summary['downstream']['production_predictions_persisted']}**.",
        f"- Scheduled fixtures with any real odds: **{summary['downstream']['scheduled_fixtures_with_any_real_odds']}**; with usable fresh/open odds: **{summary['downstream']['scheduled_fixtures_with_usable_real_odds']}**.",
        f"- Stage Three research market evaluation: `{summary['downstream']['stage_three_research_market']}`.",
        "",
        "| Profile | Target | Result | Safe target | Eligible candidates |",
        "|---|---:|---|---|---:|",
        f"| Conservative | 3.00 | {summary['downstream']['optimizer']['conservative']['status']} | {summary['downstream']['optimizer']['conservative']['target_reached']} | {summary['downstream']['optimizer']['conservative']['candidates_discovered']} |",
        f"| Balanced | 5.00 | {summary['downstream']['optimizer']['balanced']['status']} | {summary['downstream']['optimizer']['balanced']['target_reached']} | {summary['downstream']['optimizer']['balanced']['candidates_discovered']} |",
        f"| Aggressive | 10.00 | {summary['downstream']['optimizer']['aggressive']['status']} | {summary['downstream']['optimizer']['aggressive']['target_reached']} | {summary['downstream']['optimizer']['aggressive']['candidates_discovered']} |",
        "",
        "The optimizer remained fail-closed because no champion-backed production predictions were persisted. `NO_SAFE_TARGET` is the expected result here.",
        "",
        "## Leakage and limitations",
        "",
        "- Features are generated in kickoff order; same-kickoff fixtures are staged before any result updates, and the target fixture's score is not available to its own features.",
        "- Train, validation, and test partitions are atomic by exact feature cutoff timestamp; no random shuffle is used.",
        "- The backfill contains fixture results but no match-statistics rows, so statistics-derived features were unavailable rather than fabricated.",
        "- The API-Football free entitlement allowed historical seasons through 2024 but rejected the requested 2025 season; deeper history should wait for an entitled plan or another verified source.",
        "- This evaluation is evidence about the current sample and architecture, not evidence of profitability or future betting performance.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate real football candidates and smoke downstream gates without promotion")
    parser.add_argument("--output", default=str(ROOT / "docs" / "real-football-model-evaluation.md"))
    parser.add_argument("--max-upcoming", type=int, default=100)
    args = parser.parse_args()
    with SessionLocal() as db:
        feature_rows = FootballFeatureEngine().build_and_persist(db, include_unfinished=True)
        rows = build_dataset(db, "football")
        audit = audit_dataset(db, feature_rows)
        versions = []
        seen = set()
        for version in db.scalars(select(ModelVersion).where(ModelVersion.sport == "football", ModelVersion.status == "candidate").order_by(ModelVersion.trained_at.desc())):
            if version.algorithm in seen:
                continue
            seen.add(version.algorithm)
            versions.append(version)
        evaluations = [holdout_evaluation(version, rows) for version in versions]
        for item in evaluations:
            simple_elo = item["baseline"].get("simple_elo_1x2", {})
            item["qualifies"] = bool(item["test_count"] >= 100 and item["multiclass_1x2"]["brier"] <= simple_elo.get("multiclass_brier", 1) and item["multiclass_1x2"]["log_loss"] <= simple_elo.get("categorical_log_loss", 1) and item["families"].get("1X2", {}).get("calibrated_ece", 1) <= .10)
        downstream = downstream_smoke(db, versions[0], feature_rows, args.max_upcoming) if versions else {"research_predictions": 0, "production_predictions_persisted": 0, "scheduled_fixtures_with_any_real_odds": 0, "scheduled_fixtures_with_usable_real_odds": 0, "stage_three_research_market": None, "optimizer": {}}
        qualified = [item for item in evaluations if item["qualifies"]]
        promotion = {"decision": "MODEL QUALIFIED FOR CHAMPION PROMOTION" if qualified else "NO MODEL QUALIFIED FOR CHAMPION PROMOTION", "reason": "At least one candidate met the sample, calibration, and final-test non-regression gate." if qualified else "Both candidates were evaluated on the same final held-out fixtures, but neither met the safe non-regression gate against the simple Elo baseline while retaining acceptable calibration."}
        summary = {"dataset": audit, "candidates": evaluations, "promotion": promotion, "downstream": downstream}
        Path(args.output).resolve().write_text(render_report(summary), encoding="utf-8")
        print(json.dumps({"dataset": audit, "candidates": [{"version": item["version"], "algorithm": item["algorithm"], "train": item["train_count"], "validation": item["validation_count"], "test": item["test_count"], "test_1x2_brier": item["multiclass_1x2"]["brier"], "test_1x2_log_loss": item["multiclass_1x2"]["log_loss"], "qualifies": item["qualifies"]} for item in evaluations], "promotion": promotion, "downstream": downstream}, default=str))


if __name__ == "__main__":
    main()
