"""Persist bounded structural provider-error diagnostics."""

from alembic import op
import sqlalchemy as sa


revision = "0012_provider_error_shape"
down_revision = "0011_provider_error_diagnostics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("provider_usage", "provider_health"):
        op.add_column(table, sa.Column("error_shape", sa.String(length=30), nullable=True))
        op.add_column(table, sa.Column("error_entry_count", sa.Integer(), nullable=True))
        op.add_column(table, sa.Column("semantic_tags", sa.JSON(), nullable=True))
        op.add_column(table, sa.Column("diagnostic_truncated", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    for table in ("provider_health", "provider_usage"):
        op.drop_column(table, "diagnostic_truncated")
        op.drop_column(table, "semantic_tags")
        op.drop_column(table, "error_entry_count")
        op.drop_column(table, "error_shape")
