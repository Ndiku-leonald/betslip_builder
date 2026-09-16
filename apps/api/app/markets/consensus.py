from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProviderConflict
from app.providers.matching import normalize_team_name


class ProviderConsensusService:
    """Resolve normalized factual fields without comparing provider IDs."""
    priorities = {"api-football": 100, "api-basketball": 100, "livescore-football": 60, "easy-soccer-data": 20}

    def resolve(self, observations: list, *, primary_source: str | None = None, fixture_id: str | None = None, db: Session | None = None) -> dict:
        if not observations: return {"fields": {}, "source_count": 0, "agreement": 0.0, "conflicts": []}
        observations = sorted(observations, key=lambda item: self.priorities.get(self._get(item, "provider") or "", 0), reverse=True)
        primary = primary_source or self._get(observations[0], "provider")
        fields = {}; conflicts = []
        for field in ("home_team", "away_team", "kickoff_at", "status", "home_score", "away_score", "period", "clock"):
            present = [(item, self._get(item, field)) for item in observations if self._get(item, field) is not None]
            if not present: continue
            source_item, value = present[0]; agreements = [self._agreement(field, value, other) for _, other in present[1:]]
            agreement = sum(agreements) / len(agreements) if agreements else 1.0
            fields[field] = {"value": value, "agreement": round(agreement, 3), "sources": [self._get(item, "provider") for item, _ in present]}
            for (other_item, other), score in zip(present[1:], agreements):
                if score >= 1: continue
                severity = "minor" if score >= .8 else "material" if field in {"home_score", "away_score", "status", "home_team", "away_team"} else "conflict"
                conflict = {"fixture_id": fixture_id, "entity_type": "fixture", "field": field, "primary_source": primary, "secondary_source": self._get(other_item, "provider") or "unknown", "primary_value": self._json_value(value), "secondary_value": self._json_value(other), "observed_at": datetime.now(timezone.utc), "severity": severity, "resolution": "primary_priority", "resolved_source": primary}
                conflicts.append(conflict)
                if db is not None and fixture_id is not None and not self._duplicate_conflict(db, conflict): db.add(ProviderConflict(**conflict))
        if db is not None: db.commit()
        overall = sum(item["agreement"] for item in fields.values()) / len(fields) if fields else 0.0
        return {"fields": fields, "source_count": len(observations), "agreement": round(overall, 3), "conflicts": conflicts, "material_conflict": any(item["severity"] == "material" for item in conflicts)}

    @staticmethod
    def _get(item, field):
        if isinstance(item, dict):
            aliases = {"home_team": ("canonical_home_team", "home_name"), "away_team": ("canonical_away_team", "away_name")}
            if field in aliases:
                for alias in aliases[field]:
                    if item.get(alias) is not None: return item[alias]
            return item.get(field)
        aliases = {"home_team": ("canonical_home_team", "home_name"), "away_team": ("canonical_away_team", "away_name")}
        if field in aliases:
            for alias in aliases[field]:
                value = getattr(item, alias, None)
                if value is not None: return value
        return getattr(item, field, None)

    @staticmethod
    def _json_value(value): return value.isoformat() if isinstance(value, datetime) else value

    @staticmethod
    def _agreement(field, first, second):
        if field in {"home_team", "away_team"}: return 1.0 if normalize_team_name(str(first)) == normalize_team_name(str(second)) else 0.0
        if field in {"home_score", "away_score"}:
            try: return 1.0 if int(first) == int(second) else 0.0
            except (TypeError, ValueError): return 1.0 if first == second else 0.0
        if field == "status":
            equivalent = {"ns": "scheduled", "not started": "scheduled", "scheduled": "scheduled", "1h": "live", "2h": "live", "live": "live", "ht": "halftime", "halftime": "halftime", "ft": "finished", "finished": "finished"}
            return 1.0 if equivalent.get(str(first).casefold(), str(first).casefold()) == equivalent.get(str(second).casefold(), str(second).casefold()) else 0.0
        if field == "period": return 1.0 if str(first).casefold() == str(second).casefold() else 0.0
        if field == "clock":
            try:
                distance = abs(float(str(first).strip("'")) - float(str(second).strip("'")))
                return 1.0 if distance == 0 else .88 if distance <= 1 else 0.0
            except (TypeError, ValueError): return 1.0 if first == second else 0.0
        if field == "kickoff_at":
            if isinstance(first, datetime) and isinstance(second, datetime):
                if first.tzinfo is None: first = first.replace(tzinfo=timezone.utc)
                if second.tzinfo is None: second = second.replace(tzinfo=timezone.utc)
                return 1.0 if abs((first.astimezone(timezone.utc) - second.astimezone(timezone.utc)).total_seconds()) <= 300 else 0.0
        if isinstance(first, (int, float)) and isinstance(second, (int, float)): return 1.0 if abs(first - second) <= max(1, abs(first) * .01) else 0.0
        return 1.0 if first == second else 0.0

    @staticmethod
    def _duplicate_conflict(db: Session, conflict: dict) -> bool:
        rows = db.scalars(select(ProviderConflict).where(ProviderConflict.fixture_id == conflict["fixture_id"], ProviderConflict.field == conflict["field"], ProviderConflict.primary_source == conflict["primary_source"], ProviderConflict.secondary_source == conflict["secondary_source"], ProviderConflict.severity == conflict["severity"]).order_by(ProviderConflict.created_at.desc()).limit(25))
        return any(row.primary_value == conflict["primary_value"] and row.secondary_value == conflict["secondary_value"] and row.resolution == conflict["resolution"] for row in rows)
