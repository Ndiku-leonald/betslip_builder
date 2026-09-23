"""Add immutable Stage Four live observations, predictions, and evaluations."""

from alembic import op
import sqlalchemy as sa


revision = "0007_stage_four_live_intelligence"
down_revision = "0006_stage_three_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "live_match_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("fixture_id", sa.String(36), sa.ForeignKey("fixtures.id"), nullable=False),
        sa.Column("source_provider", sa.String(60), nullable=False),
        sa.Column("source_event_id", sa.String(160)),
        sa.Column("source_timestamp", sa.DateTime(timezone=True)),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("period", sa.String(40)),
        sa.Column("clock", sa.String(40)),
        sa.Column("minute", sa.Integer()),
        sa.Column("stoppage_time", sa.Integer()),
        sa.Column("home_score", sa.Integer()),
        sa.Column("away_score", sa.Integer()),
        sa.Column("halftime_home_score", sa.Integer()),
        sa.Column("halftime_away_score", sa.Integer()),
        sa.Column("statistics", sa.JSON(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("auxiliary", sa.JSON(), nullable=False),
        sa.Column("data_quality", sa.JSON(), nullable=False),
        sa.UniqueConstraint("fixture_id", "source_provider", "observed_at", name="uq_live_match_observation"),
    )
    op.create_index("ix_live_match_snapshots_fixture_id", "live_match_snapshots", ["fixture_id"])
    op.create_index("ix_live_match_snapshots_source_provider", "live_match_snapshots", ["source_provider"])
    op.create_index("ix_live_match_snapshots_source_event_id", "live_match_snapshots", ["source_event_id"])
    op.create_index("ix_live_match_snapshots_source_timestamp", "live_match_snapshots", ["source_timestamp"])
    op.create_index("ix_live_match_snapshots_observed_at", "live_match_snapshots", ["observed_at"])
    op.create_index("ix_live_match_snapshots_ingested_at", "live_match_snapshots", ["ingested_at"])
    op.create_index("ix_live_match_snapshots_status", "live_match_snapshots", ["status"])

    op.create_table(
        "live_prediction_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("fixture_id", sa.String(36), sa.ForeignKey("fixtures.id"), nullable=False),
        sa.Column("live_match_snapshot_id", sa.String(36), sa.ForeignKey("live_match_snapshots.id"), nullable=False),
        sa.Column("pre_match_prediction_id", sa.String(36), sa.ForeignKey("predictions.id")),
        sa.Column("model_version_id", sa.String(36), sa.ForeignKey("model_versions.id")),
        sa.Column("sport", sa.String(30), nullable=False),
        sa.Column("model_version", sa.String(80)),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pre_match_probability", sa.JSON(), nullable=False),
        sa.Column("live_probability", sa.JSON(), nullable=False),
        sa.Column("probability_delta", sa.JSON(), nullable=False),
        sa.Column("markets", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("data_quality", sa.JSON(), nullable=False),
        sa.Column("calibration_status", sa.String(40), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.UniqueConstraint("fixture_id", "observed_at", name="uq_live_prediction_observation"),
    )
    op.create_index("ix_live_prediction_snapshots_fixture_id", "live_prediction_snapshots", ["fixture_id"])
    op.create_index("ix_live_prediction_snapshots_live_match_snapshot_id", "live_prediction_snapshots", ["live_match_snapshot_id"])
    op.create_index("ix_live_prediction_snapshots_pre_match_prediction_id", "live_prediction_snapshots", ["pre_match_prediction_id"])
    op.create_index("ix_live_prediction_snapshots_model_version_id", "live_prediction_snapshots", ["model_version_id"])
    op.create_index("ix_live_prediction_snapshots_sport", "live_prediction_snapshots", ["sport"])
    op.create_index("ix_live_prediction_snapshots_observed_at", "live_prediction_snapshots", ["observed_at"])
    op.create_index("ix_live_prediction_snapshots_generated_at", "live_prediction_snapshots", ["generated_at"])

    op.create_table(
        "live_market_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("fixture_id", sa.String(36), sa.ForeignKey("fixtures.id"), nullable=False),
        sa.Column("live_prediction_snapshot_id", sa.String(36), sa.ForeignKey("live_prediction_snapshots.id"), nullable=False),
        sa.Column("odds_snapshot_id", sa.String(36), sa.ForeignKey("odds_snapshots.id")),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("bookmaker", sa.String(120)),
        sa.Column("market_family", sa.String(60), nullable=False),
        sa.Column("market_type", sa.String(80)),
        sa.Column("participant", sa.String(20), nullable=False),
        sa.Column("selection", sa.String(120), nullable=False),
        sa.Column("line", sa.Float()),
        sa.Column("decimal_odds", sa.Float()),
        sa.Column("market_status", sa.String(30), nullable=False),
        sa.Column("odds_observed_at", sa.DateTime(timezone=True)),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_probability", sa.Float()),
        sa.Column("push_probability", sa.Float()),
        sa.Column("expected_value", sa.Float()),
        sa.Column("suitability", sa.String(40), nullable=False),
        sa.Column("value_payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_live_market_snapshots_fixture_id", "live_market_snapshots", ["fixture_id"])
    op.create_index("ix_live_market_snapshots_live_prediction_snapshot_id", "live_market_snapshots", ["live_prediction_snapshot_id"])
    op.create_index("ix_live_market_snapshots_odds_snapshot_id", "live_market_snapshots", ["odds_snapshot_id"])
    op.create_index("ix_live_market_snapshots_provider", "live_market_snapshots", ["provider"])
    op.create_index("ix_live_market_snapshots_bookmaker", "live_market_snapshots", ["bookmaker"])
    op.create_index("ix_live_market_snapshots_market_family", "live_market_snapshots", ["market_family"])
    op.create_index("ix_live_market_snapshots_market_status", "live_market_snapshots", ["market_status"])
    op.create_index("ix_live_market_snapshots_evaluated_at", "live_market_snapshots", ["evaluated_at"])


def downgrade() -> None:
    op.drop_index("ix_live_market_snapshots_evaluated_at", table_name="live_market_snapshots")
    op.drop_index("ix_live_market_snapshots_market_status", table_name="live_market_snapshots")
    op.drop_index("ix_live_market_snapshots_market_family", table_name="live_market_snapshots")
    op.drop_index("ix_live_market_snapshots_bookmaker", table_name="live_market_snapshots")
    op.drop_index("ix_live_market_snapshots_provider", table_name="live_market_snapshots")
    op.drop_index("ix_live_market_snapshots_odds_snapshot_id", table_name="live_market_snapshots")
    op.drop_index("ix_live_market_snapshots_live_prediction_snapshot_id", table_name="live_market_snapshots")
    op.drop_index("ix_live_market_snapshots_fixture_id", table_name="live_market_snapshots")
    op.drop_table("live_market_snapshots")

    op.drop_index("ix_live_prediction_snapshots_generated_at", table_name="live_prediction_snapshots")
    op.drop_index("ix_live_prediction_snapshots_observed_at", table_name="live_prediction_snapshots")
    op.drop_index("ix_live_prediction_snapshots_sport", table_name="live_prediction_snapshots")
    op.drop_index("ix_live_prediction_snapshots_model_version_id", table_name="live_prediction_snapshots")
    op.drop_index("ix_live_prediction_snapshots_pre_match_prediction_id", table_name="live_prediction_snapshots")
    op.drop_index("ix_live_prediction_snapshots_live_match_snapshot_id", table_name="live_prediction_snapshots")
    op.drop_index("ix_live_prediction_snapshots_fixture_id", table_name="live_prediction_snapshots")
    op.drop_table("live_prediction_snapshots")

    op.drop_index("ix_live_match_snapshots_status", table_name="live_match_snapshots")
    op.drop_index("ix_live_match_snapshots_ingested_at", table_name="live_match_snapshots")
    op.drop_index("ix_live_match_snapshots_observed_at", table_name="live_match_snapshots")
    op.drop_index("ix_live_match_snapshots_source_timestamp", table_name="live_match_snapshots")
    op.drop_index("ix_live_match_snapshots_source_event_id", table_name="live_match_snapshots")
    op.drop_index("ix_live_match_snapshots_source_provider", table_name="live_match_snapshots")
    op.drop_index("ix_live_match_snapshots_fixture_id", table_name="live_match_snapshots")
    op.drop_table("live_match_snapshots")
