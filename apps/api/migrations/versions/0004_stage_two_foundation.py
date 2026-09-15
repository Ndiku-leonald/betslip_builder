"""Add immutable Stage Two historical and prediction structures.

The Stage One migrations are intentionally left unchanged.  This migration is
additive so an existing deployment can upgrade without destroying history.
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_stage_two_foundation"
down_revision = "0003_provider_request_accounting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_versions", sa.Column("sport", sa.String(30), nullable=True))
    op.add_column("model_versions", sa.Column("algorithm", sa.String(80), nullable=True))
    op.add_column("model_versions", sa.Column("trained_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("model_versions", sa.Column("training_start", sa.DateTime(timezone=True), nullable=True))
    op.add_column("model_versions", sa.Column("training_end", sa.DateTime(timezone=True), nullable=True))
    op.add_column("model_versions", sa.Column("validation_start", sa.DateTime(timezone=True), nullable=True))
    op.add_column("model_versions", sa.Column("validation_end", sa.DateTime(timezone=True), nullable=True))
    op.add_column("model_versions", sa.Column("feature_version", sa.String(80), nullable=True))
    op.add_column("model_versions", sa.Column("parameters", sa.JSON(), nullable=True))
    op.add_column("model_versions", sa.Column("metrics", sa.JSON(), nullable=True))
    op.add_column("model_versions", sa.Column("artifact_path", sa.String(500), nullable=True))
    op.add_column("model_versions", sa.Column("sample_count", sa.Integer(), nullable=True))
    op.add_column("model_versions", sa.Column("status", sa.String(30), nullable=False, server_default="candidate"))
    op.create_index("ix_model_versions_sport", "model_versions", ["sport"])
    op.create_index("ix_model_versions_status", "model_versions", ["status"])

    for name, column in (
        ("sport", sa.Column("sport", sa.String(30), nullable=True)),
        ("generated_at", sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True)),
        ("prediction_type", sa.Column("prediction_type", sa.String(80), nullable=True)),
        ("data_cutoff_at", sa.Column("data_cutoff_at", sa.DateTime(timezone=True), nullable=True)),
        ("features_version", sa.Column("features_version", sa.String(80), nullable=True)),
    ):
        op.add_column("predictions", column)
    op.create_index("ix_predictions_sport", "predictions", ["sport"])

    op.create_table(
        "team_match_statistics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("fixture_id", sa.String(36), sa.ForeignKey("fixtures.id"), nullable=False),
        sa.Column("team_id", sa.String(36), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("is_home", sa.Boolean(), nullable=False),
        sa.Column("goals", sa.Integer()), sa.Column("shots", sa.Integer()), sa.Column("shots_on_target", sa.Integer()),
        sa.Column("possession", sa.Float()), sa.Column("corners", sa.Integer()), sa.Column("fouls", sa.Integer()),
        sa.Column("yellow_cards", sa.Integer()), sa.Column("red_cards", sa.Integer()), sa.Column("expected_goals", sa.Float()),
        sa.Column("points", sa.Integer()), sa.Column("field_goals_made", sa.Integer()), sa.Column("field_goals_attempted", sa.Integer()),
        sa.Column("three_pointers_made", sa.Integer()), sa.Column("three_pointers_attempted", sa.Integer()),
        sa.Column("free_throws_made", sa.Integer()), sa.Column("free_throws_attempted", sa.Integer()),
        sa.Column("offensive_rebounds", sa.Integer()), sa.Column("defensive_rebounds", sa.Integer()), sa.Column("total_rebounds", sa.Integer()),
        sa.Column("assists", sa.Integer()), sa.Column("steals", sa.Integer()), sa.Column("blocks", sa.Integer()),
        sa.Column("turnovers", sa.Integer()), sa.Column("personal_fouls", sa.Integer()),
        sa.Column("observed_at", sa.DateTime(timezone=True)), sa.Column("raw", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("fixture_id", "team_id", name="uq_team_match_stat"),
    )
    op.create_index("ix_team_match_statistics_fixture_id", "team_match_statistics", ["fixture_id"])
    op.create_index("ix_team_match_statistics_team_id", "team_match_statistics", ["team_id"])

    op.create_table(
        "fixture_features",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("fixture_id", sa.String(36), sa.ForeignKey("fixtures.id"), nullable=False),
        sa.Column("sport", sa.String(30), nullable=False), sa.Column("feature_version", sa.String(80), nullable=False),
        sa.Column("data_cutoff_at", sa.DateTime(timezone=True), nullable=False), sa.Column("values", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("data_quality", sa.JSON(), nullable=False, server_default="{}"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_fixture_features_fixture_id", "fixture_features", ["fixture_id"])
    op.create_index("ix_fixture_features_sport", "fixture_features", ["sport"])
    op.create_index("ix_fixture_features_data_cutoff_at", "fixture_features", ["data_cutoff_at"])

    op.create_table(
        "training_runs",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("model_version_id", sa.String(36), sa.ForeignKey("model_versions.id")),
        sa.Column("sport", sa.String(30), nullable=False), sa.Column("feature_version", sa.String(80), nullable=False),
        sa.Column("training_start", sa.DateTime(timezone=True)), sa.Column("training_end", sa.DateTime(timezone=True)),
        sa.Column("validation_start", sa.DateTime(timezone=True)), sa.Column("validation_end", sa.DateTime(timezone=True)),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("rows_excluded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("seed", sa.Integer()), sa.Column("parameters", sa.JSON(), nullable=False, server_default="{}"), sa.Column("metrics", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_training_runs_model_version_id", "training_runs", ["model_version_id"])
    op.create_index("ix_training_runs_sport", "training_runs", ["sport"])

    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("model_version_id", sa.String(36), sa.ForeignKey("model_versions.id")),
        sa.Column("sport", sa.String(30), nullable=False), sa.Column("start_at", sa.DateTime(timezone=True)), sa.Column("end_at", sa.DateTime(timezone=True)),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("metrics", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_backtest_runs_model_version_id", "backtest_runs", ["model_version_id"])
    op.create_index("ix_backtest_runs_sport", "backtest_runs", ["sport"])

    op.create_table(
        "backtest_predictions",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("backtest_run_id", sa.String(36), sa.ForeignKey("backtest_runs.id"), nullable=False),
        sa.Column("fixture_id", sa.String(36), sa.ForeignKey("fixtures.id"), nullable=False), sa.Column("model_version_id", sa.String(36), sa.ForeignKey("model_versions.id")),
        sa.Column("prediction_type", sa.String(80), nullable=False), sa.Column("raw_probability", sa.Float(), nullable=False), sa.Column("calibrated_probability", sa.Float()),
        sa.Column("actual_outcome", sa.Float(), nullable=False), sa.Column("data_cutoff_at", sa.DateTime(timezone=True), nullable=False), sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_backtest_predictions_backtest_run_id", "backtest_predictions", ["backtest_run_id"])
    op.create_index("ix_backtest_predictions_fixture_id", "backtest_predictions", ["fixture_id"])
    op.create_index("ix_backtest_predictions_model_version_id", "backtest_predictions", ["model_version_id"])


def downgrade() -> None:
    op.drop_table("backtest_predictions")
    op.drop_table("backtest_runs")
    op.drop_table("training_runs")
    op.drop_table("fixture_features")
    op.drop_table("team_match_statistics")
    op.drop_index("ix_predictions_sport", table_name="predictions")
    for name in ("features_version", "data_cutoff_at", "prediction_type", "generated_at", "sport"):
        op.drop_column("predictions", name)
    op.drop_index("ix_model_versions_status", table_name="model_versions")
    op.drop_index("ix_model_versions_sport", table_name="model_versions")
    for name in ("status", "sample_count", "artifact_path", "metrics", "parameters", "feature_version", "validation_end", "validation_start", "training_end", "training_start", "trained_at", "algorithm", "sport"):
        op.drop_column("model_versions", name)
