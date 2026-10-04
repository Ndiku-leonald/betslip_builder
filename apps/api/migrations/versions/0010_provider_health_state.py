"""Persist truthful provider health state classifications."""

from alembic import op
import sqlalchemy as sa


revision = "0010_provider_health_state"
down_revision = "0009_stage_five_slip_optimizer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("provider_health", sa.Column("state", sa.String(length=40), nullable=False, server_default="unknown"))


def downgrade() -> None:
    op.drop_column("provider_health", "state")
