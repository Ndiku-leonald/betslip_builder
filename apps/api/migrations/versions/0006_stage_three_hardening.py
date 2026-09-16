"""Add market participants and stored provider observations."""
from alembic import op
import sqlalchemy as sa


revision = "0006_stage_three_hardening"
down_revision = "0005_stage_three_market_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("odds_snapshots", sa.Column("participant", sa.String(20), nullable=False, server_default="none"))
    op.create_index("ix_odds_snapshots_participant", "odds_snapshots", ["participant"])
    op.create_table(
        "provider_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("fixture_id", sa.String(36), sa.ForeignKey("fixtures.id"), nullable=False),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("source_event_id", sa.String(160)),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_updated_at", sa.DateTime(timezone=True)),
        sa.Column("kickoff_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(30)),
        sa.Column("home_score", sa.Integer()),
        sa.Column("away_score", sa.Integer()),
        sa.Column("clock", sa.String(40)),
        sa.Column("period", sa.String(40)),
        sa.Column("canonical_home_team", sa.String(160)),
        sa.Column("canonical_away_team", sa.String(160)),
        sa.Column("payload", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_provider_observations_fixture_id", "provider_observations", ["fixture_id"])
    op.create_index("ix_provider_observations_provider", "provider_observations", ["provider"])
    op.create_index("ix_provider_observations_source_event_id", "provider_observations", ["source_event_id"])
    op.create_index("ix_provider_observations_observed_at", "provider_observations", ["observed_at"])


def downgrade() -> None:
    op.drop_index("ix_provider_observations_observed_at", table_name="provider_observations")
    op.drop_index("ix_provider_observations_source_event_id", table_name="provider_observations")
    op.drop_index("ix_provider_observations_provider", table_name="provider_observations")
    op.drop_index("ix_provider_observations_fixture_id", table_name="provider_observations")
    op.drop_table("provider_observations")
    op.drop_index("ix_odds_snapshots_participant", table_name="odds_snapshots")
    op.drop_column("odds_snapshots", "participant")
