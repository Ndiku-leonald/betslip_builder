from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.live.service import LiveIntelligenceService
from app.markets.storage import latest_market_snapshots
from app.markets.value import MarketValueService, market_freshness, market_group_key
from app.models import Competition, Fixture, OddsSnapshot, Prediction, Slip, SlipLeg, Sport, Team
from app.odds.ontology import NormalizedMarket
from app.providers.reliability import source_reliability
from app.slips.config import MAX_BEAM_WIDTH, MAX_CANDIDATES_PER_FIXTURE, MAX_CANDIDATES_PER_GROUP, PROFILE_CONFIG, ProfileConfig
from app.slips.correlation import CorrelationRisk, aggregate_correlation, classify_correlation


@dataclass
class PoolResult:
    candidates: list[dict]
    diagnostics: dict[str, Any]
    exclusions: list[dict]


def _as_dict(request: Any) -> dict[str, Any]:
    return request.model_dump() if hasattr(request, "model_dump") else dict(request)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _date_bounds(request: dict[str, Any]) -> tuple[datetime, datetime]:
    settings = get_settings()
    local_zone = ZoneInfo(settings.app_timezone)
    today = datetime.now(local_zone).date()
    start = request.get("start_date") or today
    end = request.get("end_date") or start
    if isinstance(start, str): start = date.fromisoformat(start)
    if isinstance(end, str): end = date.fromisoformat(end)
    return datetime.combine(start, dt_time.min, tzinfo=local_zone).astimezone(timezone.utc), datetime.combine(end + timedelta(days=1), dt_time.min, tzinfo=local_zone).astimezone(timezone.utc)


def _candidate_identity(item: dict) -> tuple:
    return (item.get("fixture_id"), item.get("provider"), item.get("bookmaker"), item.get("market_family"), item.get("market_type"), item.get("period"), item.get("participant"), item.get("selection"), item.get("line"), item.get("settlement_semantics"))


def _warning_list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


class CandidateGate:
    """Centralized and testable hard eligibility policy."""

    def __init__(self, request: dict[str, Any], profile: ProfileConfig):
        self.request = request
        self.profile = profile

    def check(self, value: dict, *, fixture: Fixture, live: bool) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        odds = value.get("bookmaker_odds")
        probability = value.get("model_win_probability", value.get("model_probability"))
        status = str(value.get("market_status", "unknown")).lower()
        freshness = value.get("freshness", {}) or {}
        if status != "open": reasons.append(f"market_status:{status}")
        if value.get("status") != "CURRENT": reasons.append(f"value_status:{value.get('status', 'unknown')}")
        if freshness.get("status") != "CURRENT": reasons.append("stale_or_aging_odds")
        if live and not value.get("is_live", True): reasons.append("pre_match_price_in_live_pool")
        if not live and value.get("is_live", False): reasons.append("live_price_in_pre_match_pool")
        if odds is None or not isinstance(odds, (int, float)) or odds <= 1: reasons.append("invalid_odds")
        if probability is None or not 0 < float(probability) < 1: reasons.append("missing_model_probability")
        if value.get("compatibility") not in {None, "SUPPORTED"}: reasons.append(f"unsupported_model_market:{value.get('compatibility')}")
        if float(value.get("confidence", 0) or 0) < max(float(self.request.get("min_confidence", 0)), self.profile.minimum_confidence): reasons.append("confidence_below_threshold")
        if float(value.get("data_quality", 0) or 0) < max(float(self.request.get("min_data_quality", 0)), self.profile.minimum_data_quality): reasons.append("data_quality_below_threshold")
        if float(probability or 0) < max(float(self.request.get("min_probability", 0)), self.profile.minimum_probability): reasons.append("probability_below_threshold")
        if odds and float(odds) > float(self.request.get("max_individual_odds", 100.0)): reasons.append("individual_odds_above_threshold")
        if value.get("market_reliability") is None or float(value.get("market_reliability", 0)) < self.profile.minimum_market_reliability: reasons.append("market_reliability_below_threshold")
        if value.get("source_reliability") is None or float(value.get("source_reliability", 0)) < self.profile.minimum_source_reliability: reasons.append("source_reliability_below_threshold")
        agreement = value.get("provider_agreement")
        if agreement is not None and float(agreement) < get_settings().min_provider_agreement: reasons.append("provider_agreement_below_threshold")
        if value.get("material_provider_conflict"): reasons.append("material_provider_conflict")
        if self.request.get("require_positive_value") and float(value.get("expected_value", 0) or 0) <= 0: reasons.append("expected_value_not_positive")
        calibration = str(value.get("calibration_status", "INSUFFICIENT_EVIDENCE"))
        if calibration not in self.profile.minimum_calibration: reasons.append("calibration_not_accepted_for_profile")
        if not value.get("bookmaker"): reasons.append("bookmaker_missing_buildable_slip")
        if fixture.status in {"finished", "cancelled", "postponed"}: reasons.append("fixture_not_available")
        return not reasons, reasons


class SlipOptimizer:
    version = "stage-five-v1"

    def __init__(self, *, value_service: MarketValueService | None = None, live_service: LiveIntelligenceService | None = None):
        self.value_service = value_service or MarketValueService()
        self.live_service = live_service or LiveIntelligenceService()

    @staticmethod
    def _latest_valid_prematch_prediction(db: Session, fixture_id: str) -> Prediction | None:
        predictions = db.scalars(select(Prediction).where(Prediction.fixture_id == fixture_id, Prediction.prediction_type == "pre_match").order_by(Prediction.generated_at.desc(), Prediction.id.desc())).all()
        for prediction in predictions:
            payload = prediction.payload or {}
            if payload.get("available", True) is not False:
                return prediction
        return None

    @staticmethod
    def _prematch_snapshots(db: Session, fixture_id: str) -> list[OddsSnapshot]:
        rows = list(db.scalars(select(OddsSnapshot).where(OddsSnapshot.fixture_id == fixture_id, OddsSnapshot.is_live.is_(False)).order_by(OddsSnapshot.observed_at.desc(), OddsSnapshot.created_at.desc(), OddsSnapshot.id.desc())))
        selected: dict[tuple, OddsSnapshot] = {}
        for row in rows:
            key = _candidate_identity({"fixture_id": row.fixture_id, "provider": row.provider, "bookmaker": row.bookmaker, "market_family": row.market_family, "market_type": row.market_type, "period": row.period, "participant": row.participant, "selection": row.selection, "line": row.line, "settlement_semantics": row.settlement_semantics})
            current = selected.get(key)
            if current is None:
                selected[key] = row
                continue
            current_fresh = market_freshness(current.observed_at or current.created_at, provider_updated_at=current.provider_updated_at)
            row_fresh = market_freshness(row.observed_at or row.created_at, provider_updated_at=row.provider_updated_at)
            if (row.market_status == "open", row_fresh.get("status") == "CURRENT", row.observed_at or row.created_at, row.id) > (current.market_status == "open", current_fresh.get("status") == "CURRENT", current.observed_at or current.created_at, current.id):
                selected[key] = row
        return sorted(selected.values(), key=lambda item: (item.observed_at or item.created_at, item.id), reverse=True)

    def _prematch_values(self, db: Session, fixture: Fixture, snapshots: list[OddsSnapshot], prediction: Prediction | None) -> list[dict]:
        # These are the same Stage Three helpers used by the market-value endpoints.
        from app.main import _model_market_reliability, _model_probability_for_snapshot, _stored_consensus
        grouped: dict[tuple, list[OddsSnapshot]] = {}
        for item in snapshots: grouped.setdefault(market_group_key(item), []).append(item)
        values = []
        consensus = _stored_consensus(db, fixture.id)
        for snapshot in snapshots:
            info = _model_probability_for_snapshot(db, snapshot, prediction)
            normalized = NormalizedMarket(fixture_id=snapshot.fixture_id, sport=prediction.sport if prediction else "football", bookmaker=snapshot.bookmaker or "", provider=snapshot.provider, market_family=snapshot.market_family or "unknown", market_type=snapshot.market_type or "unknown", period=snapshot.period or "full_game", participant=snapshot.participant or "none", selection=snapshot.selection or "unknown", line=snapshot.line, decimal_odds=snapshot.decimal_odds, status=snapshot.market_status, settlement_semantics=snapshot.settlement_semantics or "full_game", observed_at=snapshot.observed_at or snapshot.created_at, provider_updated_at=snapshot.provider_updated_at, source_event_id=snapshot.source_event_id, raw=snapshot.payload, is_live=snapshot.is_live)
            group = [NormalizedMarket(fixture_id=item.fixture_id, sport=normalized.sport, bookmaker=item.bookmaker or "", provider=item.provider, market_family=item.market_family or "unknown", market_type=item.market_type or "unknown", period=item.period or "full_game", participant=item.participant or "none", selection=item.selection or "unknown", line=item.line, decimal_odds=item.decimal_odds, status=item.market_status, settlement_semantics=item.settlement_semantics or "full_game", observed_at=item.observed_at or item.created_at, provider_updated_at=item.provider_updated_at, is_live=item.is_live) for item in grouped[market_group_key(snapshot)]]
            reliability, components = _model_market_reliability(db, snapshot, prediction)
            source = source_reliability(snapshot.provider, observed_agreement_rate=consensus.get("agreement") if consensus.get("source_count", 0) > 1 else None)
            value = self.value_service.evaluate(normalized, model_probability_structure=info.get("model_probability_structure"), model_version=prediction.model_version_id if prediction else None, confidence=(prediction.payload or {}).get("model_confidence_score", 0) if prediction else 0, data_quality=(prediction.payload or {}).get("data_quality", {}).get("overall", 0) if prediction else 0, market_reliability=reliability, market_reliability_components=components, source_reliability=source["reliability_score"], source_reliability_components=source, provider_agreement=consensus.get("agreement"), material_conflict=consensus.get("material_conflict", False), calibration_status=info.get("calibration_status", "insufficient_calibration"), market_group=group, ttl_seconds=get_settings().odds_prematch_ttl_seconds)
            value.update({"compatibility": info.get("status"), "reason": info.get("reason"), "raw_model_probability": info.get("raw_model_probability"), "calibrated_model_probability": info.get("calibrated_model_probability"), "snapshot_id": snapshot.id, "is_live": False})
            values.append(value)
        return values

    def candidate_pool(self, db: Session, request: Any) -> PoolResult:
        params = _as_dict(request)
        profile_name = params["profile"]
        profile = PROFILE_CONFIG[profile_name]
        start, end = _date_bounds(params)
        sports = set(params.get("sports") or {"football", "basketball"})
        mode = params.get("mode", "prematch")
        include_live = bool(params.get("include_live", False)) and mode in {"live", "both"}
        diagnostics = {"candidates_discovered": 0, "candidates_rejected": 0, "candidates_entering_optimizer": 0, "rejection_reasons": {}, "bookmaker_groups": 0, "pruning_count": 0}
        exclusions: list[dict] = []
        candidates: list[dict] = []
        query = select(Fixture).join(Sport, Sport.id == Fixture.sport_id).where(Sport.slug.in_(sports)).order_by(Fixture.kickoff_at, Fixture.id)
        fixture_rows = list(db.scalars(query))
        gate = CandidateGate(params, profile)
        for fixture in fixture_rows:
            kickoff = _utc(fixture.kickoff_at)
            is_live_fixture = fixture.status in {"live", "halftime"}
            if is_live_fixture and not include_live: continue
            if is_live_fixture and mode == "prematch": continue
            if not is_live_fixture and mode == "live": continue
            if not is_live_fixture and (kickoff is None or not start <= kickoff < end): continue
            if is_live_fixture and mode == "both" and not include_live: continue
            if params.get("competitions"):
                requested_competitions = set(params["competitions"])
                competition_for_filter = db.get(Competition, fixture.competition_id) if fixture.competition_id else None
                if fixture.competition_id not in requested_competitions and (competition_for_filter is None or competition_for_filter.name not in requested_competitions): continue
            prediction = None if is_live_fixture else self._latest_valid_prematch_prediction(db, fixture.id)
            snapshots = latest_market_snapshots(db, fixture.id, live_only=is_live_fixture) if is_live_fixture else self._prematch_snapshots(db, fixture.id)
            if not is_live_fixture: snapshots = [item for item in snapshots if not item.is_live]
            if not snapshots: continue
            if is_live_fixture:
                live_result = self.live_service.markets(db, fixture.id, profile=profile_name, persist=False)
                values = live_result.get("opportunities", [])
                lookup = {_candidate_identity({**item, "snapshot_id": snapshot.id}): snapshot for snapshot in snapshots for item in [{"fixture_id": snapshot.fixture_id, "provider": snapshot.provider, "bookmaker": snapshot.bookmaker, "market_family": snapshot.market_family, "market_type": snapshot.market_type, "period": snapshot.period, "participant": snapshot.participant, "selection": snapshot.selection, "line": snapshot.line, "settlement_semantics": snapshot.settlement_semantics}]}
                for value in values:
                    match = lookup.get(_candidate_identity(value))
                    value["snapshot_id"] = match.id if match else None
                    value["is_live"] = True
            else:
                values = self._prematch_values(db, fixture, snapshots, prediction)
            sport = db.scalar(select(Sport).where(Sport.id == fixture.sport_id))
            competition = db.get(Competition, fixture.competition_id) if fixture.competition_id else None
            home = db.get(Team, fixture.home_team_id); away = db.get(Team, fixture.away_team_id)
            for value in values:
                diagnostics["candidates_discovered"] += 1
                if params.get("bookmaker") and value.get("bookmaker") != params["bookmaker"]:
                    diagnostics["candidates_rejected"] += 1
                    diagnostics["rejection_reasons"]["bookmaker_filter"] = diagnostics["rejection_reasons"].get("bookmaker_filter", 0) + 1
                    continue
                accepted, reasons = gate.check(value, fixture=fixture, live=is_live_fixture)
                if not accepted:
                    diagnostics["candidates_rejected"] += 1
                    for reason in reasons: diagnostics["rejection_reasons"][reason] = diagnostics["rejection_reasons"].get(reason, 0) + 1
                    if len(exclusions) < 100: exclusions.append({"fixture_id": fixture.id, "selection": value.get("selection"), "reasons": reasons})
                    continue
                probability = float(value.get("model_win_probability", value.get("model_probability")))
                candidate = {**value, "fixture_id": fixture.id, "sport": sport.slug if sport else value.get("sport", "unknown"), "competition": competition.name if competition else None, "competition_id": fixture.competition_id, "kickoff_at": kickoff, "status": "LIVE" if is_live_fixture else "PRE_MATCH", "home": home.name if home else "Unknown", "away": away.name if away else "Unknown", "team_ids": [fixture.home_team_id, fixture.away_team_id], "team_names": [home.name if home else "Unknown", away.name if away else "Unknown"], "model_probability": probability, "push_probability": float(value.get("model_push_probability", 0) or 0), "loss_probability": float(value.get("model_loss_probability", max(0, 1 - probability - float(value.get("model_push_probability", 0) or 0))) or 0), "warnings": _warning_list(value.get("warnings")), "settlement_semantics": value.get("settlement_semantics", "full_game"), "odds_snapshot_id": value.get("snapshot_id"), "prediction_id": prediction.id if prediction else None, "prediction_reference": prediction.model_version_id if prediction else None, "why_selected": "The model probability, current price, quality, reliability and calibration passed the configured profile gates."}
                candidates.append(candidate)
        dedup: dict[tuple, dict] = {}
        for item in candidates:
            key = _candidate_identity(item)
            current = dedup.get(key)
            if current is None or self._leg_quality(item) > self._leg_quality(current): dedup[key] = item
        candidates = sorted(dedup.values(), key=lambda item: (-self._leg_quality(item), item.get("fixture_id", ""), item.get("selection", "")))
        diagnostics["candidates_entering_optimizer"] = len(candidates)
        return PoolResult(candidates=candidates, diagnostics=diagnostics, exclusions=exclusions)

    @staticmethod
    def _leg_quality(item: dict) -> float:
        probability = float(item.get("model_probability", 0) or 0)
        return 100 * (.40 * probability + .16 * float(item.get("confidence", 0) or 0) / 100 + .14 * float(item.get("data_quality", 0) or 0) / 100 + .12 * float(item.get("market_reliability", 0) or 0) / 100 + .10 * float(item.get("source_reliability", 0) or 0) / 100 + .08 * min(1, max(0, float(item.get("expected_value", 0) or 0))))

    def _state_metrics(self, legs: list[dict], target: float, config: ProfileConfig, tolerance: float) -> dict:
        combined = math.prod(float(item["bookmaker_odds"]) for item in legs)
        joint = math.prod(float(item["model_probability"]) for item in legs)
        no_loss_with_push = math.prod(float(item.get("model_probability", 0)) + float(item.get("push_probability", 0) or 0) for item in legs)
        push_affected = max(0.0, no_loss_with_push - joint)
        pair_risks = [classify_correlation(a, b) for index, a in enumerate(legs) for b in legs[index + 1:]]
        penalty = 1.0
        warnings = []
        for pair in pair_risks:
            penalty *= {"LOW": 1.0, "MODERATE": .96, "HIGH": .80, "UNKNOWN": .88, "CONFLICTING": 0.0}.get(pair["risk"], .88)
            if pair["risk"] in {"MODERATE", "HIGH", "UNKNOWN"}: warnings.append(pair["reason"])
        adjusted = joint * penalty
        target_fit = max(0.0, 1 - abs(math.log(max(combined, 1e-9) / target)))
        if combined >= target * (1 - tolerance) and combined <= target * (1 + tolerance): target_fit = min(1.0, target_fit + .25)
        avg_confidence = sum(float(item.get("confidence", 0)) for item in legs) / len(legs) / 100
        avg_quality = sum(float(item.get("data_quality", 0)) for item in legs) / len(legs) / 100
        reliability = sum((float(item.get("market_reliability", 0)) + float(item.get("source_reliability", 0))) / 200 for item in legs) / len(legs)
        value = sum(max(0, min(1, float(item.get("expected_value", 0) or 0))) for item in legs) / len(legs)
        leg_fit = max(0.0, 1 - max(0, len(legs) - 3) * .12)
        uncertainty = sum(1 - float(item.get("confidence", 0)) / 100 for item in legs) / len(legs)
        score = 100 * (config.weights["joint"] * adjusted + config.weights["target"] * target_fit + config.weights["confidence"] * avg_confidence + config.weights["quality"] * avg_quality + config.weights["reliability"] * reliability + config.weights["value"] * value + config.weights["legs"] * leg_fit - config.uncertainty_penalty * uncertainty * .08)
        correlation = aggregate_correlation(legs)
        if push_affected > 0: warnings.append("One or more legs can push; nominal combined odds may be reduced by accumulator settlement rules.")
        return {"combined_odds": combined, "target_difference": combined - target, "naive_joint_probability": joint, "all_legs_win_probability": joint, "no_loss_probability_with_push": no_loss_with_push, "push_affected_probability": push_affected, "risk_adjusted_probability": adjusted, "correlation": correlation, "correlation_risk": correlation["risk"], "average_confidence": avg_confidence * 100, "minimum_confidence": min(float(item.get("confidence", 0)) for item in legs), "average_data_quality": avg_quality * 100, "minimum_data_quality": min(float(item.get("data_quality", 0)) for item in legs), "expected_value_summary": sum(float(item.get("expected_value", 0) or 0) for item in legs) / len(legs), "suitability_score": round(score, 4), "target_reached": target * (1 - tolerance) <= combined <= target * (1 + tolerance), "warnings": sorted(set(warnings))}

    def _search_group(self, items: list[dict], params: dict, config: ProfileConfig) -> list[dict]:
        target = float(params["target_odds"]); tolerance = float(params["target_tolerance"]); min_legs = int(params["min_legs"]); max_legs = int(params["max_legs"])
        by_fixture: dict[str, list[dict]] = {}
        for item in items: by_fixture.setdefault(item["fixture_id"], []).append(item)
        pruned = []
        for fixture_items in by_fixture.values():
            ordered = sorted(fixture_items, key=self._leg_quality, reverse=True)
            self._pruning_count += max(0, len(ordered) - MAX_CANDIDATES_PER_FIXTURE)
            pruned.extend(ordered[:MAX_CANDIDATES_PER_FIXTURE])
        ordered = sorted(pruned, key=self._leg_quality, reverse=True)
        self._pruning_count += max(0, len(ordered) - MAX_CANDIDATES_PER_GROUP)
        pruned = ordered[:MAX_CANDIDATES_PER_GROUP]
        beam: list[list[dict]] = [[]]
        explored = 0
        states: list[list[dict]] = []
        for _ in range(max_legs):
            next_beam: list[list[dict]] = []
            for state in beam:
                for item in pruned:
                    explored += 1
                    if item in state or any(existing["fixture_id"] == item["fixture_id"] for existing in state):
                        self._pruning_count += 1
                        continue
                    if state and any(classify_correlation(existing, item)["risk"] == CorrelationRisk.CONFLICTING.value for existing in state):
                        self._pruning_count += 1
                        continue
                    new_state = state + [item]
                    metrics = self._state_metrics(new_state, target, config, tolerance)
                    if metrics["combined_odds"] > target * (1 + tolerance) * 1.75:
                        self._pruning_count += 1
                        continue
                    next_beam.append(new_state)
                    if len(new_state) >= min_legs: states.append(new_state)
            next_beam.sort(key=lambda state: self._state_metrics(state, target, config, tolerance)["suitability_score"], reverse=True)
            self._pruning_count += max(0, len(next_beam) - MAX_BEAM_WIDTH)
            beam = next_beam[:MAX_BEAM_WIDTH]
            if not beam: break
        ranked = []
        for state in states:
            metrics = self._state_metrics(state, target, config, tolerance)
            ranked.append({"legs": state, **metrics, "bookmaker": state[0]["bookmaker"], "provider": state[0]["provider"], "sport_distribution": {sport: sum(1 for leg in state if leg.get("sport") == sport) for sport in sorted({leg.get("sport") for leg in state})}, "competition_concentration": {str(comp): sum(1 for leg in state if leg.get("competition_id") == comp) for comp in sorted({leg.get("competition_id") for leg in state})}})
        self._combinations_explored = getattr(self, "_combinations_explored", 0) + explored
        return sorted(ranked, key=lambda item: (-item["suitability_score"], abs(item["target_difference"]), item["combined_odds"], tuple(leg["fixture_id"] for leg in item["legs"])))

    def optimize(self, db: Session, request: Any) -> dict:
        started = time.perf_counter(); self._combinations_explored = 0; self._pruning_count = 0; params = _as_dict(request); pool = self.candidate_pool(db, params); config = PROFILE_CONFIG[params["profile"]]
        groups: dict[tuple[str, str], list[dict]] = {}
        for item in pool.candidates: groups.setdefault((item["provider"], item["bookmaker"]), []).append(item)
        ranked: list[dict] = []
        for group_items in groups.values(): ranked.extend(self._search_group(group_items, params, config))
        ranked.sort(key=lambda item: (-item["suitability_score"], abs(item["target_difference"]), item["combined_odds"]))
        alternatives = []
        for item in ranked:
            if not alternatives or all(len({leg["fixture_id"] for leg in item["legs"]}.symmetric_difference({leg["fixture_id"] for leg in other["legs"]})) >= 2 for other in alternatives):
                alternatives.append(item)
            if len(alternatives) >= int(params.get("alternatives", 3)): break
        diagnostics = {**pool.diagnostics, "bookmaker_groups": len(groups), "combinations_explored": self._combinations_explored, "pruning_count": self._pruning_count, "elapsed_ms": round((time.perf_counter() - started) * 1000, 2), "diversity_rule": "fixture symmetric difference >= 2", "search_limit": {"beam_width": MAX_BEAM_WIDTH, "max_candidates_per_fixture": MAX_CANDIDATES_PER_FIXTURE, "max_candidates_per_group": MAX_CANDIDATES_PER_GROUP, "max_legs": params["max_legs"]}}
        safe = bool(alternatives and alternatives[0]["target_reached"])
        warnings = [] if safe else ["No eligible slip reached the requested target under the current risk constraints."]
        if not groups: warnings.append("No single-bookmaker group contained enough eligible selections.")
        result = {"status": "TARGET_REACHED" if safe else "NO_SAFE_TARGET", "message": "Probabilities and odds are estimates; selections can lose and prices can change.", "target_odds": params["target_odds"], "profile": params["profile"], "mode": params.get("mode", "prematch"), "target_reached": safe, "slips": [self.serialize_option(item, params, warnings) for item in alternatives], "diagnostics": diagnostics, "exclusions": pool.exclusions, "warnings": warnings}
        return result

    def serialize_option(self, option: dict, params: dict, warnings: list[str] | None = None) -> dict:
        metrics = {key: value for key, value in option.items() if key != "legs"}
        legs = []
        for leg in option["legs"]:
            legs.append({**{key: value for key, value in leg.items() if key not in {"team_ids"}}, "explanation": f"Selected because the model estimates a {float(leg['model_probability']) * 100:.1f}% win probability, the price is fresh, and the leg passed the configured confidence, quality, reliability and calibration gates."})
        return {"id": None, "target_odds": params["target_odds"], "profile": params["profile"], "mode": params.get("mode", "prematch"), "bookmaker": option.get("bookmaker"), "provider": option.get("provider"), "optimization_version": self.version, "legs": legs, **metrics, "warnings": sorted(set((warnings or []) + option.get("warnings", [])))}

    def persist(self, db: Session, result: dict, *, configuration: dict[str, Any]) -> dict:
        if not result.get("slips"): return result
        persisted = []
        for option in result["slips"]:
            slip = Slip(risk=option["profile"], target_odds=option["target_odds"], mode=option["mode"], profile=option["profile"], bookmaker=option.get("bookmaker"), provider=option.get("provider"), achieved_odds=option.get("combined_odds"), optimization_version=self.version, joint_probability=option.get("naive_joint_probability"), adjusted_score=option.get("risk_adjusted_probability"), correlation_risk=option.get("correlation_risk"), target_reached=option.get("target_reached", False), configuration_snapshot=_json_safe(configuration), warnings=option.get("warnings", []), diagnostics=_json_safe(result.get("diagnostics", {})))
            db.add(slip); db.flush()
            for index, leg in enumerate(option["legs"]):
                row = SlipLeg(slip_id=slip.id, odds_snapshot_id=leg.get("odds_snapshot_id") or leg.get("snapshot_id"), fixture_id=leg.get("fixture_id"), leg_order=index, snapshot=_json_safe(leg))
                db.add(row); db.flush(); leg["id"] = row.id; row.snapshot = _json_safe(leg)
            option["id"] = slip.id
            persisted.append(option)
        db.commit(); result["slips"] = persisted; result["slip_id"] = persisted[0]["id"]
        return result

    @staticmethod
    def recalculate_option(legs: list[dict], target: float, tolerance: float, config: ProfileConfig) -> dict:
        helper = SlipOptimizer()
        metrics = helper._state_metrics(legs, target, config, tolerance)
        return {"legs": legs, **metrics, "bookmaker": legs[0].get("bookmaker") if legs else None, "provider": legs[0].get("provider") if legs else None}
