from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models import ProviderConflict


class ProviderConsensusService:
    """Resolve factual fields without averaging categorical sport state."""

    priorities = {"api-football": 100, "api-basketball": 100, "livescore-football": 60, "easy-soccer-data": 20}

    def resolve(self, observations: list[Any], *, primary_source: str | None = None, fixture_id: str | None = None, db: Session | None = None) -> dict:
        if not observations: return {"fields": {}, "source_count": 0, "agreement": 0.0, "conflicts": []}
        observations = sorted(observations, key=lambda item: self.priorities.get(item.get("provider", "") if isinstance(item, dict) else item.provider, 0), reverse=True)
        primary = primary_source or (observations[0].provider if not isinstance(observations[0], dict) else observations[0].get("provider"))
        fields = {}
        conflicts = []
        for field in ("home_provider_id", "away_provider_id", "kickoff_at", "status", "home_score", "away_score", "period", "clock"):
            values = [self._get(item, field) for item in observations]
            values = [value for value in values if value is not None]
            if not values: continue
            value = values[0]; agreements = [self._agreement(field, value, other) for other in values[1:]]
            agreement = sum(agreements) / len(agreements) if agreements else 1.0
            fields[field] = {"value": value, "agreement": round(agreement, 3), "sources": [self._get(item, "provider") for item in observations if self._get(item, field) is not None]}
            for other, score in zip(values[1:], agreements):
                if score < 1:
                    severity = "minor" if score >= .8 else "material" if field in {"home_score", "away_score", "status"} else "conflict"
                    conflict = {"fixture_id": fixture_id, "entity_type": "fixture", "field": field, "primary_source": primary, "secondary_source": self._source_for_value(observations, field, other), "primary_value": self._json_value(value), "secondary_value": self._json_value(other), "observed_at": datetime.now(timezone.utc), "severity": severity, "resolution": "primary_priority", "resolved_source": primary}
                    conflicts.append(conflict)
                    if db is not None and fixture_id is not None: db.add(ProviderConflict(**conflict))
        if db is not None: db.commit()
        overall = sum(item["agreement"] for item in fields.values()) / len(fields) if fields else 0.0
        return {"fields": fields, "source_count": len(observations), "agreement": round(overall, 3), "conflicts": conflicts}

    @staticmethod
    def _get(item, field): return item.get(field) if isinstance(item, dict) else getattr(item, field, None)
    @staticmethod
    def _source_for_value(observations, field, value):
        for item in observations:
            if ProviderConsensusService._get(item, field) == value: return ProviderConsensusService._get(item, "provider")
        return "unknown"
    @staticmethod
    def _json_value(value): return value.isoformat() if isinstance(value, datetime) else value
    @staticmethod
    def _agreement(field, first, second):
        if field == "clock":
            try: return 1.0 if abs(float(str(first).strip("'")) - float(str(second).strip("'"))) == 0 else .88 if abs(float(str(first).strip("'")) - float(str(second).strip("'"))) <= 1 else .4
            except (TypeError, ValueError): pass
        return 1.0 if first == second else 0.4
