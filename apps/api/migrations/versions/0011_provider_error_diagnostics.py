"""Persist safe provider error classifications and reason codes."""

from alembic import op
import sqlalchemy as sa


revision = "0011_provider_error_diagnostics"
down_revision = "0010_provider_health_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("provider_usage", sa.Column("error_category", sa.String(length=50), nullable=True))
    op.add_column("provider_usage", sa.Column("reason_code", sa.String(length=80), nullable=True))
    op.add_column("provider_usage", sa.Column("error_key", sa.String(length=50), nullable=True))
    op.add_column("provider_health", sa.Column("reason_code", sa.String(length=80), nullable=True))
    op.add_column("provider_health", sa.Column("error_key", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("provider_health", "error_key")
    op.drop_column("provider_health", "reason_code")
    op.drop_column("provider_usage", "error_key")
    op.drop_column("provider_usage", "reason_code")
    op.drop_column("provider_usage", "error_category")
