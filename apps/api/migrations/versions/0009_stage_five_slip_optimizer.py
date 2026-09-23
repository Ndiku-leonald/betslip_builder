"""Add auditable Stage Five slip and leg snapshots."""

from alembic import op
import sqlalchemy as sa


revision = "0009_stage_five_slip_optimizer"
down_revision = "0008_stage_four_live_odds_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    slip_columns = [
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="prematch"),
        sa.Column("profile", sa.String(length=20), nullable=False, server_default="balanced"),
        sa.Column("bookmaker", sa.String(length=120), nullable=True),
        sa.Column("provider", sa.String(length=60), nullable=True),
        sa.Column("achieved_odds", sa.Float(), nullable=True),
        sa.Column("optimization_version", sa.String(length=80), nullable=False, server_default="stage-five-v1"),
        sa.Column("joint_probability", sa.Float(), nullable=True),
        sa.Column("adjusted_score", sa.Float(), nullable=True),
        sa.Column("correlation_risk", sa.String(length=20), nullable=True),
        sa.Column("target_reached", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("configuration_snapshot", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("warnings", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("diagnostics", sa.JSON(), nullable=False, server_default="{}"),
    ]
    for column in slip_columns:
        op.add_column("slips", column)
    with op.batch_alter_table("slip_legs") as batch:
        batch.alter_column("market_selection_id", existing_type=sa.String(length=36), nullable=True)
        batch.add_column(sa.Column("odds_snapshot_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("fixture_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key("fk_slip_legs_odds_snapshot_id", "odds_snapshots", ["odds_snapshot_id"], ["id"])
        batch.create_foreign_key("fk_slip_legs_fixture_id", "fixtures", ["fixture_id"], ["id"])
        batch.add_column(sa.Column("leg_order", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("snapshot", sa.JSON(), nullable=False, server_default="{}"))
    op.create_index("ix_slip_legs_odds_snapshot_id", "slip_legs", ["odds_snapshot_id"])
    op.create_index("ix_slip_legs_fixture_id", "slip_legs", ["fixture_id"])


def downgrade() -> None:
    op.drop_index("ix_slip_legs_fixture_id", table_name="slip_legs")
    op.drop_index("ix_slip_legs_odds_snapshot_id", table_name="slip_legs")
    with op.batch_alter_table("slip_legs") as batch:
        batch.drop_constraint("fk_slip_legs_fixture_id", type_="foreignkey")
        batch.drop_constraint("fk_slip_legs_odds_snapshot_id", type_="foreignkey")
        batch.drop_column("snapshot")
        batch.drop_column("leg_order")
        batch.drop_column("fixture_id")
        batch.drop_column("odds_snapshot_id")
        batch.alter_column("market_selection_id", existing_type=sa.String(length=36), nullable=False)
    for column in ("diagnostics", "warnings", "configuration_snapshot", "target_reached", "correlation_risk", "adjusted_score", "joint_probability", "optimization_version", "achieved_odds", "provider", "bookmaker", "profile", "mode"):
        op.drop_column("slips", column)
