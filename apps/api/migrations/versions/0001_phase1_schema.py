"""create the immutable Phase 1 normalized sports schema"""

import sqlalchemy as sa
from alembic import op

revision = "0001_phase1_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sports_slug", "sports", ["slug"], unique=True)
    op.create_table(
        "countries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("code", sa.String(length=8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "competitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sport_id", sa.String(length=36), nullable=False),
        sa.Column("country_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("provider_id", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["country_id"], ["countries.id"]),
        sa.ForeignKeyConstraint(["sport_id"], ["sports.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_competitions_sport_id", "competitions", ["sport_id"], unique=False)
    op.create_table(
        "seasons",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("competition_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("provider_id", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["competition_id"], ["competitions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_seasons_competition_id", "seasons", ["competition_id"], unique=False)
    op.create_table(
        "teams",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sport_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("short_name", sa.String(length=80), nullable=True),
        sa.Column("logo_url", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["sport_id"], ["sports.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_teams_sport_id", "teams", ["sport_id"], unique=False)
    op.create_table(
        "players",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sport_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["sport_id"], ["sports.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_players_sport_id", "players", ["sport_id"], unique=False)
    op.create_table(
        "venues",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "fixtures",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sport_id", sa.String(length=36), nullable=False),
        sa.Column("competition_id", sa.String(length=36), nullable=True),
        sa.Column("season_id", sa.String(length=36), nullable=True),
        sa.Column("home_team_id", sa.String(length=36), nullable=False),
        sa.Column("away_team_id", sa.String(length=36), nullable=False),
        sa.Column("venue_id", sa.String(length=36), nullable=True),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("provider_fixture_id", sa.String(length=100), nullable=False),
        sa.Column("kickoff_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("status_detail", sa.String(length=80), nullable=True),
        sa.Column("home_score", sa.Integer(), nullable=True),
        sa.Column("away_score", sa.Integer(), nullable=True),
        sa.Column("period", sa.String(length=40), nullable=True),
        sa.Column("clock", sa.String(length=40), nullable=True),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("freshness", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["away_team_id"], ["teams.id"]),
        sa.ForeignKeyConstraint(["competition_id"], ["competitions.id"]),
        sa.ForeignKeyConstraint(["home_team_id"], ["teams.id"]),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"]),
        sa.ForeignKeyConstraint(["sport_id"], ["sports.id"]),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sport_id", "provider", "provider_fixture_id", name="uq_fixture_provider"),
    )
    for name, column in (("ix_fixtures_sport_id", "sport_id"), ("ix_fixtures_competition_id", "competition_id"), ("ix_fixtures_provider", "provider"), ("ix_fixtures_provider_fixture_id", "provider_fixture_id"), ("ix_fixtures_kickoff_at", "kickoff_at"), ("ix_fixtures_status", "status")):
        op.create_index(name, "fixtures", [column], unique=False)
    op.create_table(
        "provider_entity_mappings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("provider_entity_id", sa.String(length=100), nullable=False),
        sa.Column("internal_entity_id", sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "entity_type", "provider_entity_id", name="uq_provider_entity"),
    )
    for name, column in (("ix_provider_entity_mappings_provider", "provider"), ("ix_provider_entity_mappings_entity_type", "entity_type"), ("ix_provider_entity_mappings_internal_entity_id", "internal_entity_id")):
        op.create_index(name, "provider_entity_mappings", [column], unique=False)
    op.create_table(
        "match_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("fixture_id", sa.String(length=36), nullable=False),
        sa.Column("provider_event_id", sa.String(length=100), nullable=True),
        sa.Column("minute", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["fixture_id"], ["fixtures.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_match_events_fixture_id", "match_events", ["fixture_id"], unique=False)
    op.create_table(
        "match_stat_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("fixture_id", sa.String(length=36), nullable=False),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("freshness", sa.String(length=30), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["fixture_id"], ["fixtures.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_match_stat_snapshots_fixture_id", "match_stat_snapshots", ["fixture_id"], unique=False)
    for table in ("injuries", "standings_snapshots", "team_form_snapshots", "weather_snapshots"):
        op.create_table(
            table,
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("fixture_id", sa.String(length=36), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["fixture_id"], ["fixtures.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(f"ix_{table}_fixture_id", table, ["fixture_id"], unique=False)
    op.create_table(
        "lineups",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("fixture_id", sa.String(length=36), nullable=False),
        sa.Column("team_id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["fixture_id"], ["fixtures.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lineups_fixture_id", "lineups", ["fixture_id"], unique=False)
    op.create_table(
        "markets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sport_id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["sport_id"], ["sports.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "market_selections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("market_id", sa.String(length=36), nullable=False),
        sa.Column("fixture_id", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["fixture_id"], ["fixtures.id"]),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "odds_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("fixture_id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["fixture_id"], ["fixtures.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_odds_snapshots_fixture_id", "odds_snapshots", ["fixture_id"], unique=False)
    op.create_table(
        "provider_usage",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("endpoint", sa.String(length=200), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), nullable=False),
        sa.Column("rate_limit_remaining", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_provider_usage_provider", "provider_usage", ["provider"], unique=False)
    op.create_index("ix_provider_usage_requested_at", "provider_usage", ["requested_at"], unique=False)
    op.create_table(
        "provider_health",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("configured", sa.Boolean(), nullable=False),
        sa.Column("healthy", sa.Boolean(), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_latency_ms", sa.Float(), nullable=True),
        sa.Column("calls_today", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider"),
    )
    op.create_table(
        "data_conflicts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=60), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "model_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("version", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "predictions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("fixture_id", sa.String(length=36), nullable=False),
        sa.Column("model_version_id", sa.String(length=36), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["fixture_id"], ["fixtures.id"]),
        sa.ForeignKeyConstraint(["model_version_id"], ["model_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_predictions_fixture_id", "predictions", ["fixture_id"], unique=False)
    op.create_table(
        "slips",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("risk", sa.String(length=30), nullable=False),
        sa.Column("target_odds", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "slip_legs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("slip_id", sa.String(length=36), nullable=False),
        sa.Column("market_selection_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["market_selection_id"], ["market_selections.id"]),
        sa.ForeignKeyConstraint(["slip_id"], ["slips.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_slip_legs_slip_id", "slip_legs", ["slip_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_slip_legs_slip_id", table_name="slip_legs")
    op.drop_table("slip_legs")
    op.drop_table("slips")
    op.drop_index("ix_predictions_fixture_id", table_name="predictions")
    op.drop_table("predictions")
    op.drop_table("model_versions")
    op.drop_table("data_conflicts")
    op.drop_table("provider_health")
    op.drop_index("ix_provider_usage_requested_at", table_name="provider_usage")
    op.drop_index("ix_provider_usage_provider", table_name="provider_usage")
    op.drop_table("provider_usage")
    op.drop_index("ix_odds_snapshots_fixture_id", table_name="odds_snapshots")
    op.drop_table("odds_snapshots")
    op.drop_table("market_selections")
    op.drop_table("markets")
    op.drop_index("ix_lineups_fixture_id", table_name="lineups")
    op.drop_table("lineups")
    for table in ("weather_snapshots", "team_form_snapshots", "standings_snapshots", "injuries"):
        op.drop_index(f"ix_{table}_fixture_id", table_name=table)
        op.drop_table(table)
    op.drop_index("ix_match_stat_snapshots_fixture_id", table_name="match_stat_snapshots")
    op.drop_table("match_stat_snapshots")
    op.drop_index("ix_match_events_fixture_id", table_name="match_events")
    op.drop_table("match_events")
    for name in ("ix_provider_entity_mappings_internal_entity_id", "ix_provider_entity_mappings_entity_type", "ix_provider_entity_mappings_provider"):
        op.drop_index(name, table_name="provider_entity_mappings")
    op.drop_table("provider_entity_mappings")
    for name in ("ix_fixtures_status", "ix_fixtures_kickoff_at", "ix_fixtures_provider_fixture_id", "ix_fixtures_provider", "ix_fixtures_competition_id", "ix_fixtures_sport_id"):
        op.drop_index(name, table_name="fixtures")
    op.drop_table("fixtures")
    op.drop_table("venues")
    op.drop_index("ix_players_sport_id", table_name="players")
    op.drop_table("players")
    op.drop_index("ix_teams_sport_id", table_name="teams")
    op.drop_table("teams")
    op.drop_index("ix_seasons_competition_id", table_name="seasons")
    op.drop_table("seasons")
    op.drop_index("ix_competitions_sport_id", table_name="competitions")
    op.drop_table("competitions")
    op.drop_index("ix_sports_slug", table_name="sports")
    op.drop_table("countries")
    op.drop_table("sports")
