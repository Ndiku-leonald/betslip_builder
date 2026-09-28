"""track whether a provider usage row represents an outbound request"""

from alembic import op
import sqlalchemy as sa

revision = "0003_provider_request_accounting"
down_revision = "0002_observation_timestamps"
branch_labels = None
depends_on = None


def _external_request_backfill_statement() -> sa.Update:
    provider_usage = sa.table(
        "provider_usage",
        sa.column("external_request", sa.Boolean()),
    )
    return provider_usage.update().where(provider_usage.c.external_request.is_(None)).values(external_request=sa.true())


def upgrade() -> None:
    op.add_column("provider_usage", sa.Column("external_request", sa.Boolean(), nullable=True, server_default=sa.true()))
    op.execute(_external_request_backfill_statement())


def downgrade() -> None:
    op.drop_column("provider_usage", "external_request")
