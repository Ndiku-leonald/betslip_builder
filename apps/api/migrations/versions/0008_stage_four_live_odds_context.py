"""Record whether an odds snapshot was obtained in live context."""

from alembic import op
import sqlalchemy as sa


revision = "0008_stage_four_live_odds_context"
down_revision = "0007_stage_four_live_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("odds_snapshots", sa.Column("is_live", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_odds_snapshots_is_live", "odds_snapshots", ["is_live"])


def downgrade() -> None:
    op.drop_index("ix_odds_snapshots_is_live", table_name="odds_snapshots")
    op.drop_column("odds_snapshots", "is_live")
