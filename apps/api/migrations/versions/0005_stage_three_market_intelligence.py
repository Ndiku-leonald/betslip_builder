"""Add immutable Stage Three market snapshots and provider conflicts."""
from alembic import op
import sqlalchemy as sa

revision = "0005_stage_three_market_intelligence"
down_revision = "0004_stage_two_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = [
        sa.Column("source_event_id", sa.String(160)), sa.Column("bookmaker", sa.String(120)),
        sa.Column("market_family", sa.String(60)), sa.Column("market_type", sa.String(80)),
        sa.Column("period", sa.String(40)), sa.Column("selection", sa.String(120)),
        sa.Column("line", sa.Float()), sa.Column("decimal_odds", sa.Float()),
        sa.Column("market_status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("settlement_semantics", sa.String(60), nullable=False, server_default="full_game"),
        sa.Column("observed_at", sa.DateTime(timezone=True)), sa.Column("provider_updated_at", sa.DateTime(timezone=True)),
    ]
    for column in columns:
        op.add_column("odds_snapshots", column)
    for name, column in (("source_event_id", "source_event_id"), ("bookmaker", "bookmaker"), ("market_family", "market_family"), ("observed_at", "observed_at")):
        op.create_index(f"ix_odds_snapshots_{name}", "odds_snapshots", [column])
    op.create_table(
        "provider_conflicts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("fixture_id", sa.String(36), sa.ForeignKey("fixtures.id"), nullable=False),
        sa.Column("entity_type", sa.String(60), nullable=False), sa.Column("field", sa.String(80), nullable=False),
        sa.Column("primary_source", sa.String(60), nullable=False), sa.Column("secondary_source", sa.String(60), nullable=False),
        sa.Column("primary_value", sa.JSON()), sa.Column("secondary_value", sa.JSON()),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False), sa.Column("severity", sa.String(30), nullable=False),
        sa.Column("resolution", sa.String(80)), sa.Column("resolved_source", sa.String(60)), sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_provider_conflicts_fixture_id", "provider_conflicts", ["fixture_id"])
    op.create_index("ix_provider_conflicts_observed_at", "provider_conflicts", ["observed_at"])


def downgrade() -> None:
    op.drop_index("ix_provider_conflicts_observed_at", table_name="provider_conflicts")
    op.drop_index("ix_provider_conflicts_fixture_id", table_name="provider_conflicts")
    op.drop_table("provider_conflicts")
    for name in ("provider_updated_at", "observed_at", "settlement_semantics", "market_status", "decimal_odds", "line", "selection", "period", "market_type", "market_family", "bookmaker", "source_event_id"):
        op.drop_column("odds_snapshots", name)
